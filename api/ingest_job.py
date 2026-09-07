"""Nạp văn bản nền — form trả HTML ngay, không đợi embed."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from ingestion.batch import process_file
from ingestion.chunk_by_dieu import SourceMetadata
from ingestion.doc_attrs import (
    attr_warnings,
    extract_doc_attrs,
    extract_title,
    infer_loai,
    merge_attrs,
)
from ingestion.extract_text import extract_text
from ingestion.fetch_url import FetchUrlError, fetch_law_document, write_fetched
from vectordb.embed_and_store import delete_by_source_doc, upsert_chunks

logger = logging.getLogger("ingest_job")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_docs"
PROCESSED_DIR = ROOT / "data" / "processed"
STATUS_PATH = ROOT / "logs" / "ingest_status.json"

_lock = threading.Lock()


def read_status() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(payload: dict) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_PATH)


def is_running() -> bool:
    return read_status().get("state") == "running"


def take_page_status() -> dict:
    st = read_status()
    state = st.get("state")
    if state == "running":
        return {
            "message": st.get("message") or "Đang nạp văn bản…",
            "running": True,
            "warnings": [],
        }
    if state in {"ok", "error"} and not st.get("shown"):
        st["shown"] = True
        _write_status(st)
        if state == "ok":
            return {
                "message": st.get("message") or "",
                "warnings": st.get("warnings") or [],
            }
        return {"error": st.get("message") or "Ingest lỗi"}
    return {}


def start_ingest(
    *,
    dest: Path | None,
    url: str,
    meta: dict,
    label: str,
    raw_dir: Path = RAW_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> bool:
    if not _lock.acquire(blocking=False):
        return False
    _write_status(
        {
            "state": "running",
            "message": f"Đang nạp {label}…",
            "warnings": [],
            "shown": False,
        }
    )
    try:
        threading.Thread(
            target=_run,
            kwargs={
                "dest": dest,
                "url": url,
                "meta": dict(meta),
                "label": label,
                "raw_dir": raw_dir,
                "processed_dir": processed_dir,
            },
            daemon=True,
        ).start()
    except Exception:
        _lock.release()
        raise
    return True


def _write_sidecar(dest: Path, meta: dict) -> None:
    dest.with_suffix(dest.suffix + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run(
    *,
    dest: Path | None,
    url: str,
    meta: dict,
    label: str,
    raw_dir: Path,
    processed_dir: Path,
) -> None:
    try:
        fetched_title = ""
        if dest is None:
            fetched = fetch_law_document(url)
            dest = write_fetched(fetched, Path(raw_dir))
            fetched_title = fetched.title or ""
        extracted = extract_text(str(dest))
        if extracted.needs_ocr:
            _write_status(
                {
                    "state": "ok",
                    "message": (
                        f"{dest.name} là PDF scan — cần OCR thủ công, chưa đưa vào DB."
                    ),
                    "warnings": [],
                    "shown": False,
                }
            )
            return
        meta = merge_attrs(meta, extract_doc_attrs(extracted.raw_text))
        if not str(meta.get("source_doc") or "").strip():
            stem = dest.stem.replace("_", " ").replace("-", " ").strip()
            meta["source_doc"] = extract_title(
                extracted.raw_text, fallback=fetched_title or stem
            )
        if not str(meta.get("loai_van_ban") or "").strip():
            meta["loai_van_ban"] = infer_loai(
                meta.get("source_doc") or "", extracted.raw_text
            )
        if not str(meta.get("source_doc") or "").strip():
            _write_status(
                {
                    "state": "error",
                    "message": "Không trích được tiêu đề văn bản.",
                    "warnings": [],
                    "shown": False,
                }
            )
            return
        meta["pending_file"] = dest.name
        warnings = attr_warnings(meta)
        meta["attr_warnings"] = json.dumps(warnings, ensure_ascii=False)
        source = SourceMetadata.from_dict(meta)
        _write_sidecar(dest, meta)
        result = process_file(dest, source, processed_dir)
        if not result.get("ok"):
            _write_status(
                {
                    "state": "error",
                    "message": result.get("error") or "Ingest lỗi",
                    "warnings": [],
                    "shown": False,
                }
            )
            return
        if result.get("needs_ocr"):
            _write_status(
                {
                    "state": "ok",
                    "message": (
                        f"{label} là PDF scan — cần OCR thủ công, chưa đưa vào DB."
                    ),
                    "warnings": [],
                    "shown": False,
                }
            )
            return
        delete_by_source_doc(source.source_doc)
        n = upsert_chunks(result.get("chunk_dicts") or [])
        _write_status(
            {
                "state": "ok",
                "message": f"Đã nạp {label}: {n} chunk.",
                "warnings": warnings,
                "shown": False,
            }
        )
    except FetchUrlError as exc:
        _write_status(
            {
                "state": "error",
                "message": str(exc),
                "warnings": [],
                "shown": False,
            }
        )
    except Exception as exc:
        logger.exception("Ingest nền lỗi")
        _write_status(
            {
                "state": "error",
                "message": str(exc),
                "warnings": [],
                "shown": False,
            }
        )
    finally:
        _lock.release()
