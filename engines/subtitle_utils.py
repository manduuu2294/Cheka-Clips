import base64
import os
import tempfile
from pathlib import Path

import yt_dlp


BOT_CHECK_HINT = (
    "YouTube está pidiendo verificación anti-bot. Configura cookies de YouTube "
    "en Railway usando YOUTUBE_COOKIES_BASE64 o YOUTUBE_COOKIES_CONTENT."
)


def _is_bot_check_error(error: Exception) -> bool:
    text = str(error).lower()
    return "not a bot" in text or "sign in to confirm" in text


def _cookiefile_from_env(workdir: Path | None = None) -> str | None:
    path = os.environ.get("YOUTUBE_COOKIES_PATH") or os.environ.get("YT_DLP_COOKIES_PATH")
    if path and Path(path).exists():
        return path

    raw = ""
    encoded = os.environ.get("YOUTUBE_COOKIES_BASE64", "").strip()
    if encoded:
        try:
            raw = base64.b64decode(encoded).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("YOUTUBE_COOKIES_BASE64 no es un base64 válido.") from exc
    else:
        raw = (
            os.environ.get("YOUTUBE_COOKIES_CONTENT", "")
            or os.environ.get("YOUTUBE_COOKIES", "")
        )
        raw = raw.replace("\\n", "\n")

    if not raw.strip():
        return None

    target_dir = workdir if workdir is not None else Path(tempfile.gettempdir())
    target = target_dir / "youtube_cookies.txt"
    target.write_text(raw, encoding="utf-8")
    return str(target)


def ydl_base_opts(workdir: Path | None = None, **overrides) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "cachedir": False,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        },
    }
    cookiefile = _cookiefile_from_env(workdir)
    if cookiefile:
        opts["cookiefile"] = cookiefile
    opts.update(overrides)
    return opts


def _lang_matches(key: str, wanted: str) -> bool:
    k = key.lower()
    w = wanted.lower()
    return k == w or k.startswith(f"{w}-") or k.startswith(f"{w}_")


def _pick_language(available: dict, requested: str) -> str | None:
    if not available:
        return None

    preferred = []
    if requested:
        preferred.append(requested)
        base = requested.split("-")[0].split("_")[0]
        if base and base != requested:
            preferred.append(base)
    preferred.extend(["es", "en"])

    for wanted in preferred:
        for key in available:
            if _lang_matches(key, wanted):
                return key

    return next(iter(available.keys()), None)


def download_subtitles_vtt(url: str, lang: str, workdir: Path) -> Path:
    out_tpl = str(workdir / "transcripcion.%(ext)s")
    base_opts = ydl_base_opts(workdir, skip_download=True)

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        if _is_bot_check_error(exc):
            raise RuntimeError(BOT_CHECK_HINT) from exc
        raise RuntimeError(f"No se pudo leer la información del video: {exc}") from exc

    sources = [
        ("manuales", "writesub", info.get("subtitles") or {}),
        ("automáticos", "writeautomaticsub", info.get("automatic_captions") or {}),
    ]

    for label, option_name, available in sources:
        selected_lang = _pick_language(available, lang)
        if not selected_lang:
            continue

        ydl_opts = {
            **base_opts,
            option_name: True,
            "subtitleslangs": [selected_lang],
            "subtitlesformat": "vtt/best",
            "outtmpl": out_tpl,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            if _is_bot_check_error(exc):
                raise RuntimeError(BOT_CHECK_HINT) from exc
            continue

        exact_path = workdir / f"transcripcion.{selected_lang}.vtt"
        if exact_path.exists():
            return exact_path

        candidates = sorted(workdir.glob("transcripcion*.vtt"))
        if candidates:
            return candidates[0]

    available_codes = []
    for _, _, available in sources:
        available_codes.extend(available.keys())
    codes = ", ".join(sorted(set(available_codes))[:20])
    detail = f" Disponibles: {codes}" if codes else " El video no expone subtítulos descargables."
    raise RuntimeError(f"No se generaron subtítulos para '{lang}'.{detail}")
