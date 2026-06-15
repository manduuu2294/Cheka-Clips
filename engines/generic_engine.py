import json
import re
import tempfile
from pathlib import Path
from textwrap import dedent

import yt_dlp
from langchain_openai import ChatOpenAI
from engines.subtitle_utils import download_subtitles_vtt

MODEL = "deepseek-chat"
DEEPSEEK_API_BASE = "https://api.deepseek.com"
OFFSET_SEC = 0
CHUNK_DURATION_SEC = 300
MAX_CLIPS_PER_CHUNK = 10
MAX_FINAL_CLIPS = 50
MAX_CHARS_PER_CHUNK = 10_000
SKIP_FIRST_SECONDS = 0
MIN_CLIP_DURATION_SEC = 30
MAX_CLIP_DURATION_SEC = 90


def ts_to_seconds(ts: str) -> int:
    parts = ts.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    return int(parts[0]) if parts else 0


def get_video_id(url: str) -> str:
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else ""


def get_video_title(url: str) -> str:
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title", "")
    except Exception:
        return ""


def get_video_duration(url: str) -> int:
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("duration", 0)
    except Exception:
        return 0


def vtt_to_txt(vtt_path: Path, out_path: Path) -> None:
    lines = vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    def clean_text(t: str) -> str:
        t = re.sub(r"<.*?>", "", t)
        words = t.split()
        if not words:
            return ""
        clean_words = [words[0]]
        for w in words[1:]:
            if w.lower() != clean_words[-1].lower():
                clean_words.append(w)
        return " ".join(clean_words)

    def seconds_to_hhmmss(x: int) -> str:
        if x < 0:
            x = 0
        h, m = divmod(x, 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    out_lines = []
    last_text = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if " --> " in line:
            parts = line.split(" --> ")
            start_raw = parts[0].split(".")[0]
            end_raw = parts[1].split(" ")[0].split(".")[0]
            start_s = ts_to_seconds(start_raw) + OFFSET_SEC
            end_s = ts_to_seconds(end_raw) + OFFSET_SEC
            text_parts = []
            j = i + 1
            while j < len(lines) and " --> " not in lines[j]:
                t = lines[j].strip()
                if t:
                    text_parts.append(t)
                j += 1
            full_text = clean_text(" ".join(text_parts))
            if full_text:
                if last_text and full_text.lower().startswith(last_text.lower()):
                    new_part = full_text[len(last_text):].strip()
                    if new_part:
                        out_lines.append(
                            f"[{seconds_to_hhmmss(start_s)} --> {seconds_to_hhmmss(end_s)}] {new_part}"
                        )
                        last_text = full_text
                elif full_text.lower() != last_text.lower():
                    out_lines.append(
                        f"[{seconds_to_hhmmss(start_s)} --> {seconds_to_hhmmss(end_s)}] {full_text}"
                    )
                    last_text = full_text
            i = j
        else:
            i += 1

    out_path.write_text("\n".join(out_lines), encoding="utf-8")


def split_transcript_into_chunks(transcripcion: str) -> list[str]:
    lines = transcripcion.strip().split("\n")
    chunk_buckets: dict[int, list[str]] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r"\[(\d{1,2}:\d{2}:\d{2})\s*-->\s*", line)
        if match:
            start_ts = match.group(1)
            sec = ts_to_seconds(start_ts)
            if sec < SKIP_FIRST_SECONDS:
                continue
            bucket = sec // CHUNK_DURATION_SEC
            chunk_buckets.setdefault(bucket, []).append(line)
        else:
            if chunk_buckets:
                last_bucket = max(chunk_buckets)
                chunk_buckets[last_bucket].append(line)
    result = []
    for key in sorted(chunk_buckets):
        chunk_text = "\n".join(chunk_buckets[key])
        if len(chunk_text) > MAX_CHARS_PER_CHUNK:
            acc = []
            n = 0
            for ln in chunk_buckets[key]:
                if n + len(ln) + 1 <= MAX_CHARS_PER_CHUNK:
                    acc.append(ln)
                    n += len(ln) + 1
                else:
                    break
            chunk_text = "\n".join(acc)
        result.append(chunk_text)
    return result


def extract_json(text: str) -> str | None:
    if not text:
        return None
    t = re.sub(r"```json\s*", "", text)
    t = re.sub(r"```\s*", "", t).strip()
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end != -1 and end > start:
        return t[start:end + 1]
    return None


def generate_clips_from_chunk(transcripcion: str, api_key: str, max_clips: int = 10,
                              viral_examples: list[dict] | None = None) -> list[dict]:
    llm = ChatOpenAI(
        model=MODEL,
        openai_api_key=api_key,
        openai_api_base=DEEPSEEK_API_BASE,
        temperature=0.8,
        max_tokens=4096,
    )

    prompt = dedent(f"""
    DEVUELVE SOLO JSON. NO EXPLIQUES NADA. NO ESCRIBAS TEXTO.

    Eres un editor general de clips virales.
    Extrae los momentos MÁS INTERESANTES, IMPACTANTES o ENTRETENIDOS del video.

    No importa el tema (noticias, fútbol, cursos, política, tecnología, etc.).
    Busca:
    - Momentos que llamen la atención en los primeros segundos
    - Datos curiosos, sorprendentes o polémicos
    - Frases que generen debate o reacción
    - Contenido que alguien querría compartir

    REGLAS:
    - DURACIÓN: Mínimo 30 segundos, máximo 90 segundos.
    - El clip debe tener INICIO y CIERRE con sentido completo.
    - Cada clip debe ser AUTOCONTENIDO (entendible sin contexto previo).
    - Hook debe sonar natural, como si alguien lo dijera en conversación.
    - Precisión en tiempos.

    FORMATO JSON:
    [
      {{
        "start": "HH:MM:SS",
        "end": "HH:MM:SS",
        "title": "Título llamativo del clip",
        "hook": "Frase inicial potente y natural",
        "descripcion": "Por qué este momento es interesante",
        "why": "Qué tipo de reacción puede generar",
        "confidence": 0.9
      }}
    ]

    Transcripción:
    {transcripcion}
    """).strip()

    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    json_block = extract_json(raw)
    if not json_block or json_block == "[]":
        return []
    try:
        return json.loads(json_block)
    except:
        return []


def validate_and_fix_clips(clips: list[dict]) -> list[dict]:
    valid = []
    for c in clips:
        start_s = c.get("start", "")
        end_s = c.get("end", "")
        try:
            start_sec = ts_to_seconds(start_s)
            end_sec = ts_to_seconds(end_s)
        except:
            continue
        if start_sec >= end_sec:
            continue
        duration = end_sec - start_sec
        if duration < MIN_CLIP_DURATION_SEC or duration > MAX_CLIP_DURATION_SEC:
            continue
        valid.append(c)

    seen_hooks: dict[str, dict] = {}
    for c in valid:
        hook = (c.get("hook") or "").strip().lower()
        hook = re.sub(r"\s+", " ", hook)
        if not hook:
            continue
        if hook not in seen_hooks or (c.get("confidence") or 0) > (
            seen_hooks[hook].get("confidence") or 0
        ):
            seen_hooks[hook] = c

    unique = list(seen_hooks.values())
    unique.sort(key=lambda x: ts_to_seconds(x.get("start", "")))
    return unique[:MAX_FINAL_CLIPS]


def add_transcripcion_to_clips(clips: list[dict], transcripcion: str) -> None:
    lineas = []
    for line in transcripcion.strip().split("\n"):
        match = re.match(
            r"\[(\d{1,2}:\d{2}:\d{2})\s*-->\s*(\d{1,2}:\d{2}:\d{2})\]\s*(.*)", line
        )
        if match:
            lineas.append((
                ts_to_seconds(match.group(1)),
                ts_to_seconds(match.group(2)),
                match.group(3).strip(),
            ))

    for c in clips:
        clip_start = ts_to_seconds(c.get("start", ""))
        clip_end = ts_to_seconds(c.get("end", ""))
        textos = []
        ultimo = None
        for line_start, line_end, text in lineas:
            if (line_start < clip_end and line_end > (clip_start - 5)) and text:
                if text != ultimo:
                    textos.append(text)
                    ultimo = text
        c["transcripcion"] = " ".join(textos) if textos else ""
        if c["transcripcion"]:
            hook_lower = (c.get("hook") or "").lower()
            if hook_lower and hook_lower not in c["transcripcion"].lower():
                c["confidence"] = (c.get("confidence") or 0) * 0.5


def extract_clips(youtube_url: str, api_key: str, lang: str = "es",
                  progress_callback=None,
                  viral_examples: list[dict] | None = None) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)

        if progress_callback:
            progress_callback(0, "Descargando subtítulos...")

        langs = [lang, "en"]
        vtt_path = None
        last_err = ""
        for l in langs:
            try:
                vtt_path = download_subtitles_vtt(youtube_url, l, workdir)
                break
            except RuntimeError as e:
                last_err = str(e)
                continue
        if vtt_path is None:
            raise RuntimeError(f"No se pudieron descargar subtítulos: {last_err}")

        if progress_callback:
            progress_callback(15, "Procesando transcripción...")

        txt_path = workdir / "transcripcion.txt"
        vtt_to_txt(vtt_path, txt_path)

        transcripcion = txt_path.read_text(encoding="utf-8", errors="ignore")
        if not transcripcion.strip():
            raise RuntimeError("La transcripción está vacía.")

        chunks = split_transcript_into_chunks(transcripcion)

        if progress_callback:
            progress_callback(20, f"Procesando {len(chunks)} trozos con IA...")

        all_clips = []
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            pct = 20 + int((i / len(chunks)) * 60)
            if progress_callback:
                progress_callback(pct, f"Trozo {i + 1}/{len(chunks)} — analizando...")
            chunk_clips = generate_clips_from_chunk(chunk, api_key)
            all_clips.extend(chunk_clips)

        if progress_callback:
            progress_callback(85, "Validando y deduplicando clips...")

        all_clips.sort(key=lambda c: ts_to_seconds(c.get("start", "")))
        clips = validate_and_fix_clips(all_clips)

        if progress_callback:
            progress_callback(95, "Asociando transcripciones...")
        add_transcripcion_to_clips(clips, transcripcion)

        if progress_callback:
            progress_callback(100, f"¡Completado! {len(clips)} clips encontrados.")
        return clips
