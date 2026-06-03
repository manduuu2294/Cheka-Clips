import json
import os
import re
import subprocess
from pathlib import Path
from textwrap import dedent

from langchain_openai import ChatOpenAI

# =========================
# CONFIG
# =========================
YOUTUBE_URL = "https://www.youtube.com/watch?v=1UCWVl_iJ-o"  # <-- cambia esto
LANG = "es"  # "es" o "en"
# DeepSeek API (https://platform.deepseek.com) — define DEEPSEEK_API_KEY en el entorno
MODEL = "deepseek-chat"
DEEPSEEK_API_BASE = "https://api.deepseek.com"

# Ajuste de tiempo: segundos a SUMAR a los subtítulos para que coincidan con el video de YouTube.
# En este video los subtítulos VTT de YouTube YA coinciden con el video (ej. "Hola" está a 2:17 en ambos).
# Por tanto OFFSET debe ser 0. Si en otro video hubiera intro, sería segundos a sumar/restar.
OFFSET_SEC = 0
VTT_FILE = Path(f"transcripcion.{LANG}.vtt")
TXT_FILE = Path("transcripcion.txt")
CLIPS_JSON = Path("clips.json")
CLIPS_PERFORMANCE_JSON = Path("clips_performance.json")

# Clips por trozos (más trozos = más minutos de video; más clips = más candidatos)
# Clips por trozos (más trozos = más minutos de video; más clips = más candidatos)
CHUNK_DURATION_SEC = 300  # Reducido a 5 min para máxima exhaustividad
MAX_CLIPS_PER_CHUNK = 15
MAX_FINAL_CLIPS = 100  # Aumentado para no perder nada
MAX_CHARS_PER_CHUNK = 10_000
SKIP_FIRST_SECONDS = 0  # Procesar desde el inicio con el ajuste de tiempo negativo
MIN_CLIP_DURATION_SEC = 20  # Bajado a 20s para no omitir nada que sea valioso
MAX_CLIP_DURATION_SEC = 180  # Mantenido en 3 min para historias largas


# =========================
# HELPERS
# =========================
def ts_to_seconds(ts: str) -> int:
    """Convierte 'HH:MM:SS' o 'MM:SS' a segundos totales."""
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
    """Extrae el ID de video de una URL de YouTube."""
    match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
    return match.group(1) if match else "unknown_video"


def split_transcript_into_chunks(transcripcion: str) -> list[str]:
    """
    Divide la transcripción en trozos por tiempo (ej. cada 15 min).
    """
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


def run_cmd(cmd: list[str]) -> None:
    """Ejecuta un comando y si falla muestra error útil."""
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        print("ERROR ejecutando comando:\n", " ".join(cmd))
        print("\nSTDOUT:\n", p.stdout)
        print("\nSTDERR:\n", p.stderr)
        raise SystemExit(1)


def download_subtitles_vtt(url: str, lang: str) -> None:
    """Descarga SOLO subtítulos automáticos en .vtt."""
    out_tpl = "transcripcion.%(ext)s"
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-auto-subs",
        "--sub-lang",
        lang,
        "-o",
        out_tpl,
        url,
    ]
    run_cmd(cmd)
    if not VTT_FILE.exists():
        candidates = list(Path(".").glob("transcripcion.*.vtt"))
        if candidates:
            candidates[0].rename(VTT_FILE)
        else:
            raise SystemExit(f"No encontré archivo .vtt. Esperaba: {VTT_FILE}")


def vtt_to_txt(vtt_path: Path, out_path: Path) -> None:
    lines = vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    def clean_text(t: str) -> str:
        # Eliminar tags <c>, <00:00:00.000>, etc.
        t = re.sub(r"<.*?>", "", t)
        # Quitar espacios extra
        words = t.split()
        if not words:
            return ""
        # Deduplicar palabras seguidas (ej: "hola hola")
        clean_words = [words[0]]
        for w in words[1:]:
            if w.lower() != clean_words[-1].lower():
                clean_words.append(w)
        return " ".join(clean_words)

    def seconds_to_hhmmss(x: int) -> str:
        if x < 0:
            x = 0  # evita tiempos negativos en el TXT
        h, m = divmod(x, 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    out_lines = []
    last_text = ""
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if " --> " in line:
            # Extraer tiempos
            parts = line.split(" --> ")
            start_raw = parts[0].split(".")[0]
            end_raw = parts[1].split(" ")[0].split(".")[0]

            start_s = ts_to_seconds(start_raw) + OFFSET_SEC
            end_s = ts_to_seconds(end_raw) + OFFSET_SEC

            # Buscar el texto en las líneas siguientes
            text_parts = []
            j = i + 1
            while j < len(lines) and " --> " not in lines[j]:
                t = lines[j].strip()
                if t:
                    text_parts.append(t)
                j += 1

            full_text = clean_text(" ".join(text_parts))

            if full_text:
                # Lógica para evitar la repetición de "rolling captions" de YouTube
                # Si el texto actual empieza con el texto anterior, solo nos quedamos con la parte nueva
                if last_text and full_text.lower().startswith(last_text.lower()):
                    new_part = full_text[len(last_text) :].strip()
                    if new_part:
                        out_lines.append(
                            f"[{seconds_to_hhmmss(start_s)} --> {seconds_to_hhmmss(end_s)}] {new_part}"
                        )
                        last_text = full_text  # Actualizamos con el total para la siguiente comparación
                elif full_text.lower() != last_text.lower():
                    out_lines.append(
                        f"[{seconds_to_hhmmss(start_s)} --> {seconds_to_hhmmss(end_s)}] {full_text}"
                    )
                    last_text = full_text

            i = j
        else:
            i += 1

    out_path.write_text("\n".join(out_lines), encoding="utf-8")


def extract_json(text: str) -> str | None:
    """Extrae una lista JSON del texto."""
    if not text:
        return None
    t = re.sub(r"```json\s*", "", text)
    t = re.sub(r"```\s*", "", t).strip()
    start = t.find("[")
    end = t.rfind("]")
    if start != -1 and end != -1 and end > start:
        return t[start : end + 1]
    return None


def generate_clips(transcripcion: str, max_clips: int = 20) -> list[dict]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("Falta DEEPSEEK_API_KEY.")

    llm = ChatOpenAI(
        model=MODEL,
        openai_api_key=api_key,
        openai_api_base=DEEPSEEK_API_BASE,
        temperature=0.7,  # Aumentado para mayor detección de "pepitas"
        max_tokens=4096,
    )

    prompt = dedent(f"""
    DEVUELVE SOLO JSON. NO EXPLIQUES NADA. NO ESCRIBAS TEXTO.

    Eres un editor experto en contenido de alto valor para programadores.
    Tu misión es extraer clips que sean "pepitas de oro" (conocimiento útil, roadmaps, consejos de carrera).

    CRÍTICO: REVISIÓN DE TRANSCRIPCIÓN Y COHERENCIA
    1. REVISA LA TRANSCRIPCIÓN: Antes de definir los tiempos (start/end), lee la transcripción adjunta. Asegúrate de que el clip NO empiece a mitad de una frase o palabra.
    2. AJUSTE DE TIEMPOS: Si Eric empieza a hablar de una idea en "00:13:52", no pongas "00:13:56". Sé preciso. El clip debe incluir el sujeto y el contexto para que se entienda quién habla y de qué.
    3. COHERENCIA TOTAL: El Título, el Hook y la Transcripción deben estar perfectamente alineados. Si el título dice "Cómo entrar a Amazon", la transcripción del clip debe hablar EXACTAMENTE de eso, sin dejar ideas incompletas al final.
    4. SIN HUECOS: Asegúrate de que el clip tenga un inicio limpio y un cierre con sentido completo.

    QUÉ BUSCAMOS:
    - Clips de ALTO VALOR.
    - DURACIÓN: Preferiblemente de 40 segundos en adelante para asegurar que la idea sea clara.
    - EXCEPCIÓN: Si encuentras una "pepita de oro" muy potente de menos de 40 segundos (incluso de 20-30s), NO LA OMITAS, inclúyela también.
    - Consejos técnicos, roadmaps, estadísticas, realidades de Big Tech, metodologías de estudio.
    - Evita datos biográficos irrelevantes ("estudié en X") a menos que aporten una lección.
    - IMPORTANTE: No cortes la idea antes de tiempo. Asegúrate de que el clip tenga un inicio y un fin con sentido completo. Es mejor un clip un poco más largo que uno corto que no se entiende.

    FORMATO JSON:
    [
      {{
        "start": "HH:MM:SS",
        "end": "HH:MM:SS",
        "title": "Título coherente con el contenido",
        "hook": "Frase inicial potente que aparece en el clip",
        "descripcion": "Explicación clara del valor del clip",
        "why": "Por qué es útil para un programador",
        "confidence": 0.95
      }}
    ]

    Transcripción:
    {transcripcion}
    """).strip()

    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    json_block = extract_json(raw)

    if not json_block or json_block == "[]":
        print(f"      (No se encontraron clips en este trozo)")
        return []

    try:
        data = json.loads(json_block)
        print(f"      (Se encontraron {len(data)} clips potenciales)")
        return data
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
    lineas: list[tuple[int, int, str]] = []
    for line in transcripcion.strip().split("\n"):
        match = re.match(
            r"\[(\d{1,2}:\d{2}:\d{2})\s*-->\s*(\d{1,2}:\d{2}:\d{2})\]\s*(.*)", line
        )
        if match:
            lineas.append(
                (
                    ts_to_seconds(match.group(1)),
                    ts_to_seconds(match.group(2)),
                    match.group(3).strip(),
                )
            )

    for c in clips:
        clip_start = ts_to_seconds(c.get("start", ""))
        clip_end = ts_to_seconds(c.get("end", ""))
        textos = []
        ultimo = None

        # Ajuste dinámico: Si el clip empieza unos segundos después de una línea de transcripción,
        # pero esa línea es el inicio natural de la frase, la incluimos.
        buffer_inicio = 5  # segundos

        for line_start, line_end, text in lineas:
            # Incluimos la línea si está dentro del rango o si está muy cerca del inicio (contexto)
            if (
                line_start < clip_end and line_end > (clip_start - buffer_inicio)
            ) and text:
                if text != ultimo:
                    textos.append(text)
                    ultimo = text

        c["transcripcion"] = " ".join(textos) if textos else ""

        # Validación extra de coherencia
        if c["transcripcion"]:
            # Si el hook no está en la transcripción, el LLM podría estar inventando tiempos
            hook_lower = (c.get("hook") or "").lower()
            if hook_lower and hook_lower not in c["transcripcion"].lower():
                c["confidence"] = (
                    c.get("confidence") or 0
                ) * 0.5  # Bajamos confianza si no hay match


def main():
    # Eliminar clips.json previo para asegurar que siempre se genere uno nuevo
    if CLIPS_JSON.exists():
        CLIPS_JSON.unlink()

    print("1) Descargando subtítulos...")
    # Eliminar VTT previo para asegurar que siempre se descargue el del video actual
    if VTT_FILE.exists():
        VTT_FILE.unlink()
    download_subtitles_vtt(YOUTUBE_URL, LANG)

    print("2) Convirtiendo VTT a transcripción...")
    # Forzamos la regeneración del TXT para aplicar el nuevo OFFSET_SEC
    if TXT_FILE.exists():
        TXT_FILE.unlink()
    vtt_to_txt(VTT_FILE, TXT_FILE)

    print("3) Generando clips con DeepSeek...")
    transcripcion = TXT_FILE.read_text(encoding="utf-8", errors="ignore")
    if not transcripcion.strip():
        print("ERROR: La transcripción está vacía. Revisa el archivo VTT.")
        return

    chunks = split_transcript_into_chunks(transcripcion)

    print(f"   Video dividido en {len(chunks)} trozos de 15 min.")

    all_clips: list[dict] = []
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        print(f"   Procesando trozo {i + 1}/{len(chunks)}...")
        chunk_clips = generate_clips(chunk, max_clips=MAX_CLIPS_PER_CHUNK)
        all_clips.extend(chunk_clips)

    all_clips.sort(key=lambda c: ts_to_seconds(c.get("start", "")))
    clips = validate_and_fix_clips(all_clips)
    add_transcripcion_to_clips(clips, transcripcion)

    CLIPS_JSON.write_text(
        json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Guardar en historial
    video_id = get_video_id(YOUTUBE_URL)
    perf_list = []
    if CLIPS_PERFORMANCE_JSON.exists():
        try:
            perf_list = json.loads(CLIPS_PERFORMANCE_JSON.read_text(encoding="utf-8"))
        except:
            perf_list = []

    existing_video_ids = {c.get("video") for c in perf_list}
    if video_id not in existing_video_ids:
        for c in clips:
            perf_list.append(
                {
                    "video": video_id,
                    "start": c.get("start"),
                    "title": c.get("title"),
                    "hook": c.get("hook"),
                    "status": "published",
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                    "retention_full_video": 0,
                    "saves_shares": 0,
                    "new_followers": 0,
                    "notes": "",
                }
            )
        CLIPS_PERFORMANCE_JSON.write_text(
            json.dumps(perf_list, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"\nOK. Se han generado {len(clips)} clips en total.")


if __name__ == "__main__":
    main()
