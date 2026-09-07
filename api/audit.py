from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "audit.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            citations TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def log_question(question: str, answer: str, citations: list[dict]) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO questions (ts, question, answer, citations) VALUES (?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            question,
            answer,
            json.dumps(citations, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def recent_questions(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT ts, question, answer FROM questions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recent_watch(limit: int = 30) -> list[dict]:
    from ingestion.watch_nhnn import _ensure_watch_schema

    conn = _conn()
    _ensure_watch_schema(conn)
    rows = conn.execute(
        """
        SELECT title, url, source, first_seen, loai_van_ban_doan, so_hieu, tom_tat
        FROM watch_items
        ORDER BY first_seen DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
