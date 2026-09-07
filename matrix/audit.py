from __future__ import annotations

from pathlib import Path

from matrix.store import list_links
from vectordb.embed_and_store import CHROMA_DIR, get_chunk


def find_outdated_links(
    persist_dir: str | Path = CHROMA_DIR,
    db_path: str | Path | None = None,
) -> list[dict]:
    outdated: list[dict] = []
    for link in list_links(db_path):
        chunk = get_chunk(link["quydinh_chunk_id"], persist_dir)
        if chunk is None:
            canh_bao = "quy_dinh_khong_con_ton_tai"
        elif chunk.get("trang_thai") != "con_hieu_luc":
            canh_bao = "quy_dinh_da_thay_doi"
        else:
            continue
        item = dict(link)
        item["canh_bao"] = canh_bao
        outdated.append(item)
    return outdated
