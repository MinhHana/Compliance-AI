from __future__ import annotations

from pathlib import Path

from vectordb.embed_and_store import CHROMA_DIR, get_chunk
from vectordb.query import query


def suggest_links(
    sop_chunk_id: str,
    n: int = 5,
    persist_dir: str | Path = CHROMA_DIR,
) -> list[dict]:
    chunk = get_chunk(sop_chunk_id, persist_dir)
    if not chunk:
        return []
    text = (chunk.get("noi_dung") or "").strip()
    if not text:
        return []
    hits = query(
        text,
        n_results=max(n * 4, n + 8),
        persist_dir=persist_dir,
        only_active=False,
    )
    out: list[dict] = []
    for hit in hits:
        cid = hit.get("chunk_id")
        if not cid or cid == sop_chunk_id:
            continue
        if hit.get("loai_van_ban") == "sop_noi_bo":
            continue
        out.append(hit)
        if len(out) >= n:
            break
    return out
