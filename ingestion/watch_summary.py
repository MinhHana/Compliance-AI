"""Tóm tắt văn bản mới phát hiện bởi watch_nhnn."""

from __future__ import annotations

import logging

import httpx

from api.llm import configured, summarize_snippet
from ingestion.watch_nhnn import _clean, _db

logger = logging.getLogger("watch_summary")

FETCH_TIMEOUT = 15
SNIPPET_CHARS = 800
FALLBACK_CHARS = 200
UNREACHABLE = "không truy cập được"


def _fetch_text(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=FETCH_TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Không tải được %s: %s", url, exc)
        return None
    return _clean(resp.text)[:SNIPPET_CHARS]


def summarize_new_items(items: list[dict]) -> list[dict]:
    """Gắn field tom_tat cho từng item. 1 item lỗi không dừng cả batch."""
    out: list[dict] = []
    conn = _db()
    use_llm = configured()
    for item in items:
        snippet = _fetch_text(item.get("url") or "")
        if snippet is None:
            tom_tat = UNREACHABLE
        elif use_llm:
            tom_tat = summarize_snippet(snippet)
        else:
            tom_tat = snippet[:FALLBACK_CHARS]
        updated = {**item, "tom_tat": tom_tat}
        item_id = item.get("id")
        if item_id:
            conn.execute(
                "UPDATE watch_items SET tom_tat = ? WHERE id = ?",
                (tom_tat, item_id),
            )
        out.append(updated)
    conn.commit()
    conn.close()
    return out
