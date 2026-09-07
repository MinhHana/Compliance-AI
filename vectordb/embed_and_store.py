from __future__ import annotations

import json
import logging
from pathlib import Path

from ingestion.doc_attrs import warn_level

logger = logging.getLogger("vectordb")

ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = ROOT / "data" / "chroma"
PROCESSED_DIR = ROOT / "data" / "processed"
COLLECTION = "compliance"


EMBEDDING_MODEL = "BAAI/bge-m3"
_EF = None
_CLIENTS: dict[str, object] = {}
_COLS: dict[str, object] = {}


def _embedding_function():
    global _EF
    if _EF is None:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        _EF = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _EF


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return _embedding_function()(texts)


def _dir_key(persist_dir: str | Path) -> str:
    path = Path(persist_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path.resolve())


def _client(persist_dir: str | Path = CHROMA_DIR):
    key = _dir_key(persist_dir)
    client = _CLIENTS.get(key)
    if client is None:
        import chromadb

        client = chromadb.PersistentClient(path=key)
        _CLIENTS[key] = client
    return client


def collection(persist_dir: str | Path = CHROMA_DIR):
    key = _dir_key(persist_dir)
    col = _COLS.get(key)
    if col is None:
        col = _client(persist_dir).get_or_create_collection(COLLECTION)
        _COLS[key] = col
    return col


def get_chunk(chunk_id: str, persist_dir: str | Path = CHROMA_DIR) -> dict | None:
    col = collection(persist_dir)
    r = col.get(ids=[chunk_id])
    if not r["ids"]:
        return None
    meta = dict((r["metadatas"] or [{}])[0] or {})
    meta["noi_dung"] = (r["documents"] or [None])[0]
    meta["chunk_id"] = chunk_id
    return meta


def _meta(chunk: dict) -> dict:
    skip = {"noi_dung"}
    out = {}
    for key, value in chunk.items():
        if key in skip:
            continue
        if value is None:
            out[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


def list_documents(persist_dir: str | Path = CHROMA_DIR) -> list[dict]:
    try:
        col = collection(persist_dir)
        if col.count() == 0:
            return []
        raw = col.get(include=["metadatas"])
    except Exception:
        logger.exception("list_documents lỗi")
        return []
    grouped: dict[str, dict] = {}
    for meta in raw.get("metadatas") or []:
        meta = meta or {}
        source = meta.get("source_doc") or ""
        if source not in grouped:
            raw_w = meta.get("attr_warnings") or "[]"
            try:
                warnings = json.loads(raw_w) if isinstance(raw_w, str) else list(raw_w)
            except (TypeError, ValueError):
                warnings = []
            grouped[source] = {
                "source_doc": source,
                "loai_van_ban": meta.get("loai_van_ban") or "",
                "ngay_ban_hanh": meta.get("ngay_ban_hanh") or "",
                "ngay_hieu_luc": meta.get("ngay_hieu_luc") or "",
                "trang_thai": meta.get("trang_thai") or "",
                "ly_do_ban_hanh": meta.get("ly_do_ban_hanh") or "",
                "co_quan_ban_hanh": meta.get("co_quan_ban_hanh") or "",
                "attr_warnings": warnings,
                "warn_level": warn_level(warnings),
                "so_chunk": 0,
            }
        grouped[source]["so_chunk"] += 1
    docs = list(grouped.values())
    docs.sort(key=lambda d: d.get("ngay_hieu_luc") or "", reverse=True)
    return docs


def delete_by_source_doc(source_doc: str, persist_dir: str | Path = CHROMA_DIR) -> int:
    if not source_doc:
        return 0
    col = collection(persist_dir)
    try:
        raw = col.get(where={"source_doc": source_doc})
    except Exception:
        logger.exception("delete_by_source_doc get lỗi")
        return 0
    ids = raw.get("ids") or []
    if not ids:
        return 0
    col.delete(ids=ids)
    return len(ids)


def upsert_chunks(chunks: list[dict], persist_dir: str | Path = CHROMA_DIR) -> int:
    if not chunks:
        return 0
    col = collection(persist_dir)
    docs = [c.get("noi_dung") or "" for c in chunks]
    col.upsert(
        ids=[c["chunk_id"] for c in chunks],
        documents=docs,
        embeddings=embed_texts(docs),
        metadatas=[_meta(c) for c in chunks],
    )
    return len(chunks)


def embed_processed_dir(
    processed_dir: str | Path = PROCESSED_DIR,
    persist_dir: str | Path = CHROMA_DIR,
) -> int:
    total = 0
    folder = Path(processed_dir)
    if not folder.exists():
        return 0
    for path in sorted(folder.glob("*.json")):
        try:
            chunks = json.loads(path.read_text(encoding="utf-8"))
            total += upsert_chunks(chunks, persist_dir)
        except Exception as exc:
            logger.error("Không embed %s: %s", path.name, exc)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = embed_processed_dir()
    print(f"Đã lưu {n} chunk.")
