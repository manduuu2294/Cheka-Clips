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
YOUTUBE_URL = "https://www.youtube.com/watch?v=j11qeggxROY"  # <-- cambia esto
LANG = "es"  # "es" o "en"
# DeepSeek API (https://platform.deepseek.com) — define DEEPSEEK_API_KEY en el entorno
MODEL = "deepseek-chat"
DEEPSEEK_API_BASE = "https://api.deepseek.com"

VTT_FILE = Path(f"transcripcion.{LANG}.vtt")
TXT_FILE = Path("transcripcion.txt")
CLIPS_JSON = Path("clips.json")

# Clips por trozos (más trozos = más minutos de video; más clips = más candidatos)
CHUNK_DURATION_SEC = 600  # 10 min por trozo
MAX_CLIPS_PER_CHUNK = 4  # clips por trozo
MAX_FINAL_CLIPS = 12  # máximo de clips finales (TikTok)
MAX_CHUNKS_TO_PROCESS = 8  # trozos a procesar (ej. 8 × 10 min = hasta ~80 min)
MAX_CHARS_PER_CHUNK = 12_000  # límite de caracteres por trozo
SKIP_FIRST_SECONDS = 120  # saltar intro (ej. 2 min) para evitar música/inglés
MIN_CLIP_DURATION_SEC = 30
MAX_CLIP_DURATION_SEC = 45


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


def split_transcript_into_chunks(transcripcion: str) -> list[str]:
    """
    Divide la transcripción en trozos por tiempo (ej. cada 10 min).
    Cada trozo se limita a MAX_CHARS_PER_CHUNK caracteres (sugerencia 1).
    """
    lines = transcripcion.strip().split("\n")
    # Agrupar por ventana de tiempo: [00:00:00 --> 00:00:05] texto
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
                continue  # saltar intro (música/inglés)
            bucket = sec // CHUNK_DURATION_SEC
            chunk_buckets.setdefault(bucket, []).append(line)
        else:
            # Línea sin timestamp: añadir al último bucket
            if chunk_buckets:
                last_bucket = max(chunk_buckets)
                chunk_buckets[last_bucket].append(line)
    # Ordenar buckets por tiempo y unir líneas; truncar por caracteres
    result = []
    for key in sorted(chunk_buckets):
        chunk_text = "\n".join(chunk_buckets[key])
        if len(chunk_text) > MAX_CHARS_PER_CHUNK:
            # Cortar en límite de caracteres, al final de una línea
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


# =========================
# HELPERS (resto)
# =========================
def run_cmd(cmd: list[str]) -> None:
    """Ejecuta un comando y si falla muestra error útil."""
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.returncode != 0:
        print("ERROR ejecutando comando:\n", " ".join(cmd))
        print("\nSTDOUT:\n", p.stdout)
        print("\nSTDERR:\n", p.stderr)
        raise SystemExit(1)


def download_subtitles_vtt(url: str, lang: str) -> None:
    """
    Descarga SOLO subtítulos automáticos en .vtt.
    No descarga video.
    """
    # Output: transcripcion.<lang>.vtt
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

    # yt-dlp suele guardar como transcripcion.<lang>.vtt (ej: transcripcion.es.vtt)
    if not VTT_FILE.exists():
        # fallback: busca cualquier transcripcion.*.vtt por si el idioma salió distinto
        candidates = list(Path(".").glob("transcripcion.*.vtt"))
        if candidates:
            candidates[0].rename(VTT_FILE)
        else:
            raise SystemExit(f"No encontré archivo .vtt. Esperaba: {VTT_FILE}")

def vtt_to_txt(vtt_path: Path, out_path: Path) -> None:
    lines = vtt_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    def clean_text(t: str) -> str:
        t = re.sub(r"<.*?>", "", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    def ts_to_seconds(ts: str) -> int:
        # "HH:MM:SS" o "MM:SS" (YouTube casi siempre HH:MM:SS)
        parts = ts.split(":")
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            h, m, s = parts
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = parts
            return m * 60 + s
        return int(parts[0])

    def seconds_to_hhmmss(x: int) -> str:
        if x < 0:
            x = 0
        h = x // 3600
        x %= 3600
        m = x // 60
        s = x % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    # 1) Detectar offset base = primer start timestamp encontrado
    base_offset = None
    for line in lines:
        line = line.strip()
        if "-->" in line:
            start_raw = line.split("-->")[0].strip().split(".")[0]
            base_offset = ts_to_seconds(start_raw)
            break
    if base_offset is None:
        raise ValueError("No se encontraron timestamps en el VTT")

    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if "-->" in line:
            start_raw, end_raw = [x.strip() for x in line.split("-->")]
            start = start_raw.split(".")[0]
            end = end_raw.split(".")[0]

            start_s = ts_to_seconds(start) - base_offset
            end_s = ts_to_seconds(end) - base_offset

            j = i + 1
            chunk = []
            while j < len(lines) and lines[j].strip():
                if "-->" not in lines[j]:
                    chunk.append(lines[j].strip())
                j += 1

            text = clean_text(" ".join(chunk))
            if text:
                out_lines.append(
                    f"[{seconds_to_hhmmss(start_s)} --> {seconds_to_hhmmss(end_s)}] {text}"
                )

            i = j
        else:
            i += 1

    out_path.write_text("\n".join(out_lines), encoding="utf-8")

def extract_json(text: str) -> str | None:
    """Extrae una lista JSON del texto (por si el modelo mete texto extra)."""
    if not text:
        return None
    t = text.strip().replace("```json", "").replace("```", "").strip()
    m = re.search(r"\[\s*{.*}\s*\]", t, flags=re.DOTALL)
    return m.group(0) if m else None


def generate_clips(transcripcion: str, max_clips: int = 7) -> list[dict]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit(
            "Falta DEEPSEEK_API_KEY. Crea una API key en https://platform.deepseek.com y define la variable:\n"
            "  Windows (PowerShell): $env:DEEPSEEK_API_KEY = 'sk-...'\n"
            "  Linux/macOS: export DEEPSEEK_API_KEY='sk-...'"
        )
    llm = ChatOpenAI(
        model=MODEL,
        openai_api_key=api_key,
        openai_api_base=DEEPSEEK_API_BASE,
        temperature=0.2,
        max_tokens=4096,
    )

    # Prompt: clips que peguen en TikTok — controversiales, virales, hooks fuertes
    min_c = 1 if max_clips <= 3 else 3
    prompt = dedent(f"""
    DEVUELVE SOLO JSON. NO EXPLIQUES NADA. NO ESCRIBAS TEXTO.

    Eres editor experto para TikTok (canal principal). Tu objetivo es elegir cortes que PEGUEN: virales, que generen comentarios y shares. Prioriza:
    - Momentos CONTROVERSIALES o que generen debate (opiniones fuertes, preguntas incómodas, afirmaciones que "rompan").
    - Hooks que enganchen en los primeros 3 segundos: preguntas, polémica suave, "esto no te lo esperabas", frases punchy y cortas.
    - Ideas que se entiendan sin contexto y que inviten a comentar o compartir. Nada genérico ni relleno.

    REGLAS OBLIGATORIAS:
    - Cada clip DEBE durar entre 30 y 45 segundos. (end - start = entre 30 y 45 segundos).
    - Devuelve EXACTAMENTE entre {min_c} y {max_clips} clips. No más de {max_clips}.
    - title, hook y descripcion deben basarse SOLO en lo que REALMENTE se dice en la transcripción. NO inventes. Resume o parafrasea lo que dice el ponente; el hook debe ser una frase que enganche para TikTok.
    - Cada clip debe tener hook y title DIFERENTES. No repitas la misma frase.
    - Los timestamps están en el texto como [00:MM:SS --> 00:MM:SS]. Usa esos mismos timestamps para start y end.

    Salida: UNA LISTA JSON (array) con entre {min_c} y {max_clips} objetos.
    Campos obligatorios:
    - start: "00:MM:SS" (o "H:MM:SS" si pasa de 1 hora)
    - end: "00:MM:SS"
    - title: 6–10 palabras (resumen punchy, tipo TikTok)
    - hook: 1 frase fuerte (<= 12 palabras) que enganche en los primeros segundos, basada en lo dicho
    - descripcion: 1 o 2 frases con QUÉ SE DICE exactamente en ese tramo
    - why: por qué ese momento puede pegar en TikTok (<= 14 palabras)
    - confidence: 0 a 1

    EJEMPLO DE SALIDA (solo ejemplo, no lo repitas literal):
    [
      {{
        "start": "00:05:30",
        "end": "00:06:05",
        "title": "La verdad incómoda sobre la nube que nadie dice",
        "hook": "Si no mides, pagas de más.",
        "descripcion": "El ponente explica que si no mides el uso de recursos en la nube, acabas pagando de más.",
        "why": "Hook contraintuitivo, genera debate",
        "confidence": 0.84
      }}
    ]

    Ahora genera la salida JSON real para esta transcripción:

    {transcripcion}
    """).strip()

    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    json_block = extract_json(raw)

    # Debug: ver 300 chars por si vuelve a fallar
    if not json_block:
        print("\nDEBUG (primer output, 300 chars):\n", raw[:300], "\n")

        # Segundo intento: convertir el texto a JSON sí o sí
        repair = dedent(f"""
        CONVIERTE A JSON. DEVUELVE SOLO JSON. SIN TEXTO EXTRA.

        Tienes este texto (posible respuesta previa del modelo):
        {raw}

        Devuélvelo en formato JSON LISTA con objetos:
        start, end, title, hook, descripcion, why, confidence

        Reglas:
        - Entre {min_c} y {max_clips} clips. Duración de cada clip: 30 a 45 segundos.
        - start/end deben ser timestamps presentes en la transcripción original (formato 00:MM:SS).
        - confidence 0..1
        """).strip()

        response2 = llm.invoke(repair)
        raw2 = response2.content if hasattr(response2, "content") else str(response2)
        json_block = extract_json(raw2)

    if not json_block:
        print("ERROR: el modelo no devolvió JSON. Output crudo:\n")
        print(raw)
        raise SystemExit(1)

    return json.loads(json_block)


def validate_and_fix_clips(clips: list[dict]) -> list[dict]:
    """
    Valida y corrige la salida del modelo:
    - start < end; duración entre 30 y 45 s (descartar si no); máximo MAX_FINAL_CLIPS; quitar hooks repetidos.
    """
    valid = []
    for c in clips:
        start_s = c.get("start", "")
        end_s = c.get("end", "")
        try:
            start_sec = ts_to_seconds(start_s)
            end_sec = ts_to_seconds(end_s)
        except (ValueError, TypeError):
            continue
        if start_sec >= end_sec:
            continue
        duration = end_sec - start_sec
        if duration < MIN_CLIP_DURATION_SEC or duration > MAX_CLIP_DURATION_SEC:
            continue
        valid.append(c)
    # Quitar hooks repetidos: normalizar (minúsculas, espacios colapsados), quedarse con mayor confidence
    seen_hooks: dict[str, dict] = {}
    for c in valid:
        hook = (c.get("hook") or "").strip().lower()
        hook = re.sub(r"\s+", " ", hook)
        if not hook:
            continue
        if hook not in seen_hooks or (c.get("confidence") or 0) > (seen_hooks[hook].get("confidence") or 0):
            seen_hooks[hook] = c
    unique = list(seen_hooks.values())
    # Ordenar por start y quedarse con máximo MAX_FINAL_CLIPS
    unique.sort(key=lambda x: ts_to_seconds(x.get("start", "")))
    return unique[:MAX_FINAL_CLIPS]


def add_transcripcion_to_clips(clips: list[dict], transcripcion: str) -> None:
    """
    Añade a cada clip el campo 'transcripcion' con el texto completo
    de la transcripción que cae entre start y end de ese clip.
    """
    # Parsear transcripción: cada línea "[HH:MM:SS --> HH:MM:SS] texto"
    lineas: list[tuple[int, int, str]] = []
    for line in transcripcion.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = re.match(r"\[(\d{1,2}:\d{2}:\d{2})\s*-->\s*(\d{1,2}:\d{2}:\d{2})\]\s*(.*)", line)
        if match:
            start_sec = ts_to_seconds(match.group(1))
            end_sec = ts_to_seconds(match.group(2))
            text = match.group(3).strip()
            lineas.append((start_sec, end_sec, text))

    for c in clips:
        clip_start = ts_to_seconds(c.get("start", ""))
        clip_end = ts_to_seconds(c.get("end", ""))
        textos = []
        ultimo = None
        for line_start, line_end, text in lineas:
            if not (line_start < clip_end and line_end > clip_start and text):
                continue
            # Evitar frases repetidas: solo añadir si es distinto al segmento anterior
            if text != ultimo:
                textos.append(text)
                ultimo = text
        c["transcripcion"] = " ".join(textos) if textos else ""


# =========================
# MAIN
# =========================
def main():
    print("1) Descargando subtítulos (solo texto, NO video)...")
    download_subtitles_vtt(YOUTUBE_URL, LANG)
    print(f"   OK -> {VTT_FILE}")

    print("2) Convirtiendo VTT a transcripción con timestamps...")
    vtt_to_txt(VTT_FILE, TXT_FILE)
    print(f"   OK -> {TXT_FILE}")

    print("3) Generando clips con DeepSeek (por trozos)...")
    transcripcion = TXT_FILE.read_text(encoding="utf-8", errors="ignore")
    chunks = split_transcript_into_chunks(transcripcion)
    all_clips: list[dict] = []
    chunks_to_process = chunks[:MAX_CHUNKS_TO_PROCESS]
    if len(chunks_to_process) == 1:
        print(f"   Un solo trozo (intro saltada), generando hasta {MAX_FINAL_CLIPS} clips...")
        all_clips = generate_clips(chunks_to_process[0], max_clips=MAX_FINAL_CLIPS)
    else:
        for i, chunk in enumerate(chunks_to_process):
            if not chunk.strip():
                continue
            print(f"   Trozo {i + 1}/{len(chunks_to_process)} (de {len(chunks)} total) ({len(chunk)} chars)...")
            chunk_clips = generate_clips(chunk, max_clips=MAX_CLIPS_PER_CHUNK)
            all_clips.extend(chunk_clips)
        all_clips.sort(key=lambda c: ts_to_seconds(c.get("start", "")))
    clips = validate_and_fix_clips(all_clips)
    add_transcripcion_to_clips(clips, transcripcion)

    CLIPS_JSON.write_text(json.dumps(clips, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   OK -> {CLIPS_JSON}\n")

    print("Clips sugeridos:\n")
    print(json.dumps(clips, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()













