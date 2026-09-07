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
    last = conn.execute(
        "SELECT question FROM questions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last and last["question"] == question:
        conn.close()
        return
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
        """
        SELECT ts, question, answer FROM questions
        WHERE id IN (SELECT MAX(id) FROM questions GROUP BY question)
        ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def recent_watch(limit: int = 30) -> list[dict]:
    from ingestion.watch_nhnn import _ensure_watch_schema, is_compliance_doc
    from ingestion.watch_summary import sanitize_tom_tat

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
    out = []
    for r in rows:
        item = dict(r)
        if not is_compliance_doc(item.get("title") or "", item.get("url") or ""):
            continue
        item["tom_tat"] = sanitize_tom_tat(item.get("tom_tat") or "")
        out.append(item)
    return _annotate_replacements(out)


_titles_cache: tuple[tuple, tuple[str, ...]] | None = None


def _ingested_titles() -> list[str]:
    global _titles_cache
    processed = ROOT / "data" / "processed"
    if not processed.is_dir():
        _titles_cache = None
        return []
    listing = tuple(sorted(p.name for p in processed.glob("*.json")))
    key = (str(processed), processed.stat().st_mtime, listing)
    if _titles_cache and _titles_cache[0] == key:
        return list(_titles_cache[1])
    titles: list[str] = []
    for name in listing:
        path = processed / name
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rows, list) and rows:
            titles.append(str(rows[0].get("source_doc") or ""))
    _titles_cache = (key, tuple(titles))
    return titles


def _annotate_replacements(items: list[dict]) -> list[dict]:
    from ingestion.watch_nhnn import parse_doc_ref

    by_so: dict[str, list[str]] = {}
    for title in _ingested_titles():
        so = parse_doc_ref(title).get("so_hieu")
        if so:
            by_so.setdefault(so.lower(), []).append(title)
    for item in items:
        so = item.get("so_hieu") or parse_doc_ref(item.get("title") or "").get("so_hieu")
        if not so:
            continue
        names = [n for n in by_so.get(so.lower(), []) if n and n != item.get("title")]
        if names:
            item["goi_y_thay_the"] = (
                f"Kho đã có «{names[0]}» cùng số hiệu {so} — "
                "cân nhắc ghi văn bản thay thế."
            )
    return items
