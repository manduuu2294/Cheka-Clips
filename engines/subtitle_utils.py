from pathlib import Path

import yt_dlp


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
    base_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
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
        except yt_dlp.utils.DownloadError:
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
