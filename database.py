import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "analisis.db"
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _conn = None
    for attempt in range(8):
        try:
            _conn = sqlite3.connect(str(DB_PATH), timeout=20)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=DELETE")
            _conn.execute("PRAGMA busy_timeout=20000")
            _conn.execute("PRAGMA synchronous=NORMAL")
            return _conn
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < 7:
                time.sleep(1)
                continue
            raise
    raise sqlite3.OperationalError("No se pudo conectar a la base de datos")


def column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(c["name"] == col for c in cols)


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL DEFAULT '',
            video_url TEXT NOT NULL,
            video_id TEXT,
            video_title TEXT,
            video_duration INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            clip_count INTEGER DEFAULT 0,
            clips_json TEXT
        )
    """)
    if not column_exists(conn, "analyses", "channel"):
        conn.execute("ALTER TABLE analyses ADD COLUMN channel TEXT NOT NULL DEFAULT ''")
    conn.commit()


def save_analysis(channel: str, video_url: str, video_id: str, video_title: str,
                  video_duration: int, clips: list[dict]) -> int:
    conn = _get_conn()
    cur = conn.execute("""
        INSERT INTO analyses (channel, video_url, video_id, video_title, video_duration,
                              created_at, clip_count, clips_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel,
        video_url,
        video_id,
        video_title or "",
        video_duration or 0,
        datetime.now().isoformat(),
        len(clips),
        json.dumps(clips, ensure_ascii=False),
    ))
    conn.commit()
    return cur.lastrowid


def get_analyses(channel: str = "") -> list[dict]:
    conn = _get_conn()
    if channel:
        rows = conn.execute(
            "SELECT id, channel, video_url, video_title, created_at, clip_count FROM analyses WHERE channel = ? OR channel = '' ORDER BY id DESC",
            (channel,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, channel, video_url, video_title, created_at, clip_count FROM analyses ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_analysis(analysis_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["clips"] = json.loads(result.pop("clips_json") or "[]")
    return result


def update_analysis(analysis_id: int, clips: list[dict]) -> bool:
    conn = _get_conn()
    cur = conn.execute("""
        UPDATE analyses SET clips_json = ?, clip_count = ? WHERE id = ?
    """, (
        json.dumps(clips, ensure_ascii=False),
        len(clips),
        analysis_id,
    ))
    conn.commit()
    return cur.rowcount > 0


def delete_analysis(analysis_id: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
    conn.commit()
    return cur.rowcount > 0


def migrate_old_db(old_path: Path, channel: str) -> int:
    if not old_path.exists():
        return 0
    try:
        old_conn = sqlite3.connect(str(old_path))
        old_conn.row_factory = sqlite3.Row
        old_rows = old_conn.execute(
            "SELECT * FROM analyses ORDER BY id"
        ).fetchall()
        old_conn.close()
    except Exception:
        return 0

    count = 0
    conn = _get_conn()
    for row in old_rows:
        exists = conn.execute(
            "SELECT id FROM analyses WHERE id = ? AND channel = ?",
            (row["id"], channel),
        ).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO analyses (id, channel, video_url, video_id, video_title,
                                      video_duration, created_at, clip_count, clips_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"],
                channel,
                row["video_url"],
                row["video_id"],
                row["video_title"],
                row["video_duration"],
                row["created_at"],
                row["clip_count"],
                row["clips_json"],
            ))
            count += 1
    conn.commit()
    return count


def migrate_all_old_dbs():
    base = Path(__file__).parent
    old_antauro = base.parent / "cheka-clips" / "analisis.db"
    old_deepskill = base / "analisis.db"

    antauro_count = migrate_old_db(old_antauro, "antauro_tv")

    deepskill_count = 0
    if old_deepskill.resolve() == DB_PATH.resolve():
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM analyses WHERE channel = '' OR channel IS NULL ORDER BY id"
        ).fetchall()
        for row in rows:
            exists = conn.execute(
                "SELECT id FROM analyses WHERE id = ? AND channel = ?",
                (row["id"], "deepskill"),
            ).fetchone()
            if not exists:
                conn.execute("""
                    INSERT INTO analyses (id, channel, video_url, video_id, video_title,
                                          video_duration, created_at, clip_count, clips_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["id"],
                    "deepskill",
                    row["video_url"],
                    row["video_id"],
                    row["video_title"],
                    row["video_duration"],
                    row["created_at"],
                    row["clip_count"],
                    row["clips_json"],
                ))
                deepskill_count += 1
        conn.commit()

    return antauro_count, deepskill_count
