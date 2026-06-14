import os, json, re, traceback, importlib, asyncio, mimetypes
mimetypes.add_type('image/webp', '.webp')
mimetypes.add_type('font/woff2', '.woff2')
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from channels import get_channel, list_channels
from database import (
    init_db, save_analysis, get_analyses, get_analysis,
    update_analysis, delete_analysis, save_viral_clip,
    delete_viral_clip, get_viral_clips, get_analysis_by_video_id,
    _use_turso, _turso_debug
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Cheka Clips Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

_jinja_env = Environment(loader=FileSystemLoader("templates"), auto_reload=False)

def render(name: str, **context):
    t = _jinja_env.get_template(name)
    return HTMLResponse(t.render(context))

ACCENTS = {"antauro_tv": "#65A30D", "deepskill": "#2563EB", "general": "#A855F7"}

_ADMIN_USER = os.environ.get("ADMIN_USERNAME", "")
_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "")

def _get_admin_creds():
    user = _ADMIN_USER
    pwd = _ADMIN_PASS
    return user, pwd

def _ts_to_sec(ts):
    parts = ts.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
    if len(parts) == 2: return parts[0]*60 + parts[1]
    return parts[0] if parts else 0

def fmt_dur(s):
    m, s_ = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s_:02d}s"

def fmt_cdur(s):
    if s < 60: return f"{s}s"
    m, s_ = divmod(s, 60)
    if m < 60: return f"{m}m {s_:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"

def sc_pct(c): return f"{int(c*100)}%"

def badge_pct(c):
    bg = "#16A34A" if c>=0.9 else "#D97706" if c>=0.75 else "#DC2626"
    return f'<span style="background:{bg};color:#fff;padding:0.04rem 0.4rem;font-weight:700;font-size:0.65rem">{sc_pct(c)}</span>'

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return render("landing.html")

@app.get("/ch/{channel_id}", response_class=HTMLResponse)
async def channel_view(
    request: Request,
    channel_id: str,
    admin: str = Query(None),
):
    cfg = get_channel(channel_id)
    if not cfg:
        return HTMLResponse("Canal no encontrado", status_code=404)

    is_admin = admin == "1" or request.cookies.get("admin") == "1"
    accent = ACCENTS.get(channel_id, "#65A30D")
    analyses = get_analyses(channel=channel_id)
    db_info = _turso_debug()
    use_turso = _use_turso()

    return render("channel.html",
        channel=cfg, accent=accent, is_admin=is_admin,
        analyses=analyses, db_info=db_info, use_turso=use_turso,
        clips=None, video_info={}, error=None, skip_processing=False,
        viral_keys_set=set())

@app.post("/ch/{channel_id}/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    channel_id: str,
    url: str = Form(...),
    api_key: str = Form(...),
    admin: str = Query(None),
):
    cfg = get_channel(channel_id)
    if not cfg:
        return HTMLResponse("Canal no encontrado", status_code=404)
    is_admin = admin == "1" or request.cookies.get("admin") == "1"
    accent = ACCENTS.get(channel_id, "#65A30D")
    error = None
    clips = []
    video_info = {}
    skip_processing = False

    try:
        em = importlib.import_module(f"engines.{cfg['engine']}")
        importlib.reload(em)
        ep = getattr(em, cfg["entry_point"])
        gid = getattr(em, "get_video_id", lambda x: "")
        gti = getattr(em, "get_video_title", lambda x: "")
        gdu = getattr(em, "get_video_duration", lambda x: 0)
        t2s = getattr(em, "ts_to_seconds", lambda x: 0)
        gcv_func = getattr(em, "generar_copy_viral", None)

        video_id = gid(url)
        if video_id:
            existente = get_analysis_by_video_id(channel_id, video_id)
            if existente:
                clips = existente["clips"]
                video_info = {"id": video_id, "title": existente["video_title"], "duration": 0}
                skip_processing = True

        if not skip_processing:
            virales = get_viral_clips(channel_id, limit=5) if is_admin else None

            def on_progress(pct, msg):
                pass

            result = ep(url, api_key, lang="es", progress_callback=on_progress, viral_examples=virales)
            clips = result
            video_info = {"id": gid(url), "title": gti(url), "duration": gdu(url)}

    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    analyses = get_analyses(channel=channel_id)
    db_info = _turso_debug()
    use_turso = _use_turso()

    viral_clips_list = []
    viral_keys_set = set()
    if is_admin and clips:
        viral_clips_list = get_viral_clips(channel_id, limit=500)
        viral_keys_set = {f"{v['video_id']}:{int(v['clip_start'])}:{int(v['clip_end'])}" for v in viral_clips_list}

    return render("channel.html",
        channel=cfg, accent=accent, is_admin=is_admin,
        analyses=analyses, db_info=db_info, use_turso=use_turso,
        clips=clips, video_info=video_info, error=error,
        skip_processing=skip_processing, viral_keys_set=viral_keys_set)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, admin: str = Query(None)):
    if admin == "1":
        channels = [ch for ch in list_channels() if ch["id"] != "general"]
        for ch in channels:
            ch["analysis_count"] = len(get_analyses(channel=ch["id"]))
        return render("admin_panel.html", channels=channels, accents=ACCENTS)
    resp = render("admin.html", error=None)
    resp.delete_cookie("admin")
    return resp

@app.post("/admin", response_class=HTMLResponse)
async def admin_auth(request: Request, username: str = Form(...), password: str = Form(...)):
    user, pwd = _get_admin_creds()
    if not user or not pwd:
        return render("admin.html", error="No hay credenciales configuradas")
    if username == user and password == pwd:
        resp = RedirectResponse(url="/admin?admin=1", status_code=302)
        resp.set_cookie(key="admin", value="1", max_age=86400)
        return resp
    return render("admin.html", error="Credenciales incorrectas")

@app.get("/api/analyses", response_class=HTMLResponse)
async def get_analyses_api(channel: str = Query(None)):
    rows = get_analyses(channel=channel or "")
    return HTMLResponse(json.dumps([dict(r) for r in rows], ensure_ascii=False), media_type="application/json")
