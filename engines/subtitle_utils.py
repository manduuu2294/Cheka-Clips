import base64
import gzip
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp


COOKIE_ENV_NAMES = (
    "YOUTUBE_COOKIES_GZIP_BASE64",
    "YOUTUBE_COOKIES_BASE64",
    "YOUTUBE_COOKIES_CONTENT",
    "YOUTUBE_COOKIES",
    "YOUTUBE_COOKIES_PATH",
    "YT_DLP_COOKIES_PATH",
)

BOT_CHECK_HINT = (
    "YouTube está pidiendo verificación anti-bot y no hay cookies configuradas. "
    "Configura YOUTUBE_COOKIES_GZIP_BASE64 en Railway."
)

BOT_CHECK_WITH_COOKIES_HINT = (
    "YouTube está pidiendo verificación anti-bot aunque hay cookies configuradas. "
    "Regenera YOUTUBE_COOKIES_GZIP_BASE64 con cookies recientes de una sesión de YouTube."
)


def _is_bot_check_error(error: Exception) -> bool:
    text = str(error).lower()
    return "not a bot" in text or "sign in to confirm" in text


def _clean_env_value(value: str) -> str:
    value = value.strip().strip('"').strip("'").strip()
    for separator in ("=", " "):
        prefix = f"YOUTUBE_COOKIES_GZIP_BASE64{separator}"
        if value.startswith(prefix):
            value = value[len(prefix):].strip().strip('"').strip("'").strip()
    if value.startswith("export YOUTUBE_COOKIES_GZIP_BASE64="):
        value = value.split("=", 1)[1].strip().strip('"').strip("'").strip()
    return "".join(value.split())


def _env(name: str) -> str:
    return _clean_env_value(os.environ.get(name, ""))


def _has_cookie_config() -> bool:
    return any(_env(name) for name in COOKIE_ENV_NAMES)


def _bot_check_hint() -> str:
    return BOT_CHECK_WITH_COOKIES_HINT if _has_cookie_config() else BOT_CHECK_HINT


def youtube_cookie_env_status() -> dict:
    value = _env("YOUTUBE_COOKIES_GZIP_BASE64")
    status = {
        "present": bool(value),
        "length": len(value),
        "prefix": value[:5] if value else "",
        "gzip_base64_valid": False,
        "decoded_lines": 0,
        "looks_like_netscape": False,
        "error": "",
    }
    if not value:
        return status
    try:
        raw = gzip.decompress(base64.b64decode(value, validate=True)).decode("utf-8", errors="ignore")
        lines = [line for line in raw.splitlines() if line.strip()]
        status["gzip_base64_valid"] = True
        status["decoded_lines"] = len(lines)
        status["looks_like_netscape"] = any("Netscape HTTP Cookie File" in line for line in lines[:5])
    except Exception as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status

def _get_video_id(url: str) -> str:
    patterns = [
        r"(?:v=)([0-9A-Za-z_-]{11})",
        r"(?:youtu\.be/)([0-9A-Za-z_-]{11})",
        r"(?:embed/)([0-9A-Za-z_-]{11})",
        r"(?:shorts/)([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    match = re.search(r"([0-9A-Za-z_-]{11})", url)
    return match.group(1) if match else ""


def _cookiefile_from_env(workdir: Path | None = None) -> str | None:
    path = os.environ.get("YOUTUBE_COOKIES_PATH") or os.environ.get("YT_DLP_COOKIES_PATH")
    if path and Path(path).exists():
        return path

    raw = ""
    gzip_encoded = _env("YOUTUBE_COOKIES_GZIP_BASE64")
    encoded = _env("YOUTUBE_COOKIES_BASE64")
    if gzip_encoded:
        try:
            raw = gzip.decompress(base64.b64decode(gzip_encoded)).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("YOUTUBE_COOKIES_GZIP_BASE64 no es un gzip+base64 válido.") from exc
    elif encoded:
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


def _cookie_header_from_file(cookiefile: str | None) -> str:
    if not cookiefile:
        return ""

    pairs = []
    try:
        lines = Path(cookiefile).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            continue

        domain, _, _, _, _, name, value = parts[:7]
        if "youtube.com" not in domain and "google.com" not in domain:
            continue
        if not name or value is None:
            continue
        pairs.append(f"{name}={value}")

    return "; ".join(pairs)


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


def get_video_metadata(url: str) -> dict:
    """Return the YouTube fields needed by the UI with a single extraction."""
    with yt_dlp.YoutubeDL(ydl_base_opts(socket_timeout=15, retries=1)) as ydl:
        info = ydl.extract_info(url, download=False)

    published_at = ""
    upload_date = str(info.get("upload_date") or "")
    if len(upload_date) == 8 and upload_date.isdigit():
        published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    elif info.get("timestamp"):
        published_at = datetime.fromtimestamp(
            info["timestamp"], tz=timezone.utc
        ).date().isoformat()

    return {
        "id": str(info.get("id") or _get_video_id(url)),
        "title": str(info.get("title") or ""),
        "duration": int(info.get("duration") or 0),
        "published_at": published_at,
    }


def timedtext_headers(workdir: Path | None = None) -> dict:
    opts = ydl_base_opts(workdir)
    headers = dict(opts.get("http_headers", {}))
    cookie_header = _cookie_header_from_file(opts.get("cookiefile"))
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


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


def _candidate_langs(lang: str) -> list[str]:
    result = []
    for item in [lang, "es", "es-419", "es-US", "en", "en-US"]:
        if item and item not in result:
            result.append(item)
    return result


def _download_timedtext_vtt(url: str, lang: str, workdir: Path) -> Path | None:
    video_id = _get_video_id(url)
    if not video_id:
        return None

    headers = timedtext_headers(workdir)
    for code in _candidate_langs(lang):
        for kind in ("", "asr"):
            params = {
                "v": video_id,
                "lang": code,
                "fmt": "vtt",
            }
            if kind:
                params["kind"] = kind
            timedtext_url = "https://www.youtube.com/api/timedtext?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(timedtext_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
            except Exception:
                continue

            if "WEBVTT" not in body or "-->" not in body:
                continue

            out_path = workdir / f"transcripcion.{code}.vtt"
            out_path.write_text(body, encoding="utf-8")
            return out_path

    return None


def download_subtitles_vtt(url: str, lang: str, workdir: Path) -> Path:
    direct_vtt = _download_timedtext_vtt(url, lang, workdir)
    if direct_vtt is not None:
        return direct_vtt

    out_tpl = str(workdir / "transcripcion.%(ext)s")
    base_opts = ydl_base_opts(workdir, skip_download=True)

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        if _is_bot_check_error(exc):
            raise RuntimeError(_bot_check_hint()) from exc
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
                raise RuntimeError(_bot_check_hint()) from exc
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
