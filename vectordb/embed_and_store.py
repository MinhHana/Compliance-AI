from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("vectordb")

ROOT = Path(__file__).resolve().parent.parent
CHROMA_DIR = ROOT / "data" / "chroma"
PROCESSED_DIR = ROOT / "data" / "processed"
COLLECTION = "compliance"


EMBEDDING_MODEL = "BAAI/bge-m3"
_EF = None


def _embedding_function():
    global _EF
    if _EF is None:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

        _EF = SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    return _EF


def _client(persist_dir: str | Path = CHROMA_DIR):
    import chromadb

    Path(persist_dir).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def collection(persist_dir: str | Path = CHROMA_DIR):
    return _client(persist_dir).get_or_create_collection(
        COLLECTION,
        embedding_function=_embedding_function(),
    )


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


def upsert_chunks(chunks: list[dict], persist_dir: str | Path = CHROMA_DIR) -> int:
    if not chunks:
        return 0
    col = collection(persist_dir)
    col.upsert(
        ids=[c["chunk_id"] for c in chunks],
        documents=[c.get("noi_dung") or "" for c in chunks],
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
