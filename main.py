import os, json, re, traceback, importlib, inspect, asyncio, mimetypes
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
    migrate_all_old_dbs, _use_turso, _turso_debug
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        migrate_all_old_dbs()
    except Exception:
        pass
    yield

app = FastAPI(title="Cheka Clips Hub", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

_jinja_env = Environment(loader=FileSystemLoader("templates"), auto_reload=False)

def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip('#')
    return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"

_jinja_env.filters['hex_to_rgb'] = _hex_to_rgb

def _jinja_ts_to_sec(ts: str) -> int:
    try:
        return _ts_to_sec(ts or "0")
    except Exception:
        return 0

_jinja_env.filters['ts_to_sec'] = _jinja_ts_to_sec

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

def _is_admin(request: Request, admin: str | None = None) -> bool:
    return admin == "1" or request.cookies.get("admin") == "1"

def _admin_query(is_admin: bool) -> str:
    return "?admin=1" if is_admin else ""

def _get_engine(cfg: dict):
    em = importlib.import_module(f"engines.{cfg['engine']}")
    importlib.reload(em)
    return em

def _viral_keys(channel_id: str) -> set[str]:
    return {
        f"{v['video_id']}:{int(v['clip_start'])}:{int(v['clip_end'])}"
        for v in get_viral_clips(channel_id, limit=500)
    }

def _render_channel(
    request: Request,
    channel_id: str,
    *,
    admin: str | None = None,
    clips=None,
    video_info=None,
    error: str | None = None,
    skip_processing: bool = False,
    current_analysis_id: int | None = None,
    edit_mode: bool = False,
    notice: str | None = None,
):
    cfg = get_channel(channel_id)
    if not cfg:
        return HTMLResponse("Canal no encontrado", status_code=404)

    is_admin = _is_admin(request, admin)
    accent = ACCENTS.get(channel_id, "#65A30D")
    analyses = get_analyses(channel=channel_id)
    db_info = _turso_debug()
    use_turso = _use_turso()
    viral_keys_set = _viral_keys(channel_id) if is_admin and clips else set()

    return render("channel.html",
        channel=cfg, accent=accent, is_admin=is_admin,
        analyses=analyses, db_info=db_info, use_turso=use_turso,
        clips=clips, video_info=video_info or {}, error=error,
        skip_processing=skip_processing, viral_keys_set=viral_keys_set,
        admin="1" if is_admin else admin, current_analysis_id=current_analysis_id,
        edit_mode=edit_mode, notice=notice)

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return render("landing.html", is_admin=_is_admin(request))

@app.get("/ch/{channel_id}", response_class=HTMLResponse)
async def channel_view(
    request: Request,
    channel_id: str,
    admin: str = Query(None),
):
    return _render_channel(request, channel_id, admin=admin)

@app.post("/ch/{channel_id}/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    channel_id: str,
    url: str = Form(...),
    api_key: str = Form(...),
    content_focus: str = Form(""),
    admin: str = Query(None),
):
    cfg = get_channel(channel_id)
    if not cfg:
        return HTMLResponse("Canal no encontrado", status_code=404)
    is_admin = _is_admin(request, admin)
    error = None
    clips = []
    video_info = {}
    skip_processing = False
    analysis_id = None

    try:
        em = _get_engine(cfg)
        ep = getattr(em, cfg["entry_point"])
        gid = getattr(em, "get_video_id", lambda x: "")
        gti = getattr(em, "get_video_title", lambda x: "")
        gdu = getattr(em, "get_video_duration", lambda x: 0)

        video_id = gid(url)
        if video_id:
            existente = get_analysis_by_video_id(channel_id, video_id)
            if existente:
                target = f"/ch/{channel_id}/analysis/{existente['id']}{_admin_query(is_admin)}"
                return RedirectResponse(url=target, status_code=303)

        if not skip_processing:
            virales = get_viral_clips(channel_id, limit=5) if is_admin else None

            def on_progress(pct, msg):
                pass

            kwargs = {
                "lang": "es",
                "progress_callback": on_progress,
                "viral_examples": virales,
            }
            if "content_focus" in inspect.signature(ep).parameters:
                kwargs["content_focus"] = content_focus.strip()
            result = ep(url, api_key, **kwargs)
            clips = result
            video_info = {"id": gid(url), "title": gti(url), "duration": gdu(url)}
            if clips:
                analysis_id = save_analysis(
                    channel=channel_id,
                    video_url=url,
                    video_id=video_info.get("id", ""),
                    video_title=video_info.get("title", ""),
                    video_duration=video_info.get("duration", 0),
                    clips=clips,
                )
                target = f"/ch/{channel_id}/analysis/{analysis_id}{_admin_query(is_admin)}"
                return RedirectResponse(url=target, status_code=303)

    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    return _render_channel(request, channel_id, admin=admin, clips=clips,
        video_info=video_info, error=error, skip_processing=skip_processing,
        current_analysis_id=analysis_id)

@app.get("/ch/{channel_id}/analysis/{analysis_id}", response_class=HTMLResponse)
async def view_analysis(request: Request, channel_id: str, analysis_id: int, admin: str = Query(None)):
    cfg = get_channel(channel_id)
    if not cfg:
        return HTMLResponse("Canal no encontrado", status_code=404)
    an = get_analysis(analysis_id)
    if not an:
        return HTMLResponse("Análisis no encontrado", status_code=404)
    return _render_channel(request, channel_id, admin=admin,
        clips=an["clips"],
        video_info={"id": an["video_id"], "title": an["video_title"], "duration": an["video_duration"]},
        skip_processing=True, current_analysis_id=analysis_id)

@app.get("/ch/{channel_id}/analysis/{analysis_id}/edit", response_class=HTMLResponse)
async def edit_analysis(request: Request, channel_id: str, analysis_id: int, admin: str = Query(None)):
    if not _is_admin(request, admin):
        return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}", status_code=302)
    an = get_analysis(analysis_id)
    if not an:
        return HTMLResponse("Análisis no encontrado", status_code=404)
    return _render_channel(request, channel_id, admin="1",
        clips=an["clips"],
        video_info={"id": an["video_id"], "title": an["video_title"], "duration": an["video_duration"]},
        skip_processing=True, current_analysis_id=analysis_id, edit_mode=True)

@app.post("/ch/{channel_id}/analysis/{analysis_id}/clips/{clip_index}/delete", response_class=HTMLResponse)
async def delete_clip_route(request: Request, channel_id: str, analysis_id: int, clip_index: int, admin: str = Query(None)):
    if not _is_admin(request, admin):
        return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}", status_code=302)
    an = get_analysis(analysis_id)
    if not an:
        return HTMLResponse("Análisis no encontrado", status_code=404)
    clips = list(an["clips"])
    if 0 <= clip_index < len(clips):
        del clips[clip_index]
        update_analysis(analysis_id, clips)
    return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}/edit?admin=1", status_code=303)

@app.post("/ch/{channel_id}/analysis/{analysis_id}/clips/{clip_index}/viral", response_class=HTMLResponse)
async def toggle_viral_clip_route(request: Request, channel_id: str, analysis_id: int, clip_index: int, admin: str = Query(None)):
    if not _is_admin(request, admin):
        return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}", status_code=302)
    an = get_analysis(analysis_id)
    if not an:
        return HTMLResponse("Análisis no encontrado", status_code=404)
    clips = an["clips"]
    if not (0 <= clip_index < len(clips)):
        return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}?admin=1", status_code=303)

    clip = clips[clip_index]
    video_id = an.get("video_id", "")
    start = _ts_to_sec(clip.get("start", "0"))
    end = _ts_to_sec(clip.get("end", "0"))
    key = f"{video_id}:{start}:{end}"
    if key in _viral_keys(channel_id):
        delete_viral_clip(channel_id, video_id, start, end)
    else:
        save_viral_clip(
            channel_id,
            video_id,
            an.get("video_title", ""),
            start,
            end,
            clip.get("title", ""),
            clip.get("hook", ""),
            clip.get("descripcion", ""),
            clip.get("transcripcion", ""),
            clip.get("confidence", 0),
        )
    suffix = "/edit?admin=1" if request.headers.get("referer", "").endswith("/edit?admin=1") else "?admin=1"
    return RedirectResponse(url=f"/ch/{channel_id}/analysis/{analysis_id}{suffix}", status_code=303)

@app.post("/ch/{channel_id}/analysis/{analysis_id}/delete", response_class=HTMLResponse)
async def delete_analysis_route(request: Request, channel_id: str, analysis_id: int, admin: str = Query(None)):
    is_admin = _is_admin(request, admin)
    if not is_admin:
        return RedirectResponse(url=f"/ch/{channel_id}", status_code=302)
    delete_analysis(analysis_id)
    return RedirectResponse(url=f"/ch/{channel_id}{_admin_query(is_admin)}", status_code=302)

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, admin: str = Query(None)):
    if _is_admin(request, admin):
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

@app.post("/admin/logout", response_class=HTMLResponse)
async def admin_logout():
    resp = RedirectResponse(url="/admin", status_code=302)
    resp.delete_cookie("admin")
    return resp

@app.get("/api/analyses", response_class=HTMLResponse)
async def get_analyses_api(channel: str = Query(None)):
    rows = get_analyses(channel=channel or "")
    return HTMLResponse(json.dumps([dict(r) for r in rows], ensure_ascii=False), media_type="application/json")
