from __future__ import annotations

from pathlib import Path

from vectordb.embed_and_store import CHROMA_DIR, collection, embed_texts


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
    q_emb = embed_texts([text])
    fetch = min(count, max(n * 8, n)) if only_active else n
    raw = col.query(query_embeddings=q_emb, n_results=fetch)
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    dists = (raw.get("distances") or [[]])[0]
    ids = (raw.get("ids") or [[]])[0]
    hits = []
    for i, doc in enumerate(docs):
        meta = metas[i] if i < len(metas) else {}
        hit = {
            "chunk_id": ids[i] if i < len(ids) else meta.get("chunk_id") or "",
            "noi_dung": doc,
            "dieu": meta.get("dieu") or None,
            "khoan": meta.get("khoan") or None,
            "tieu_de_dieu": meta.get("tieu_de_dieu") or None,
            "source_doc": meta.get("source_doc") or "",
            "loai_van_ban": meta.get("loai_van_ban") or "",
            "file_name_goc": meta.get("file_name_goc") or "",
            "co_quan_ban_hanh": meta.get("co_quan_ban_hanh") or "",
            "ngay_hieu_luc": meta.get("ngay_hieu_luc") or "",
            "trang_thai": meta.get("trang_thai") or "",
            "distance": dists[i] if i < len(dists) else None,
        }
        hit["hieu_luc_chua_ro"] = not hit["trang_thai"] or not hit["ngay_hieu_luc"]
        hits.append(hit)
    fallback = False
    if only_active:
        kept = [
            h
            for h in hits
            if not h["trang_thai"] or h["trang_thai"] == "con_hieu_luc"
        ]
        if kept:
            hits = kept[:n]
        else:
            fallback = True
            hits = hits[:n]
            for hit in hits:
                if hit["trang_thai"] and hit["trang_thai"] != "con_hieu_luc":
                    hit["canh_bao_het_hieu_luc"] = True
    else:
        hits = hits[:n]
    return hits
