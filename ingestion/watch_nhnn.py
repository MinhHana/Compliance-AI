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

DEFAULT_URLS = [
    "https://vanban.chinhphu.vn/",
    "https://www.sbv.gov.vn/",
]


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
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
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


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
        if len(title) < 12:
            continue
        full = urljoin(url, href)
        if not _host_ok(full):
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
            conn.execute(
                "INSERT INTO watch_items (id, url, title, source, first_seen) VALUES (?,?,?,?,?)",
                (item_id, link, title, source, now),
            )
            new_items.append(
                {"id": item_id, "url": link, "title": title, "source": source}
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
