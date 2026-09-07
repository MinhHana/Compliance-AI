from __future__ import annotations

import httpx

from ingestion.watch_nhnn import parse_doc_ref
from ingestion.watch_summary import summarize_new_items


def test_parse_thong_tu():
    r = parse_doc_ref("Thông tư số 39/2016/TT-NHNN quy định về hoạt động cho vay")
    assert r["loai_van_ban_doan"] == "thong_tu"
    assert "39/2016/TT-NHNN" in (r["so_hieu"] or "")


def test_parse_no_so_hieu():
    r = parse_doc_ref("Họp báo thường kỳ của Ngân hàng Nhà nước")
    assert r["loai_van_ban_doan"] is None
    assert r["so_hieu"] is None


def test_summarize_fetch_fail(monkeypatch):
    def boom(*_a, **_k):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("ingestion.watch_summary.httpx.get", boom)
    items = summarize_new_items(
        [{"url": "https://example.invalid/x", "title": "x"}]
    )
    assert len(items) == 1
    assert items[0]["tom_tat"]


def test_summarize_no_llm_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    posts = []

    class Resp:
        text = (
            "<html><body><p>Nội dung văn bản quy định về cho vay "
            "tổ chức tín dụng theo thông tư.</p></body></html>"
        )

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "ingestion.watch_summary.httpx.get", lambda *_a, **_k: Resp()
    )
    monkeypatch.setattr(
        "api.llm.httpx.post", lambda *_a, **_k: posts.append(1) or None
    )
    items = summarize_new_items(
        [{"url": "https://example.test/vb", "title": "vb"}]
    )
    assert posts == []
    assert items[0]["tom_tat"]
    assert "cho vay" in items[0]["tom_tat"]
