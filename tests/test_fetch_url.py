from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.batch import process_url
from ingestion.chunk_by_dieu import SourceMetadata
from ingestion.fetch_url import FetchUrlError, fetch_law_document, html_to_text

META = SourceMetadata(
    source_doc="Thông tư 39/2016/TT-NHNN",
    loai_van_ban="thong_tu",
    ngay_hieu_luc="2017-03-15",
    trang_thai="con_hieu_luc",
)

HTML = """<!doctype html><html><head><title>Thông tư 39/2016/TT-NHNN</title>
<style>@font-face{font-family:x}</style></head>
<body>
<script>gtag('config')</script>
<p>Điều 1. Phạm vi điều chỉnh</p>
<p>Thông tư này quy định về hoạt động cho vay của tổ chức tín dụng.</p>
<p>Điều 2. Đối tượng áp dụng</p>
<p>Tổ chức tín dụng và khách hàng vay.</p>
</body></html>"""


TVPL_TT39 = (
    "https://m.thuvienphapluat.vn/van-ban/Tien-te-Ngan-hang/"
    "Thong-tu-39-2016-TT-NHNN-hoat-dong-cho-vay-cua-to-chuc-tin-dung-"
    "chi-nhanh-ngan-hang-nuoc-ngoai-338877.aspx"
)


class _Resp:
    def __init__(
        self,
        content: bytes,
        content_type: str,
        url: str,
        status: int = 200,
        headers: dict | None = None,
    ):
        self.content = content
        self.text = content.decode("utf-8", errors="replace")
        self.headers = {"content-type": content_type, **(headers or {})}
        self.url = url
        self.status_code = status
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("http error")


def test_html_to_text_keeps_dieu_and_drops_script():
    text = html_to_text(HTML)
    assert "gtag" not in text
    assert "font-face" not in text
    assert "Điều 1. Phạm vi điều chỉnh" in text
    assert "Điều 2. Đối tượng áp dụng" in text


def test_fetch_html_page(monkeypatch):
    def fake_get(url, **_k):
        return _Resp(HTML.encode(), "text/html; charset=utf-8", url)

    monkeypatch.setattr("ingestion.fetch_url.httpx.get", fake_get)
    fetched = fetch_law_document("https://vbpl.vn/toanvan/tt39.html")
    assert fetched.suffix == ".txt"
    assert "Điều 1." in (fetched.raw_text or "")
    assert fetched.title.startswith("Thông tư 39")


def test_fetch_pdf_bytes(monkeypatch):
    body = b"%PDF-1.1 fake"

    def fake_get(url, **_k):
        return _Resp(body, "application/pdf", url)

    monkeypatch.setattr("ingestion.fetch_url.httpx.get", fake_get)
    fetched = fetch_law_document("https://vbpl.vn/files/tt39.pdf")
    assert fetched.suffix == ".pdf"
    assert fetched.content.startswith(b"%PDF")


def test_allows_thuvienphapluat_mobile(monkeypatch):
    def fake_get(url, **_k):
        return _Resp(HTML.encode(), "text/html", url)

    monkeypatch.setattr("ingestion.fetch_url.httpx.get", fake_get)
    fetched = fetch_law_document(TVPL_TT39)
    assert fetched.suffix == ".txt"
    assert "Điều 1." in (fetched.raw_text or "")


def test_tvpl_cloudflare_falls_back_to_wayback(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **_k):
        calls.append(url)
        if "web.archive.org" in url:
            return _Resp(HTML.encode(), "text/html", url)
        return _Resp(
            b"<!DOCTYPE html><title>Just a moment...</title>cloudflare",
            "text/html",
            url,
            status=403,
            headers={"cf-mitigated": "challenge"},
        )

    monkeypatch.setattr("ingestion.fetch_url.httpx.get", fake_get)
    fetched = fetch_law_document(TVPL_TT39)
    assert "Điều 1." in (fetched.raw_text or "")
    assert any("web.archive.org" in u for u in calls)


def test_rejects_non_http():
    with pytest.raises(FetchUrlError):
        fetch_law_document("javascript:alert(1)")


def test_process_url_chunks_html(tmp_path: Path, monkeypatch):
    def fake_get(url, **_k):
        return _Resp(HTML.encode(), "text/html", url)

    monkeypatch.setattr("ingestion.fetch_url.httpx.get", fake_get)
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    result = process_url(
        "https://vbpl.vn/nganhangnhanuoc/tt39.aspx",
        META,
        raw,
        processed,
    )
    assert result["ok"] is True
    assert result["chunks"] == 2
    assert (raw / "tt39.txt").exists() or list(raw.glob("*.txt"))
