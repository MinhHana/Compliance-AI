from __future__ import annotations

from pathlib import Path

from matrix.audit import find_outdated_links
from matrix.store import create_link, delete_link, list_links
from matrix.suggest import suggest_links
from vectordb.embed_and_store import upsert_chunks


def _chunk(
    chunk_id: str,
    noi_dung: str,
    *,
    loai: str,
    trang_thai: str = "con_hieu_luc",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "noi_dung": noi_dung,
        "dieu": "Điều 1",
        "tieu_de_dieu": "Điều 1. Cho vay",
        "khoan": None,
        "source_doc": "SOP nội bộ" if loai == "sop_noi_bo" else "Thông tư test",
        "loai_van_ban": loai,
        "ngay_hieu_luc": "2017-03-15",
        "trang_thai": trang_thai,
        "van_ban_thay_the": None,
        "file_name_goc": "sop.docx" if loai == "sop_noi_bo" else "tt.docx",
    }


QD_TEXT = "Tổ chức tín dụng được cấp tín dụng cho khách hàng theo hợp đồng tín dụng."
SOP_TEXT = "Quy trình nội bộ: tổ chức tín dụng cấp tín dụng cho khách hàng theo hợp đồng tín dụng."


def test_link_active_not_outdated(tmp_path: Path):
    chroma = tmp_path / "chroma"
    db = tmp_path / "audit.db"
    upsert_chunks(
        [
            _chunk("sop1", SOP_TEXT, loai="sop_noi_bo"),
            _chunk("qd1", QD_TEXT, loai="thong_tu"),
        ],
        chroma,
    )
    create_link("sop1", "qd1", "", "test", db)
    assert find_outdated_links(chroma, db) == []


def test_expired_regulation_is_outdated(tmp_path: Path):
    chroma = tmp_path / "chroma"
    db = tmp_path / "audit.db"
    upsert_chunks(
        [
            _chunk("sop1", SOP_TEXT, loai="sop_noi_bo"),
            _chunk("qd1", QD_TEXT, loai="thong_tu"),
        ],
        chroma,
    )
    create_link("sop1", "qd1", "", "test", db)
    upsert_chunks(
        [_chunk("qd1", QD_TEXT, loai="thong_tu", trang_thai="het_hieu_luc")],
        chroma,
    )
    out = find_outdated_links(chroma, db)
    assert len(out) == 1
    assert out[0]["quydinh_chunk_id"] == "qd1"
    assert out[0]["canh_bao"] == "quy_dinh_da_thay_doi"


def test_suggest_finds_similar_regulation(tmp_path: Path):
    chroma = tmp_path / "chroma"
    upsert_chunks(
        [
            _chunk("sop1", SOP_TEXT, loai="sop_noi_bo"),
            _chunk("qd1", QD_TEXT, loai="thong_tu"),
            _chunk(
                "qd2",
                "Quy định về giờ làm việc và nghỉ lễ của công chức.",
                loai="thong_tu",
            ),
        ],
        chroma,
    )
    hits = suggest_links("sop1", n=5, persist_dir=chroma)
    ids = [h["chunk_id"] for h in hits]
    assert "qd1" in ids
    assert "sop1" not in ids


def test_duplicate_link_ignored(tmp_path: Path):
    db = tmp_path / "audit.db"
    a = create_link("sop1", "qd1", "a", "test", db)
    b = create_link("sop1", "qd1", "b", "test", db)
    assert a == b
    assert len(list_links(db)) == 1


def test_delete_link(tmp_path: Path):
    db = tmp_path / "audit.db"
    lid = create_link("sop1", "qd1", "", "test", db)
    delete_link(lid, db)
    assert list_links(db) == []
