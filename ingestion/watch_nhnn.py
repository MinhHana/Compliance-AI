"""Kiểm tra nguồn Chính phủ/NHNN. Không crawl thuvienphapluat.vn."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("watch_nhnn")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "audit.db"
URLS_FILE = ROOT / "config" / "watch_urls.txt"
BLOCKED_HOSTS = {"thuvienphapluat.vn", "www.thuvienphapluat.vn"}
HREF_RE = re.compile(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
DEGREE_RE = re.compile(r"[°º℃℉]")
JUNK_TITLE_MARKERS = (
    "datalayer",
    "function",
    "font-face",
    "document.ready",
    "gtag",
    "mobile.detect",
)
SO_HIEU_RE = re.compile(r"\d+[/\-]\d{4}[/\-][A-ZĐ]+(?:[/\-][A-ZĐ]+)*", re.I)
LOAI_PATTERNS = (
    (re.compile(r"thông\s*tư", re.I), "thong_tu"),
    (re.compile(r"nghị\s*định", re.I), "nghi_dinh"),
    (re.compile(r"quyết\s*định", re.I), "quyet_dinh"),
    (re.compile(r"\bluật\b", re.I), "luat"),
)
LOAI_FROM_SO_HIEU = (
    (re.compile(r"TT", re.I), "thong_tu"),
    (re.compile(r"N[ĐD]", re.I), "nghi_dinh"),
    (re.compile(r"Q[ĐD]", re.I), "quyet_dinh"),
    (re.compile(r"QH", re.I), "luat"),
)
WATCH_EXTRA_COLS = ("loai_van_ban_doan", "so_hieu", "tom_tat")

DEFAULT_URLS = [
    "https://vbpl.vn/nganhangnhanuoc/Pages/Home.aspx",
]

KEEP_KEYWORDS = (
    "thông tư",
    "nghị định",
    "luật",
    "quyết định",
    "chỉ thị",
    "công văn",
    "dự thảo",
    "lấy ý kiến",
    "vbqppl",
    "tt-nhnn",
    "nd-cp",
    "nđ-cp",
    "qh",
    "sop",
    "quy chế",
    "quy trình",
)
DENY_SUBSTRINGS = (
    "trang chủ",
    "giới thiệu",
    "liên hệ",
    "đăng nhập",
    "tìm kiếm",
    "doanh nghiệp",
    "báo điện tử",
    "thư điện tử",
    "nước chxhcn",
    "chính phủ",
)
MENU_EXACT = "văn bản quy phạm pháp luật"


def parse_doc_ref(title: str) -> dict:
    """Nhận diện loại văn bản + số hiệu từ tiêu đề. Không nhận diện được thì None, không crash."""
    text = title or ""
    so_hieu = None
    m = SO_HIEU_RE.search(text)
    if m:
        so_hieu = m.group(0)
    loai = None
    for pat, value in LOAI_PATTERNS:
        if pat.search(text):
            loai = value
            break
    if loai is None and so_hieu:
        for pat, value in LOAI_FROM_SO_HIEU:
            if pat.search(so_hieu):
                loai = value
                break
    return {"loai_van_ban_doan": loai, "so_hieu": so_hieu}


def _ensure_watch_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS watch_items (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            first_seen TEXT NOT NULL
        )
        """
    )
    for col in WATCH_EXTRA_COLS:
        try:
            conn.execute(f"ALTER TABLE watch_items ADD COLUMN {col} TEXT")
        except sqlite3.OperationalError:
            pass
    conn.commit()


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _ensure_watch_schema(conn)
    return conn


def load_urls() -> list[str]:
    if URLS_FILE.exists():
        urls = []
        for line in URLS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
        return urls or DEFAULT_URLS
    return DEFAULT_URLS


def _host_ok(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host.lower() not in BLOCKED_HOSTS


def _clean(html: str) -> str:
    html = SCRIPT_STYLE_RE.sub("", html or "")
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


def is_junk_title(title: str) -> bool:
    text = title or ""
    lowered = text.lower()
    if any(marker in lowered for marker in JUNK_TITLE_MARKERS):
        return True
    return bool(DEGREE_RE.search(text))


def is_compliance_doc(title: str, url: str = "") -> bool:
    """Keep banking-compliance docs only. url is unused; kept for the Watch API filter."""
    del url
    text = title or ""
    lowered = text.lower()
    if is_junk_title(text):
        return False
    if lowered.strip() == MENU_EXACT:
        return False
    if any(deny in lowered for deny in DENY_SUBSTRINGS):
        return False
    ref = parse_doc_ref(text)
    so_hieu = ref.get("so_hieu")
    if len(text) < 20 and not so_hieu:
        return False
    if ref.get("loai_van_ban_doan") or so_hieu:
        return True
    return any(kw in lowered for kw in KEEP_KEYWORDS)


def fetch_links(url: str) -> list[tuple[str, str]]:
    if not _host_ok(url):
        logger.warning("Bỏ qua nguồn bị cấm: %s", url)
        return []
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Không tải được %s: %s", url, exc)
        return []
    found = []
    for href, inner in HREF_RE.findall(resp.text):
        title = _clean(inner)
        full = urljoin(url, href)
        if not _host_ok(full):
            continue
        if not is_compliance_doc(title, full):
            continue
        found.append((full, title[:300]))
    return found


def run() -> list[dict]:
    conn = _db()
    new_items: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for source in load_urls():
        for link, title in fetch_links(source):
            item_id = hashlib.sha256(f"{link}|{title}".encode()).hexdigest()[:32]
            exists = conn.execute(
                "SELECT 1 FROM watch_items WHERE id = ?", (item_id,)
            ).fetchone()
            if exists:
                continue
            ref = parse_doc_ref(title)
            conn.execute(
                """
                INSERT INTO watch_items
                    (id, url, title, source, first_seen, loai_van_ban_doan, so_hieu)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    item_id,
                    link,
                    title,
                    source,
                    now,
                    ref["loai_van_ban_doan"],
                    ref["so_hieu"],
                ),
            )
            new_items.append(
                {
                    "id": item_id,
                    "url": link,
                    "title": title,
                    "source": source,
                    "loai_van_ban_doan": ref["loai_van_ban_doan"],
                    "so_hieu": ref["so_hieu"],
                }
            )
    conn.commit()
    conn.close()
    logger.info("Phát hiện %s văn bản mới", len(new_items))
    return new_items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    items = run()
    if not items:
        print("Không có văn bản mới.")
    for item in items:
        print(f"- {item['title']}\n  {item['url']}")
