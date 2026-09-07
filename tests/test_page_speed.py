from __future__ import annotations

import threading
import time
from pathlib import Path

from ingestion.fetch_url import TIMEOUT, WAYBACK_TIMEOUT
from vectordb import embed_and_store as es


def _chunk(chunk_id: str, source_doc: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "noi_dung": "nội dung " + chunk_id,
        "source_doc": source_doc,
        "loai_van_ban": "thong_tu",
        "ngay_hieu_luc": "2017-03-15",
        "trang_thai": "con_hieu_luc",
    }


def test_fetch_timeouts_are_short():
    assert TIMEOUT <= 12
    assert WAYBACK_TIMEOUT <= 10
    assert WAYBACK_TIMEOUT <= TIMEOUT


def test_count_does_not_load_embed_model(tmp_path: Path, monkeypatch):
    called: list[int] = []

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("không được load embedding")

    monkeypatch.setattr(es, "_embedding_function", boom)
    assert es.collection(tmp_path / "chroma").count() == 0
    assert called == []


def test_delete_by_source_doc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(es, "embed_texts", lambda texts: [[0.1] * 4 for _ in texts])
    chroma = tmp_path / "chroma"
    es.upsert_chunks(
        [_chunk("a", "TT1"), _chunk("b", "TT2")],
        chroma,
    )
    assert es.delete_by_source_doc("TT1", chroma) == 1
    left = es.collection(chroma).get()
    assert left.get("ids") == ["b"]


def test_start_ingest_returns_before_embed(tmp_path: Path, monkeypatch):
    from api import ingest_job as job

    gate = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(job, "_lock", threading.Lock())
    monkeypatch.setattr(job, "STATUS_PATH", tmp_path / "ingest_status.json")

    def slow_upsert(chunks, persist_dir=None):
        gate.set()
        release.wait(timeout=5)
        return len(chunks or [])

    monkeypatch.setattr(job, "upsert_chunks", slow_upsert)
    monkeypatch.setattr(job, "delete_by_source_doc", lambda *_a, **_k: 0)

    raw = tmp_path / "raw"
    raw.mkdir()
    dest = raw / "a.txt"
    dest.write_text(
        "Điều 1. Phạm vi\nÁp dụng cho tổ chức tín dụng.\n",
        encoding="utf-8",
    )
    meta = {
        "source_doc": "Thông tư test",
        "loai_van_ban": "thong_tu",
        "ngay_hieu_luc": "2017-03-15",
        "trang_thai": "con_hieu_luc",
        "van_ban_thay_the": None,
        "ngay_ban_hanh": "",
        "ly_do_ban_hanh": "",
        "co_quan_ban_hanh": "",
        "pending_file": "a.txt",
    }
    t0 = time.monotonic()
    started = job.start_ingest(
        dest=dest,
        url="",
        meta=meta,
        label="a.txt",
        raw_dir=raw,
        processed_dir=tmp_path / "processed",
    )
    elapsed = time.monotonic() - t0
    assert started is True
    assert elapsed < 1.0
    assert job.read_status().get("state") == "running"
    assert gate.wait(timeout=10)
    release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if job.read_status().get("state") == "ok":
            break
        time.sleep(0.05)
    assert job.read_status().get("state") == "ok"
    assert "chunk" in (job.read_status().get("message") or "")


def test_start_ingest_extracts_title_when_blank(tmp_path: Path, monkeypatch):
    from api import ingest_job as job

    monkeypatch.setattr(job, "_lock", threading.Lock())
    monkeypatch.setattr(job, "STATUS_PATH", tmp_path / "ingest_status.json")
    monkeypatch.setattr(job, "upsert_chunks", lambda chunks, persist_dir=None: len(chunks or []))
    monkeypatch.setattr(job, "delete_by_source_doc", lambda *_a, **_k: 0)
    captured = {}

    def fake_sidecar(dest, meta):
        captured["meta"] = dict(meta)

    monkeypatch.setattr(job, "_write_sidecar", fake_sidecar)

    raw = tmp_path / "raw"
    raw.mkdir()
    dest = raw / "x.txt"
    dest.write_text(
        "Thông tư 39/2016/TT-NHNN\nĐiều 1. Phạm vi\nÁp dụng cho tổ chức tín dụng.\n",
        encoding="utf-8",
    )
    meta = {
        "source_doc": "",
        "loai_van_ban": "",
        "ngay_hieu_luc": "",
        "trang_thai": "con_hieu_luc",
        "van_ban_thay_the": None,
        "ngay_ban_hanh": "",
        "ly_do_ban_hanh": "",
        "co_quan_ban_hanh": "",
        "pending_file": "x.txt",
    }
    assert job.start_ingest(
        dest=dest,
        url="",
        meta=meta,
        label="x.txt",
        raw_dir=raw,
        processed_dir=tmp_path / "processed",
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if job.read_status().get("state") in {"ok", "error"}:
            break
        time.sleep(0.05)
    assert job.read_status().get("state") == "ok"
    assert "39/2016/TT-NHNN" in (captured.get("meta") or {}).get("source_doc", "")
    assert captured["meta"]["loai_van_ban"] == "thong_tu"
