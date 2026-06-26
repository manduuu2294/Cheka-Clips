import base64
import gzip
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yt_dlp


BOT_CHECK_HINT = (
    "YouTube está pidiendo verificación anti-bot. Configura cookies de YouTube "
    "en Railway usando YOUTUBE_COOKIES_GZIP_BASE64."
)
BOT_CHECK_WITH_COOKIES_HINT = (
    "YouTube está pidiendo verificación anti-bot aunque hay cookies configuradas. "
    "Las cookies cargadas no fueron aceptadas por YouTube; normalmente están vencidas, "
    "son de otra cuenta/sesión o no incluyen dominios de youtube.com/google.com. "
    "Regenera YOUTUBE_COOKIES_GZIP_BASE64 con cookies recientes de una sesión activa."
)


def _is_bot_check_error(error: Exception) -> bool:
    text = str(error).lower()
    return "not a bot" in text or "sign in to confirm" in text


def _bot_check_hint(cookiefile: str | None = None) -> str:
    return BOT_CHECK_WITH_COOKIES_HINT if cookiefile else BOT_CHECK_HINT


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


def _is_cookie_comment(line: str) -> bool:
    stripped = line.lstrip()
    return stripped.startswith("#") and not stripped.startswith("#HttpOnly_")


def _cookie_domain(parts: list[str]) -> str:
    return parts[0].removeprefix("#HttpOnly_")


def _validate_cookie_text(raw: str) -> None:
    cookie_lines = [
        line for line in raw.splitlines()
        if line.strip() and not _is_cookie_comment(line)
    ]
    if not cookie_lines:
        raise RuntimeError("La variable de cookies de YouTube está vacía.")

    parsed = []
    for line in cookie_lines:
        parts = line.split("\t")
        if len(parts) >= 7:
            parsed.append(parts)
    if not parsed:
        raise RuntimeError(
            "Las cookies de YouTube no tienen formato Netscape. Exporta cookies.txt "
            "y vuelve a generar YOUTUBE_COOKIES_GZIP_BASE64."
        )

    youtube_rows = [
        parts for parts in parsed
        if "youtube.com" in _cookie_domain(parts).lower()
        or "google.com" in _cookie_domain(parts).lower()
    ]
    if not youtube_rows:
        raise RuntimeError(
            "Las cookies configuradas no contienen dominios de youtube.com/google.com."
        )

    now = int(time.time())
    live_rows = []
    for parts in youtube_rows:
        try:
            expires = int(parts[4])
        except ValueError:
            continue
        if expires == 0 or expires > now:
            live_rows.append(parts)
    if not live_rows:
        raise RuntimeError(
            "Las cookies configuradas para YouTube/Google están vencidas. "
            "Regenera YOUTUBE_COOKIES_GZIP_BASE64 con cookies recientes."
        )

def _cookiefile_from_env(workdir: Path | None = None) -> str | None:
    path = os.environ.get("YOUTUBE_COOKIES_PATH") or os.environ.get("YT_DLP_COOKIES_PATH")
    if path and Path(path).exists():
        return path

    raw = ""
    gzip_encoded = os.environ.get("YOUTUBE_COOKIES_GZIP_BASE64", "").strip()
    encoded = os.environ.get("YOUTUBE_COOKIES_BASE64", "").strip()
    if gzip_encoded:
        try:
            raw = gzip.decompress(base64.b64decode("".join(gzip_encoded.split()))).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("YOUTUBE_COOKIES_GZIP_BASE64 no es un gzip+base64 válido.") from exc
    elif encoded:
        try:
            raw = base64.b64decode("".join(encoded.split())).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("YOUTUBE_COOKIES_BASE64 no es un base64 válido.") from exc
    else:
        raw = (
            os.environ.get("YOUTUBE_COOKIES_CONTENT", "")
            or os.environ.get("YOUTUBE_COOKIES", "")
        )
    raw = raw.replace("\\n", "\n").strip()

    if not raw:
        return None
    _validate_cookie_text(raw)

    target_dir = workdir if workdir is not None else Path(tempfile.gettempdir())
    target = target_dir / "youtube_cookies.txt"
    target.write_text(raw, encoding="utf-8")
    return str(target)


def _cookie_header_from_file(cookiefile: str | None) -> str:
    if not cookiefile:
        return ""
    try:
        raw = Path(cookiefile).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

    pairs = []
    for line in raw.splitlines():
        if not line.strip() or _is_cookie_comment(line):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _, path, _, expires, name, value = parts[:7]
        domain = domain.removeprefix("#HttpOnly_")
        domain_l = domain.lower()
        if "youtube.com" not in domain_l and "google.com" not in domain_l:
            continue
        try:
            expires_i = int(expires)
        except ValueError:
            expires_i = 0
        if expires_i and expires_i <= int(time.time()):
            continue
        if path and name and value:
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

    base_opts = ydl_base_opts(workdir)
    headers = dict(base_opts.get("http_headers", {}))
    cookie_header = _cookie_header_from_file(base_opts.get("cookiefile"))
    if cookie_header:
        headers["Cookie"] = cookie_header
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
            raise RuntimeError(_bot_check_hint(base_opts.get("cookiefile"))) from exc
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
                raise RuntimeError(_bot_check_hint(base_opts.get("cookiefile"))) from exc
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
