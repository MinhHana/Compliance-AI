"""Tải văn bản luật từ URL (PDF / Word / HTML).

Watch không crawl thuvienphapluat.vn; form dán link thì cho phép
(m./www.thuvienphapluat.vn). Cloudflare → bản lưu web.archive.org.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urlparse, unquote, urlunparse

import httpx

from ingestion.watch_nhnn import SCRIPT_STYLE_RE, TAG_RE

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,*/*"
    ),
}
MAX_BYTES = 20 * 1024 * 1024
TIMEOUT = 12
WAYBACK_TIMEOUT = 10
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
BR_RE = re.compile(r"(?i)<br\s*/?>")
BLOCK_CLOSE_RE = re.compile(r"(?i)</(p|div|tr|h[1-6]|li|table|section|article|br)>")


class FetchUrlError(ValueError):
    pass


@dataclass
class FetchedDocument:
    url: str
    title: str
    suffix: str
    content: bytes
    raw_text: str | None = None


def html_to_text(html: str) -> str:
    html = SCRIPT_STYLE_RE.sub("", html or "")
    html = BR_RE.sub("\n", html)
    html = BLOCK_CLOSE_RE.sub("\n", html)
    text = unescape(TAG_RE.sub("", html))
    text = unicodedata.normalize("NFC", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _title_from_html(html: str) -> str:
    m = TITLE_RE.search(html or "")
    if not m:
        return ""
    return re.sub(r"\s+", " ", unescape(TAG_RE.sub("", m.group(1)))).strip()[:300]


def _normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise FetchUrlError("Thiếu đường link văn bản.")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FetchUrlError("Link phải bắt đầu bằng http:// hoặc https://.")
    return raw


def is_thuvienphapluat(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "thuvienphapluat.vn" or host.endswith(".thuvienphapluat.vn")


def _canonical_tvpl(url: str) -> str:
    parsed = urlparse(url)
    if not is_thuvienphapluat(url):
        return url
    path = parsed.path or "/"
    return urlunparse(("https", "thuvienphapluat.vn", path, "", parsed.query, ""))


def _wayback_url(url: str) -> str:
    return "https://web.archive.org/web/" + _canonical_tvpl(url)


def _is_cf_challenge(resp: httpx.Response) -> bool:
    if resp.headers.get("cf-mitigated"):
        return True
    head = (resp.content or b"")[:4000].lower()
    if resp.status_code in {403, 503} and b"cloudflare" in head:
        return True
    return b"just a moment" in head and b"cloudflare" in head


def _suffix_from_headers(url: str, content_type: str, body: bytes) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    path = unquote(urlparse(url).path).lower()
    if body.startswith(b"%PDF") or ctype == "application/pdf" or path.endswith(".pdf"):
        return ".pdf"
    if (
        ctype
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or path.endswith(".docx")
    ):
        return ".docx"
    if ctype in {"text/html", "application/xhtml+xml"} or body.lstrip()[:32].lower().startswith(
        (b"<!doctype", b"<html", b"<head", b"<?xml")
    ):
        return ".txt"
    if path.endswith(".htm") or path.endswith(".html") or path.endswith(".aspx"):
        return ".txt"
    raise FetchUrlError("Link không phải PDF, Word (.docx) hoặc trang HTML văn bản.")


def _safe_stem(url: str, title: str) -> str:
    stem = Path(unquote(urlparse(url).path)).stem
    if not stem or stem.lower() in {"index", "default", "home", "pages"}:
        stem = re.sub(r"[^\w\-]+", "_", title, flags=re.UNICODE).strip("_")[:60]
    if not stem:
        stem = hashlib.sha256(url.encode()).hexdigest()[:16]
    return stem


def _http_get(url: str, timeout: float = TIMEOUT) -> httpx.Response:
    return httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers=HEADERS,
    )


def fetch_law_document(url: str) -> FetchedDocument:
    target = _normalize_url(url)
    resp: httpx.Response | None = None
    err: Exception | None = None
    try:
        resp = _http_get(target)
    except httpx.HTTPError as exc:
        err = exc
    if is_thuvienphapluat(target) and (resp is None or _is_cf_challenge(resp)):
        try:
            resp = _http_get(_wayback_url(target), timeout=WAYBACK_TIMEOUT)
            err = None
        except httpx.HTTPError as exc:
            err = exc
    if resp is None:
        raise FetchUrlError(f"Không tải được link: {err}") from err
    try:
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise FetchUrlError(f"Không tải được link: {exc}") from exc
    if _is_cf_challenge(resp):
        raise FetchUrlError(
            "Thư viện Pháp luật chặn tải tự động. Tải file PDF từ trang rồi nạp file."
        )
    final = str(resp.url)
    body = resp.content or b""
    if len(body) > MAX_BYTES:
        raise FetchUrlError("File quá lớn (tối đa 20MB).")
    if not body.strip():
        raise FetchUrlError("Link không có nội dung.")
    suffix = _suffix_from_headers(final, resp.headers.get("content-type") or "", body)
    title = ""
    raw_text = None
    if suffix == ".txt":
        encoding = resp.encoding or "utf-8"
        try:
            html = body.decode(encoding, errors="replace")
        except LookupError:
            html = body.decode("utf-8", errors="replace")
        title = _title_from_html(html)
        raw_text = html_to_text(html)
        if len(raw_text) < 40:
            raise FetchUrlError("Không lấy được nội dung văn bản từ trang.")
        body = raw_text.encode("utf-8")
    return FetchedDocument(
        url=final,
        title=title,
        suffix=suffix,
        content=body,
        raw_text=raw_text,
    )


def write_fetched(fetched: FetchedDocument, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{_safe_stem(fetched.url, fetched.title)}{fetched.suffix}"
    dest.write_bytes(fetched.content)
    return dest
