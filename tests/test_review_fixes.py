from __future__ import annotations

from pathlib import Path

from api.llm import REFUSAL, answer
from vectordb.embed_and_store import upsert_chunks
from vectordb.query import query


def _chunk(chunk_id: str, noi_dung: str, trang_thai: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "noi_dung": noi_dung,
        "dieu": "Điều 1",
        "tieu_de_dieu": "Điều 1. Cho vay",
        "khoan": None,
        "source_doc": "Thông tư test",
        "loai_van_ban": "thong_tu",
        "ngay_hieu_luc": "2017-03-15",
        "trang_thai": trang_thai,
        "van_ban_thay_the": None,
        "file_name_goc": "tt_test.docx",
    }


def test_vietnamese_synonyms_closer_than_unrelated(tmp_path: Path):
    upsert_chunks(
        [
            _chunk(
                "a",
                "Tổ chức tín dụng được cấp tín dụng cho khách hàng theo hợp đồng tín dụng.",
                "con_hieu_luc",
            )
        ],
        tmp_path,
    )
    syn = query("ngân hàng cho khách hàng vay tiền", persist_dir=tmp_path)
    unrelated = query("cách nấu món phở bò Hà Nội", persist_dir=tmp_path)
    assert syn and unrelated
    assert syn[0]["distance"] < unrelated[0]["distance"]


def test_query_default_only_active(tmp_path: Path):
    text = "Cho vay phải có bảo đảm bằng tài sản."
    upsert_chunks(
        [
            _chunk("active", text, "con_hieu_luc"),
            _chunk("expired", text, "het_hieu_luc"),
        ],
        tmp_path,
    )
    hits = query("cho vay phải có bảo đảm", persist_dir=tmp_path)
    assert len(hits) == 1
    assert hits[0]["trang_thai"] == "con_hieu_luc"
    assert hits[0].get("canh_bao_het_hieu_luc") is not True


def test_unrelated_question_refuses(monkeypatch):
    called = []

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("không được gọi LLM")

    monkeypatch.setenv("LLM_API_KEY", "fake-key")
    monkeypatch.setattr("api.llm.httpx.post", boom)
    out = answer(
        "cách nấu phở bò",
        [
            {
                "noi_dung": "Tổ chức tín dụng cho vay theo Thông tư NHNN.",
                "dieu": "Điều 1",
                "source_doc": "Thông tư test",
                "distance": 0.95,
            }
        ],
    )
    assert REFUSAL in out
    assert called == []
