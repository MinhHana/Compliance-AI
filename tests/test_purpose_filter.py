from __future__ import annotations

import sqlite3
from pathlib import Path

from api.audit import recent_watch
from ingestion.watch_nhnn import is_compliance_doc
from ingestion.watch_summary import summarize_new_items


def test_thong_tu_39_is_compliance():
    assert is_compliance_doc("Thông tư 39/2016/TT-NHNN", "https://example.test/tt")


def test_lai_chau_weather_dropped():
    assert not is_compliance_doc("Lai Châu 22°", "https://example.test/w")


def test_gioi_thieu_chinh_phu_dropped():
    assert not is_compliance_doc("Giới thiệu Chính phủ", "https://example.test/g")


def test_doanh_nghiep_dropped():
    assert not is_compliance_doc("Doanh nghiệp", "https://example.test/dn")


def test_recent_watch_hides_junk_still_in_sqlite(tmp_path: Path, monkeypatch):
    db = tmp_path / "audit.db"
    monkeypatch.setattr("api.audit.DB_PATH", db)
    from ingestion.watch_nhnn import _ensure_watch_schema

    conn = sqlite3.connect(db)
    _ensure_watch_schema(conn)
    now = "2026-09-07T00:00:00+00:00"
    conn.execute(
        "INSERT INTO watch_items (id, url, title, source, first_seen, tom_tat) "
        "VALUES (?,?,?,?,?,?)",
        ("junk", "https://x/a", "Giới thiệu Chính phủ", "https://x", now, "menu"),
    )
    conn.execute(
        "INSERT INTO watch_items (id, url, title, source, first_seen, tom_tat) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ok",
            "https://x/b",
            "Thông tư số 39/2016/TT-NHNN quy định về cho vay",
            "https://x",
            now,
            "Quy định cho vay",
        ),
    )
    conn.commit()
    conn.close()
    titles = [r["title"] for r in recent_watch()]
    assert titles == ["Thông tư số 39/2016/TT-NHNN quy định về cho vay"]


def test_tom_tat_gtag_not_shown_raw(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    class Resp:
        text = "window.dataLayer = window.dataLayer || []; gtag('js', new Date());"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "ingestion.watch_summary.httpx.get", lambda *_a, **_k: Resp()
    )
    items = summarize_new_items(
        [{"url": "https://example.test/vb", "title": "vb"}]
    )
    tom = items[0]["tom_tat"]
    assert "gtag" not in tom.lower()
    assert "datalayer" not in tom.lower()


def test_tom_tat_gtag_in_sqlite_not_shown_raw(tmp_path: Path, monkeypatch):
    db = tmp_path / "audit.db"
    monkeypatch.setattr("api.audit.DB_PATH", db)
    from ingestion.watch_nhnn import _ensure_watch_schema

    conn = sqlite3.connect(db)
    _ensure_watch_schema(conn)
    conn.execute(
        "INSERT INTO watch_items (id, url, title, source, first_seen, tom_tat) "
        "VALUES (?,?,?,?,?,?)",
        (
            "ok",
            "https://x/b",
            "Thông tư số 39/2016/TT-NHNN quy định về cho vay",
            "https://x",
            "2026-09-07T00:00:00+00:00",
            "gtag('config', 'G-XXXX')",
        ),
    )
    conn.commit()
    conn.close()
    rows = recent_watch()
    assert rows
    tom = rows[0]["tom_tat"] or ""
    assert "gtag" not in tom.lower()
