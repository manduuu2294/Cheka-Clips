import asyncio, sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json, importlib, traceback, streamlit as st
import os  # debug
from channels import get_channel, list_channels
from database import init_db, save_analysis, get_analyses, get_analysis, update_analysis, delete_analysis, migrate_all_old_dbs

if "db_initialized" not in st.session_state:
    init_db()
    migrate_all_old_dbs()
    st.session_state.db_initialized = True
st.set_page_config(page_title="Cheka Clips Hub", page_icon="🎬", layout="centered", initial_sidebar_state="expanded")

if "ch" in st.query_params:
    st.session_state.channel = st.query_params["ch"]
    st.query_params.clear()

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

ACCENTS = {"antauro_tv": "#65A30D", "deepskill": "#2563EB"}

channel_cfg = get_channel(st.session_state.channel) if st.session_state.channel else None

if channel_cfg is None:
    ch_cards = ""
    for ch in list_channels():
        accent = ACCENTS.get(ch["id"], "#65A30D")
        ch_cards += (
            f'<a href="?ch={ch["id"]}" class="ch-link" target="_self">'
            f'<div class="ch-card" style="--accent:{accent}">'
            f'<div class="ct">{ch["name"]}</div>'
            f'<div class="cd">{ch["description"]}</div>'
            f'</div></a>'
        )
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        * {{ font-family: 'Inter', sans-serif; }}
        header[data-testid="stHeader"] {{ background: transparent !important; }}
        [data-testid="stToolbar"] {{ display: none !important; }}
        .stAppDeployButton, button[title="Deploy this app"], button[title="View app source"] {{ display: none !important; }}
        .block-container {{ padding: 0 !important; max-width: 560px !important; width: 100%; }}
        .stApp > .main {{ padding: 0 !important; }}
        #landing {{ display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; width: 100%; gap: 0.5rem; }}
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
        .add-box {{ display: flex; align-items: center; justify-content: center; gap: 0.4rem; padding: 0.65rem; border: 2px dashed #D4D4D4; border-radius: 8px; margin-top: 0.75rem; width: 100%; }}
        .add-box span {{ font-size: 0.78rem; color: #A3A3A3; }}
        .add-box code {{ font-size: 0.72rem; background: #FFFFFF; padding: 0.1rem 0.3rem; border-radius: 3px; border: 1px solid #E5E5E5; }}
        .foot-note {{ text-align: center; padding: 1.5rem 0; color: #A3A3A3; font-size: 0.7rem; }}
    </style>
    <div id="landing">
        <div class="top-area">
            <div class="logo">Cheka<span class="accent">_</span>Clips</div>
            <div class="sub">Selecciona un canal</div>
        </div>
        {ch_cards}
        <div class="add-box"><span>+</span><span>Agrega mas canales editando <code>channels.py</code></span></div>
        <div class="foot-note"><strong>Cheka Clips Hub</strong></div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

ACCENT = ACCENTS.get(st.session_state.channel, "#65A30D")

st.markdown(f"""
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
""", unsafe_allow_html=True)

st.markdown(f'<div class="chan-header"><div class="ch-name">{channel_cfg["name"]}</div><div class="ch-desc">{channel_cfg["description"]}</div></div>', unsafe_allow_html=True)
st.markdown(f'<div class="top-row"></div>', unsafe_allow_html=True)
if st.button("← Volver al inicio", key="back"):
    st.session_state.channel = None; st.session_state.clips = None; st.session_state.video_info = None
    st.session_state.current_analysis_id = None; st.session_state.analyses_needs_refresh = True; st.rerun()

dk = ""
try:
    if "DEEPSEEK_API_KEY" in st.secrets and st.secrets["DEEPSEEK_API_KEY"]: dk = st.secrets["DEEPSEEK_API_KEY"]
except: pass

if st.session_state.analyses_needs_refresh:
    st.session_state.analyses_cache = get_analyses(channel=st.session_state.channel)
    st.session_state.analyses_needs_refresh = False
analyses = st.session_state.analyses_cache

hcol, mcol = st.columns([1.1, 2.4])
with hcol:
    st.markdown(f'<div class="sidebar-title">Historial</div>', unsafe_allow_html=True)
    if analyses:
        for a in analyses:
            t = a["video_title"] or "Video"
            st.markdown(f'<div class="sidebar-card"><div class="sc-title">{t}</div><div class="sc-meta">{a["created_at"][:19].replace("T"," ")} - {a["clip_count"]} clips</div></div>', unsafe_allow_html=True)
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
        st.markdown(f'<p style="font-size:0.72rem;color:#A3A3A3;padding:0.3rem 0">Sin analisis</p>', unsafe_allow_html=True)

with mcol:
    with st.form("inputs"):
        url = st.text_input("URL del video", placeholder="https://www.youtube.com/watch?v=...", autocomplete="url")
        api_key = st.text_input("DeepSeek API Key", type="password", value=dk, placeholder="sk-...", autocomplete="off")
        submitted = st.form_submit_button("Extraer clips", use_container_width=True)
        if dk:
            st.markdown(f'<p style="font-size:0.68rem;color:#16A34A;text-align:center;margin-top:0.2rem">API Key desde secrets</p>', unsafe_allow_html=True)

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
                clips = ep(url, api_key, progress_callback=on_progress)
                st.session_state.clips = clips; st.session_state.view_mode = "view"
                st.session_state.video_info = {"id": gid(url), "title": gti(url), "duration": gdu(url)}
                st.session_state.current_analysis_id = None; prog.progress(1.0, text=f"Listo: {len(clips)} clips")
                sts.success(f"Completado - {len(clips)} clips.")
            except Exception as e: st.error(f"Error: {e}\n\n{traceback.format_exc()}"); prog.progress(1.0, text="Error"); st.stop()
            if not clips: st.warning("No se encontraron clips."); st.stop()

    clips = st.session_state.clips; vi = st.session_state.video_info

    if clips and len(clips) > 0:
        st.markdown("---")
        em = importlib.import_module(f"engines.{channel_cfg['engine']}"); t2s = getattr(em, "ts_to_seconds", lambda x: 0)
        vid = (vi or {}).get("id",""); title = (vi or {}).get("title",""); dur = (vi or {}).get("duration",0)
        thu = f"https://img.youtube.com/vi/{vid}/mqdefault.jpg" if vid else ""
        st.markdown(f'<div class="card"><div class="section-label">Video</div><div class="video-info"><img src="{thu}" alt="" onerror="this.style.display=\'none\'"><div class="vd"><div class="vt">{title or "Video"}</div><div class="vm">{fmt_dur(dur)+" - " if dur else ""}{len(clips)} clips</div></div></div></div>', unsafe_allow_html=True)
        durs = [t2s(c.get("end","00:00:00"))-t2s(c.get("start","00:00:00")) for c in clips]; ad = sum(durs)/len(durs) if durs else 0; asc = sum(c.get("confidence",0) for c in clips)/len(clips) if clips else 0
        st.markdown(f'<div class="metrics"><div class="metric"><div class="val">{len(clips)}</div><div class="lbl">Clips</div></div><div class="metric"><div class="val">{ad:.0f}s</div><div class="lbl">Duracion</div></div><div class="metric"><div class="val">{sc_pct(asc)}</div><div class="lbl">Score</div></div></div>', unsafe_allow_html=True)
        if st.session_state.current_analysis_id is None:
            if st.button("Guardar en historial", use_container_width=True, type="primary"):
                aid = save_analysis(channel=st.session_state.channel, video_url="", video_id=st.session_state.video_info.get("id",""), video_title=st.session_state.video_info.get("title",""), video_duration=st.session_state.video_info.get("duration",0), clips=st.session_state.clips)
                st.session_state.current_analysis_id = aid; st.session_state.analyses_needs_refresh = True; st.rerun()
        mode = ""; 
        if st.session_state.current_analysis_id is None: mode = "Vista previa"
        elif st.session_state.view_mode == "edit": mode = "Edicion"
        else: mode = "Lectura"
        if mode: st.markdown(f'<p style="font-size:0.68rem;color:#A3A3A3;margin-bottom:0.2rem">{mode}</p>', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Mejores momentos</div>', unsafe_allow_html=True)
        gcv = getattr(em, "generar_copy_viral", None)
        for i, clip in enumerate(clips):
            start = clip.get("start","00:00:00"); end = clip.get("end","00:00:00"); tt = clip.get("title","Sin titulo"); hook = clip.get("hook",""); desc = clip.get("descripcion",""); conf = clip.get("confidence",0); why = clip.get("why",""); tc = clip.get("tiktok_copy","")
            dsec = t2s(end)-t2s(start); dst = fmt_cdur(dsec)
            tp = gcv(tt, hook, desc) if gcv else (tc or f"{tt}\n\n\"{hook}\"\n\n")
            st.markdown('<div class="clip-wrapper">', unsafe_allow_html=True)
            st.markdown(f'<div class="clip-header-bar"><span class="clip-num">#{i+1}</span><span class="clip-title-text">{tt}</span><span class="clip-time">{start}-{end} | {dst}</span>{badge_pct(conf)}</div>', unsafe_allow_html=True)
            with st.expander("+"):
                if st.session_state.view_mode == "edit":
                    if st.button("Eliminar", key=f"cd_{i}", type="secondary"): upd = list(st.session_state.clips); del upd[i]; st.session_state.clips = upd; st.session_state.analyses_needs_refresh = True; st.rerun()
                if hook: st.markdown(f'<p style="font-style:italic;color:#737373;font-size:0.82rem">"{hook}"</p>', unsafe_allow_html=True)
                if desc: st.markdown(f'<p style="color:#737373;font-size:0.8rem">{desc}</p>', unsafe_allow_html=True)
                if why: st.markdown(f'<p style="color:#2563EB;font-size:0.75rem;font-weight:500">{why}</p>', unsafe_allow_html=True)
                if tc: st.markdown(f'<p style="color:#D97706;font-size:0.75rem;font-weight:500">{tc}</p>', unsafe_allow_html=True)
                st.markdown('<p style="font-size:0.62rem;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:0.05em;margin-top:0.65rem;margin-bottom:0.2rem">Copy</p>', unsafe_allow_html=True)
                st.code(tp, language="text", line_numbers=False)
                tr = clip.get("transcripcion","")
                if tr: st.markdown('<p style="font-size:0.62rem;font-weight:600;color:#9CA3AF;text-transform:uppercase;letter-spacing:0.05em;margin-top:0.4rem;margin-bottom:0.15rem">Transcripcion</p>', unsafe_allow_html=True); st.write(tr)
            st.markdown("</div>", unsafe_allow_html=True)

    if clips is None:
        st.markdown(f'<div class="section-title">Como funciona?</div><div class="steps"><div class="step"><div class="num">1</div><div class="lbl">Pega la URL</div><div class="subl">Video de YouTube</div></div><div class="step"><div class="num">2</div><div class="lbl">DeepSeek analiza</div><div class="subl">IA extrae clips</div></div><div class="step"><div class="num">3</div><div class="lbl">Obtén los clips</div><div class="subl">Titulos y copy listos</div></div></div>', unsafe_allow_html=True)
        with st.expander("Como obtener tu API Key de DeepSeek?"): st.markdown("1. [platform.deepseek.com](https://platform.deepseek.com)\n2. Registrate\n3. API Keys -> Create\n4. Copia la llave `sk-...`")

    st.markdown(f'<div class="footer"><strong>Cheka Clips Hub</strong> | {channel_cfg["emoji"]} {channel_cfg["name"]}</div>', unsafe_allow_html=True)
