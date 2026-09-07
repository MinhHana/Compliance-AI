from __future__ import annotations

from pathlib import Path

from vectordb.embed_and_store import CHROMA_DIR, collection


def query(
    text: str,
    n_results: int = 5,
    persist_dir: str | Path = CHROMA_DIR,
    only_active: bool = True,
) -> list[dict]:
    col = collection(persist_dir)
    count = col.count()
    if count == 0 or not text.strip():
        return []
    n = min(n_results, count)
    fallback = False
    raw = None
    if only_active:
        try:
            raw = col.query(
                query_texts=[text],
                n_results=n,
                where={"trang_thai": "con_hieu_luc"},
            )
            if not (raw.get("documents") or [[]])[0]:
                fallback = True
                raw = None
        except Exception:
            fallback = True
            raw = None
    if raw is None:
        raw = col.query(query_texts=[text], n_results=n)
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    dists = (raw.get("distances") or [[]])[0]
    hits = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        hit = {
            "noi_dung": doc,
            "dieu": meta.get("dieu") or None,
            "khoan": meta.get("khoan") or None,
            "tieu_de_dieu": meta.get("tieu_de_dieu") or None,
            "source_doc": meta.get("source_doc") or "",
            "file_name_goc": meta.get("file_name_goc") or "",
            "ngay_hieu_luc": meta.get("ngay_hieu_luc") or "",
            "trang_thai": meta.get("trang_thai") or "",
            "distance": dists[i] if i < len(dists) else None,
        }
        if fallback:
            hit["canh_bao_het_hieu_luc"] = True
        hits.append(hit)
    return hits
