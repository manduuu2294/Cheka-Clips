import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json, importlib, traceback, streamlit as st
import os  # debug
from channels import get_channel, list_channels
from database import init_db, save_analysis, get_analyses, get_analysis, update_analysis, delete_analysis, migrate_all_old_dbs, save_viral_clip, delete_viral_clip, get_viral_clips, get_analysis_by_video_id

if "turso_env_set" not in st.session_state:
    for k in ("TURSO_DATABASE_URL", "TURSO_DATABASE_TOKEN"):
        if k not in os.environ:
            try:
                if k in st.secrets:
                    os.environ[k] = st.secrets[k]
            except Exception:
                pass
    st.session_state.turso_env_set = True

if "db_initialized" not in st.session_state:
    init_db()
    try:
        migrate_all_old_dbs()
    except Exception:
        pass
    st.session_state.db_initialized = True
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False
st.set_page_config(page_title="Cheka Clips Hub", page_icon="🎬", layout="centered", initial_sidebar_state="expanded")

if st.query_params.get("admin") == "1":
    st.session_state.is_admin = True

if "ch" in st.query_params:
    st.session_state.channel = st.query_params["ch"]
    st.query_params.clear()
    if st.session_state.is_admin:
        st.query_params.admin = "1"

if st.session_state.get("_force_landing", False):
    st.session_state._force_landing = False
    st.session_state.channel = None

for k in ("channel","clips","video_info","current_analysis_id","analyses_cache","view_mode"):
    if k not in st.session_state: st.session_state[k] = None
if "analyses_needs_refresh" not in st.session_state:
    st.session_state.analyses_needs_refresh = True

def fmt_dur(s):
    m, s = divmod(s, 60); h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
def fmt_cdur(s):
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"
def sc_pct(c): return f"{int(c*100)}%"
def badge_pct(c):
    bg = "#16A34A" if c>=0.9 else "#D97706" if c>=0.75 else "#DC2626"
    return f'<span style="background:{bg};color:#fff;padding:0.04rem 0.4rem;font-weight:700;font-size:0.65rem">{sc_pct(c)}</span>'
def _ts_to_sec(ts):
    parts = ts.strip().split(":"); parts = [int(p) for p in parts]
    if len(parts) == 3: return parts[0]*3600 + parts[1]*60 + parts[2]
    if len(parts) == 2: return parts[0]*60 + parts[1]
    return parts[0] if parts else 0

ACCENTS = {"antauro_tv": "#65A30D", "deepskill": "#2563EB", "general": "#A855F7"}

_admin_user = os.environ.get("ADMIN_USERNAME", "")
_admin_pass = os.environ.get("ADMIN_PASSWORD", "")
if not _admin_user or not _admin_pass:
    try:
        if "ADMIN_USERNAME" in st.secrets: _admin_user = st.secrets["ADMIN_USERNAME"]
        if "ADMIN_PASSWORD" in st.secrets: _admin_pass = st.secrets["ADMIN_PASSWORD"]
    except: pass

channel_cfg = get_channel(st.session_state.channel) if st.session_state.channel else None

if st.session_state.channel == "admin_login":
    st.html("""
<style>
    .chan-header { text-align: center; padding: 2rem 0 0.5rem 0; }
    .chan-header .ch-name { font-size: 1.8rem; font-weight: 800; color: #1A1A1A; letter-spacing: -0.02em; }
    .chan-header .ch-desc { font-size: 0.85rem; color: #737373; margin-top: 0.15rem; }
</style>
<div class="chan-header"><div class="ch-name">Administrador</div><div class="ch-desc">Inicia sesión para acceder al panel</div></div>
""")
    if st.button("← Volver al inicio"):
        st.session_state._force_landing = True; st.rerun()
    if not st.session_state.is_admin:
        if not _admin_user or not _admin_pass:
            st.error("No hay credenciales de administrador configuradas en secrets.toml")
        else:
            with st.form("login_form", clear_on_submit=False):
                au = st.text_input("Usuario", placeholder="admin", label_visibility="collapsed")
                ap = st.text_input("Contraseña", type="password", placeholder="••••••", label_visibility="collapsed")
                if st.form_submit_button("Ingresar", type="primary", use_container_width=True):
                    if au == _admin_user and ap == _admin_pass:
                        st.session_state.is_admin = True
                        st.query_params.admin = "1"; st.rerun()
                    else:
                        st.error("Credenciales incorrectas")
    else:
        st.session_state.channel = None; st.rerun()
    st.stop()

if channel_cfg is None:
    if st.session_state.is_admin:
        admin_channels = [ch for ch in list_channels() if ch["id"] != "general"]
        st.html("""
<div style="display:flex;align-items:center;justify-content:center;gap:0.5rem;padding:0.6rem 0;margin-bottom:1.5rem;border-bottom:1px solid #e5e7eb">
    <span style="background:#16A34A;color:#fff;font-size:0.6rem;font-weight:700;padding:0.1rem 0.45rem;border-radius:3px;letter-spacing:0.04em">ADMIN</span>
    <span style="font-size:0.82rem;color:#6B7280">Has iniciado sesión como administrador</span>
</div>
<style>
    .admin-ch-link { text-decoration: none !important; display: block; width: 100%; flex: 1; }
    .admin-ch-card { background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 8px; padding: 1rem 1rem; transition: all 0.2s ease; cursor: pointer; border-left: 4px solid transparent; min-height: 90px; display: flex; flex-direction: column; justify-content: center; }
    .admin-ch-link:hover .admin-ch-card { background: #F5F5F5; border-color: var(--accent); border-left-color: var(--accent); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
    .admin-ch-card .ct { font-weight: 700; font-size: 1rem; color: #1A1A1A; margin-bottom: 0.2rem; transition: color 0.2s ease; }
    .admin-ch-link:hover .admin-ch-card .ct { color: var(--accent); }
    .admin-ch-card .cd { font-size: 0.78rem; color: #737373; line-height: 1.4; }
</style>
<div style="display:flex;gap:0.65rem;width:100%">
""")
        for ch in admin_channels:
            accent = ACCENTS.get(ch["id"], "#65A30D")
            st.html(f'''
<a href="?ch={ch["id"]}&admin=1" class="admin-ch-link" target="_self" style="flex:1;--accent:{accent}">
    <div class="admin-ch-card">
        <div class="ct">{ch["name"]}</div>
        <div class="cd">{ch["description"]}</div>
    </div>
</a>
''')
        st.html("""
</div>
<div style="text-align:center;padding:1.5rem 0;color:#A3A3A3;font-size:0.7rem">
    <strong>Cheka Clips Hub</strong>
</div>
""")
        _, bcol, _ = st.columns([1, 2, 1])
        with bcol:
            if st.button("Cerrar sesión de administrador", key="landing_logout", type="secondary", use_container_width=True):
                st.session_state.is_admin = False
                st.query_params.clear()
                st.rerun()
    else:
        ch_cards = (
            f'<a href="?ch=admin_login" class="ch-link" target="_self">'
            f'<div class="ch-card" style="--accent:#1A1A1A">'
            f'<div class="ct">Administrador</div>'
            f'<div class="cd">Accede al panel de administración</div>'
            f'</div></a>'
        )
        gen = get_channel("general")
        ch_cards += (
            f'<a href="?ch=general" class="ch-link" target="_self">'
            f'<div class="ch-card" style="--accent:{ACCENTS["general"]}">'
            f'<div class="ct">{gen["name"]}</div>'
            f'<div class="cd">{gen["description"]}</div>'
            f'</div></a>'
        )
        st.html(f"""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
            * {{ font-family: 'Inter', sans-serif; }}
            header[data-testid="stHeader"] {{ background: transparent !important; }}
            [data-testid="stToolbar"] {{ display: none !important; }}
            [data-testid="stAppDeployButton"], .stAppDeployButton, button[title="Deploy this app"], button[title="View app source"] {{ display: none !important; }}
            .block-container {{ padding: 0 !important; max-width: 560px !important; width: 100%; }}
            .stApp > .main {{ padding: 0 !important; }}
            #landing {{ display: flex; flex-direction: column; align-items: center; justify-content: center; width: 100%; gap: 0.5rem; min-height: 80vh; }}
            .top-area {{ text-align: center; }}
            .logo {{ font-size: 2.2rem; font-weight: 800; color: #1A1A1A; letter-spacing: -0.02em; }}
            .logo .accent {{ color: #65A30D; }}
            .sub {{ font-size: 0.85rem; color: #737373; margin-top: 0.15rem; }}
            .ch-link {{ text-decoration: none !important; display: block; width: 100%; }}
            .ch-card {{ background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 8px; padding: 1rem 1rem; transition: all 0.2s ease; cursor: pointer; border-left: 4px solid transparent; min-height: 90px; display: flex; flex-direction: column; justify-content: center; }}
            .ch-link:hover .ch-card {{ background: #F5F5F5; border-color: var(--accent); border-left-color: var(--accent); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
            .ch-card .ct {{ font-weight: 700; font-size: 1rem; color: #1A1A1A; margin-bottom: 0.2rem; transition: color 0.2s ease; }}
            .ch-link:hover .ch-card .ct {{ color: var(--accent); }}
            .ch-card .cd {{ font-size: 0.78rem; color: #737373; line-height: 1.4; }}
            .foot-note {{ text-align: center; padding: 1.5rem 0; color: #A3A3A3; font-size: 0.7rem; }}
        </style>
        <div id="landing">
            <div class="top-area">
                <div class="logo">Cheka<span class="accent">_</span>Clips</div>
                <div class="sub">Selecciona un canal</div>
            </div>
            {ch_cards}
            <div class="foot-note"><strong>Cheka Clips Hub</strong></div>
        </div>
        """)
    st.stop()

ACCENT = ACCENTS.get(st.session_state.channel, "#65A30D")

st.html(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    * {{ font-family: 'Inter', sans-serif; }}
    header[data-testid="stHeader"] {{ background: transparent !important; }}
    [data-testid="stToolbar"] {{ display: none !important; }}
    .stAppDeployButton, button[title="Deploy this app"], button[title="View app source"] {{ display: none !important; }}
    .block-container {{ padding-top: 0.75rem !important; padding-bottom: 1.5rem !important; max-width: 1200px !important; }}
    .chan-header {{ text-align: center; padding: 1rem 0 0.5rem 0; }}
    .chan-header .ch-name {{ font-size: 1.8rem; font-weight: 800; color: {ACCENT}; letter-spacing: -0.02em; }}
    .chan-header .ch-desc {{ font-size: 0.85rem; color: #737373; margin-top: 0.15rem; }}
    .top-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem; }}
    .card {{ background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 8px; padding: 0.85rem 1rem; margin-bottom: 0.65rem; }}
    .section-title {{ font-size: 0.95rem; font-weight: 700; color: #1A1A1A; margin: 0.85rem 0 0.5rem 0; }}
    .section-label {{ font-size: 0.62rem; font-weight: 600; color: #A3A3A3; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.3rem; }}
    .steps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.65rem; margin: 0.65rem 0; }}
    .step {{ background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 8px; padding: 0.75rem; text-align: center; }}
    .step .num {{ display: inline-block; background: #F5F5F5; color: #737373; width: 24px; height: 24px; line-height: 24px; font-weight: 700; font-size: 0.75rem; margin-bottom: 0.3rem; }}
    .step .lbl {{ font-size: 0.8rem; font-weight: 600; color: #1A1A1A; margin-bottom: 0.1rem; }}
    .step .subl {{ font-size: 0.72rem; color: #737373; }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.65rem; margin-bottom: 0.65rem; }}
    .metric {{ background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 6px; padding: 0.55rem; text-align: center; }}
    .metric .val {{ font-size: 1.1rem; font-weight: 700; color: #1A1A1A; }}
    .metric .lbl {{ font-size: 0.6rem; font-weight: 500; color: #A3A3A3; text-transform: uppercase; }}
    .video-info {{ display: flex; align-items: center; gap: 0.65rem; }}
    .video-info img {{ border-radius: 4px; border: 1px solid #D4D4D4; width: 120px; }}
    .video-info .vd .vt {{ font-weight: 600; color: #1A1A1A; font-size: 0.85rem; }}
    .video-info .vd .vm {{ font-size: 0.72rem; color: #737373; }}
    hr {{ border-color: #D4D4D4; margin: 0.65rem 0; }}
    .footer {{ text-align: center; padding: 1.5rem 0 0.5rem 0; color: #A3A3A3; font-size: 0.68rem; }}
    .sidebar-title {{ font-size: 0.85rem; font-weight: 700; color: #1A1A1A; margin-bottom: 0.65rem; padding-bottom: 0.35rem; border-bottom: 2px solid {ACCENT}; }}
    .sidebar-card {{ background: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 6px; padding: 0.6rem 0.8rem; margin-bottom: 0.75rem; }}
    .sidebar-card .sc-title {{ font-size: 0.75rem; font-weight: 600; color: #1A1A1A; line-height: 1.3; margin-bottom: 0.1rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    .sidebar-card .sc-meta {{ font-size: 0.62rem; color: #A3A3A3; }}
    .clip-header-bar {{ display: flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.65rem; border: 1px solid #D4D4D4; border-bottom: none; border-radius: 6px 6px 0 0; background: #FFFFFF; }}
    .clip-num {{ background: #F5F5F5; color: #1A1A1A; padding: 0.04rem 0.3rem; font-weight: 700; font-size: 0.65rem; flex-shrink: 0; }}
    .clip-time {{ background: #F5F5F5; color: #737373; padding: 0.04rem 0.3rem; font-weight: 600; font-size: 0.58rem; font-family: 'Courier New'; flex-shrink: 0; }}
    .clip-title-text {{ flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; color: #1A1A1A; font-size: 0.78rem; }}
    section[data-testid="stAppViewContainer"] .clip-wrapper {{ margin-bottom: 0.4rem; }}
    section[data-testid="stAppViewContainer"] .clip-wrapper [data-testid="stExpander"] {{ border: 1px solid #D4D4D4 !important; border-top: none !important; border-radius: 0 0 6px 6px !important; background: #FFFFFF !important; }}
    section[data-testid="stAppViewContainer"] .clip-wrapper [data-testid="stExpander"] > details > summary {{ padding: 0.3rem 0.65rem !important; font-weight: 500 !important; font-size: 0.7rem !important; border-radius: 0 !important; cursor: pointer !important; min-height: 1.5rem !important; color: #A3A3A3 !important; background: #FFFFFF !important; }}
    section[data-testid="stAppViewContainer"] .clip-wrapper [data-testid="stExpander"] > details > div {{ padding: 0.4rem 0.65rem 0.65rem 0.65rem !important; background: #FFFFFF !important; }}
    div[data-testid="column"]:first-child .stButton>button {{ font-size: 0.65rem !important; height: 28px !important; line-height: 1 !important; padding: 0 0.3rem !important; min-width: 0 !important; }}
    div[data-testid="column"]:first-child > div:first-child {{ padding-right: 1rem !important; }}
    .stButton>button[kind="secondary"] {{ font-size: 0.78rem !important; height: 32px !important; padding: 0 0.75rem !important; }}
    @media(max-width:640px) {{ .steps, .metrics {{ grid-template-columns: 1fr; }} .video-info {{ flex-direction: column; }} .video-info img {{ width: 100%; }} }}
</style>
<div hidden></div>
""")

st.html(f'<div class="chan-header"><div class="ch-name">{channel_cfg["name"]}</div><div class="ch-desc">{channel_cfg["description"]}</div></div>')
st.html(f'<div class="top-row"></div>')
if st.button("← Volver al inicio", key="back"):
    st.session_state._force_landing = True
    st.session_state.clips = None; st.session_state.video_info = None
    st.session_state.current_analysis_id = None; st.session_state.analyses_needs_refresh = True; st.rerun()

dk = os.environ.get("DEEPSEEK_API_KEY", "")
if not dk:
    try:
        if "DEEPSEEK_API_KEY" in st.secrets and st.secrets["DEEPSEEK_API_KEY"]: dk = st.secrets["DEEPSEEK_API_KEY"]
    except: pass

if st.session_state.analyses_needs_refresh:
    st.session_state.analyses_cache = get_analyses(channel=st.session_state.channel)
    st.session_state.analyses_needs_refresh = False
analyses = st.session_state.analyses_cache

if st.session_state.is_admin:
    hcol, mcol = st.columns([1.1, 2.4])
    with hcol:
        st.html(f'<div class="sidebar-title">Historial</div>')
        if analyses:
            for a in analyses:
                t = a["video_title"] or "Video"
                st.html(f'<div class="sidebar-card"><div class="sc-title">{t}</div><div class="sc-meta">{a["created_at"][:19].replace("T"," ")} - {a["clip_count"]} clips</div></div>')
                c1, c2, c3 = st.columns([1,1,1])
                with c1:
                    if st.button("Ver", key=f"v_{a['id']}", use_container_width=True):
                        an = get_analysis(a["id"])
                        if an: st.session_state.clips = an["clips"]; st.session_state.video_info = {"id": an["video_id"], "title": an["video_title"], "duration": an["video_duration"]}; st.session_state.current_analysis_id = a["id"]; st.session_state.view_mode = "view"; st.rerun()
                with c2:
                    if st.button("Editar", key=f"e_{a['id']}", use_container_width=True):
                        an = get_analysis(a["id"])
                        if an: st.session_state.clips = an["clips"]; st.session_state.video_info = {"id": an["video_id"], "title": an["video_title"], "duration": an["video_duration"]}; st.session_state.current_analysis_id = a["id"]; st.session_state.view_mode = "edit"; st.rerun()
                with c3:
                    if st.button("Eliminar", key=f"d_{a['id']}", use_container_width=True):
                        delete_analysis(a["id"]); st.session_state.analyses_needs_refresh = True
                        if st.session_state.current_analysis_id == a["id"]: st.session_state.current_analysis_id = None; st.session_state.clips = None; st.session_state.video_info = None
                        st.rerun()
        else:
            st.html(f'<p style="font-size:0.72rem;color:#A3A3A3;padding:0.3rem 0">Sin analisis</p>')
else:
    mcol = st.container()

with mcol:
    with st.form("inputs"):
        url = st.text_input("URL del video", placeholder="https://www.youtube.com/watch?v=...", autocomplete="url")
        api_key = st.text_input("DeepSeek API Key", type="password", value=dk, placeholder="sk-...", autocomplete="off")
        submitted = st.form_submit_button("Extraer clips", use_container_width=True)
        if dk:
            st.html(f'<p style="font-size:0.68rem;color:#16A34A;text-align:center;margin-top:0.2rem">API Key desde secrets</p>')

    if submitted:
        if not url: st.error("Pega una URL de YouTube primero.")
        elif not api_key: st.error("Ingresa tu DeepSeek API Key.")
        else:
            st.caption("v3")  # debug version marker
            prog = st.progress(0, text="Iniciando..."); sts = st.empty()
            def on_progress(pct, msg): prog.progress(pct/100, text=msg)
            try:
                em = importlib.import_module(f"engines.{channel_cfg['engine']}")
                importlib.reload(em)
                ep = getattr(em, channel_cfg["entry_point"]); gid = getattr(em, "get_video_id", lambda x: ""); gti = getattr(em, "get_video_title", lambda x: ""); gdu = getattr(em, "get_video_duration", lambda x: 0)
                video_id = gid(url)
                skip_processing = False
                if video_id:
                    existente = get_analysis_by_video_id(st.session_state.channel, video_id)
                    if existente:
                        st.warning(f"⚠️ Este video ya fue cargado el {existente['created_at'][:10]} ({existente['clip_count']} clips). Mostrando resultados guardados.")
                        st.session_state.clips = existente["clips"]
                        st.session_state.video_info = {"id": video_id, "title": existente["video_title"], "duration": 0}
                        st.session_state.current_analysis_id = existente["id"]
                        st.session_state.view_mode = "view"
                        skip_processing = True
                if not skip_processing:
                    virales = get_viral_clips(st.session_state.channel, limit=5) if st.session_state.is_admin else None
                    clips = ep(url, api_key, progress_callback=on_progress, viral_examples=virales)
                    st.session_state.clips = clips; st.session_state.view_mode = "view"
                    st.session_state.video_info = {"id": gid(url), "title": gti(url), "duration": gdu(url)}
                    st.session_state.current_analysis_id = None; prog.progress(1.0, text=f"Listo: {len(clips)} clips")
                    sts.success(f"Completado - {len(clips)} clips.")
            except Exception as e: st.error(f"Error: {e}\n\n{traceback.format_exc()}"); prog.progress(1.0, text="Error"); st.stop()
            if not skip_processing and not clips: st.warning("No se encontraron clips."); st.stop()

    clips = st.session_state.clips; vi = st.session_state.video_info

    if clips and len(clips) > 0:
        st.markdown("---")
        em = importlib.import_module(f"engines.{channel_cfg['engine']}"); t2s = getattr(em, "ts_to_seconds", lambda x: 0)
        vid = (vi or {}).get("id",""); title = (vi or {}).get("title",""); dur = (vi or {}).get("duration",0)
        thu = f"https://img.youtube.com/vi/{vid}/mqdefault.jpg" if vid else ""
        st.html(f'<div class="card"><div class="section-label">Video</div><div class="video-info"><img src="{thu}" alt="" onerror="this.style.display=\'none\'"><div class="vd"><div class="vt">{title or "Video"}</div><div class="vm">{fmt_dur(dur)+" - " if dur else ""}{len(clips)} clips</div></div></div></div>')
        durs = [t2s(c.get("end","00:00:00"))-t2s(c.get("start","00:00:00")) for c in clips]; ad = sum(durs)/len(durs) if durs else 0; asc = sum(c.get("confidence",0) for c in clips)/len(clips) if clips else 0
        st.html(f'<div class="metrics"><div class="metric"><div class="val">{len(clips)}</div><div class="lbl">Clips</div></div><div class="metric"><div class="val">{ad:.0f}s</div><div class="lbl">Duracion</div></div><div class="metric"><div class="val">{sc_pct(asc)}</div><div class="lbl">Score</div></div></div>')
        if st.session_state.is_admin:
            if st.session_state.current_analysis_id is None:
                if st.button("Guardar en historial", use_container_width=True, type="primary"):
                    aid = save_analysis(channel=st.session_state.channel, video_url="", video_id=st.session_state.video_info.get("id",""), video_title=st.session_state.video_info.get("title",""), video_duration=st.session_state.video_info.get("duration",0), clips=st.session_state.clips)
                    st.session_state.current_analysis_id = aid; st.session_state.analyses_needs_refresh = True; st.rerun()
        mode = ""; 
        if st.session_state.current_analysis_id is None: mode = "Vista previa"
        elif st.session_state.view_mode == "edit": mode = "Edicion"
        else: mode = "Lectura"
        if mode: st.html(f'<p style="font-size:0.68rem;color:#A3A3A3;margin-bottom:0.2rem">{mode}</p>')
        st.html('<div class="section-title">Mejores momentos</div>')
        viral_keys_set: set[str] = set()
        if st.session_state.is_admin:
            viral_keys_set = {f"{vr['video_id']}:{int(vr['clip_start'])}:{int(vr['clip_end'])}" for vr in get_viral_clips(st.session_state.channel, limit=500)}
            viral_count = sum(1 for c in clips if f"{vid}:{_ts_to_sec(c.get('start',''))}:{_ts_to_sec(c.get('end',''))}" in viral_keys_set)
            if viral_count:
                st.html(f'<p style="font-size:0.72rem;color:#16A34A;margin:0 0 0.5rem 0">✅ {viral_count} clip{"s" if viral_count!=1 else ""} marcado{"s" if viral_count!=1 else ""} como viral</p>')
        gcv = getattr(em, "generar_copy_viral", None)
        for i, clip in enumerate(clips):
            start = clip.get("start","00:00:00"); end = clip.get("end","00:00:00"); tt = clip.get("title","Sin titulo"); hook = clip.get("hook",""); desc = clip.get("descripcion",""); conf = clip.get("confidence",0); why = clip.get("why",""); tc = clip.get("tiktok_copy","")
            dsec = t2s(end)-t2s(start); dst = fmt_cdur(dsec)
            tp = gcv(tt, hook, desc) if gcv else (tc or f"{tt}\n\n\"{hook}\"\n\n")
            vk = f"{vid}:{_ts_to_sec(start)}:{_ts_to_sec(end)}"
            is_viral = vk in viral_keys_set
            viral_badge = ""
            if st.session_state.is_admin:
                viral_badge = f'<span style="background:#16A34A;color:#fff;padding:0.04rem 0.4rem;font-weight:700;font-size:0.65rem">✅ Viral</span>' if is_viral else ""
            st.html('<div class="clip-wrapper">')
            st.html(f'<div class="clip-header-bar"><span class="clip-num">#{i+1}</span><span class="clip-title-text">{tt}</span><span class="clip-time">{start}-{end} | {dst}</span>{badge_pct(conf)}{viral_badge}</div>')
            vcol, ecol = st.columns([0.15, 0.85])
            with vcol:
                if st.session_state.is_admin:
                    btn_label = "✅ Viral" if is_viral else "⭐ Marcar"
                    key_suffix = f"uv_{vid}_{i}" if is_viral else f"v_{vid}_{i}"
                    btn_type = "primary" if is_viral else "secondary"
                    if st.button(btn_label, key=key_suffix, type=btn_type, help="Desmarcar como viral" if is_viral else "Marcar como viral", use_container_width=True):
                        if is_viral:
                            delete_viral_clip(st.session_state.channel, vid, _ts_to_sec(start), _ts_to_sec(end))
                            viral_keys_set.discard(vk)
                        else:
                            save_viral_clip(st.session_state.channel, vid, title, _ts_to_sec(start), _ts_to_sec(end), tt, hook, desc, clip.get("transcripcion",""), conf)
                            viral_keys_set.add(vk)
                        st.rerun()
            with ecol:
                with st.expander("+"):
                    if st.session_state.view_mode == "edit":
                        if st.button("Eliminar", key=f"cd_{i}", type="secondary"): upd = list(st.session_state.clips); del upd[i]; st.session_state.clips = upd; st.session_state.analyses_needs_refresh = True; st.rerun()
                    if hook: st.html(f'<p style="font-style:italic;color:#737373;font-size:0.82rem">"{hook}"</p>')
                    if desc: st.html(f'<p style="color:#737373;font-size:0.8rem">{desc}</p>')
                    if why: st.html(f'<p style="color:#2563EB;font-size:0.75rem;font-weight:500">{why}</p>')
                    if tc: st.html(f'<p style="color:#D97706;font-size:0.75rem;font-weight:500">{tc}</p>')
                    st.html('<p style="font-size:0.62rem;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:0.05em;margin-top:0.65rem;margin-bottom:0.2rem">Copy</p>')
                    st.code(tp, language="text", line_numbers=False)
                    tr = clip.get("transcripcion","")
                    if tr: st.html('<p style="font-size:0.62rem;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:0.05em;margin-top:0.4rem;margin-bottom:0.15rem">Transcripcion</p>'); st.write(tr)
            st.html("</div>")

    if clips is None:
        st.html(f'<div class="section-title">Como funciona?</div><div class="steps"><div class="step"><div class="num">1</div><div class="lbl">Pega la URL</div><div class="subl">Video de YouTube</div></div><div class="step"><div class="num">2</div><div class="lbl">DeepSeek analiza</div><div class="subl">IA extrae clips</div></div><div class="step"><div class="num">3</div><div class="lbl">Obtén los clips</div><div class="subl">Titulos y copy listos</div></div></div>')
        with st.expander("Como obtener tu API Key de DeepSeek?"): st.markdown("1. [platform.deepseek.com](https://platform.deepseek.com)\n2. Registrate\n3. API Keys -> Create\n4. Copia la llave `sk-...`")

    st.html(f'<div class="footer"><strong>Cheka Clips Hub</strong> | {channel_cfg["emoji"]} {channel_cfg["name"]}</div>')
