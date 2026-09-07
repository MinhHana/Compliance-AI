from __future__ import annotations

import json
import logging
from pathlib import Path

from ingestion.chunk_by_dieu import (
    SourceMetadata,
    chunk_by_dieu,
    write_chunks_json,
)
from ingestion.extract_text import ExtractionError, extract_text
from ingestion.fetch_url import FetchUrlError, fetch_law_document, write_fetched

logger = logging.getLogger("ingestion")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_docs"
PROCESSED_DIR = ROOT / "data" / "processed"


def process_file(
    file_path: str | Path,
    source_metadata: SourceMetadata,
    processed_dir: str | Path = PROCESSED_DIR,
) -> dict:
    extracted = extract_text(str(file_path))
    if extracted.needs_ocr:
        logger.warning("needs_ocr=true: %s", extracted.file_name)
        return {
            "ok": True,
            "file": extracted.file_name,
            "needs_ocr": True,
            "chunks": 0,
            "output": None,
        }
    chunks = chunk_by_dieu(extracted, source_metadata)
    out = write_chunks_json(chunks, processed_dir, extracted.file_name)
    return {
        "ok": True,
        "file": extracted.file_name,
        "needs_ocr": False,
        "chunks": len(chunks),
        "output": str(out),
        "chunk_dicts": [c.to_dict() for c in chunks],
    }


def process_url(
    url: str,
    source_metadata: SourceMetadata,
    raw_dir: str | Path = RAW_DIR,
    processed_dir: str | Path = PROCESSED_DIR,
) -> dict:
    fetched = fetch_law_document(url)
    dest = write_fetched(fetched, Path(raw_dir))
    try:
        return process_file(dest, source_metadata, processed_dir)
    except ExtractionError as exc:
        raise FetchUrlError(str(exc)) from exc


def process_directory(
    raw_dir: str | Path = RAW_DIR,
    processed_dir: str | Path = PROCESSED_DIR,
) -> list[dict]:
    raw = Path(raw_dir)
    results: list[dict] = []
    files = sorted(
        p for p in raw.iterdir() if p.is_file() and p.suffix.lower() in {".pdf", ".docx"}
    )
    for path in files:
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        try:
            if not meta_path.exists():
                raise FileNotFoundError(f"Thiếu metadata: {meta_path.name}")
            with open(meta_path, encoding="utf-8") as fh:
                meta = SourceMetadata.from_dict(json.load(fh))
            results.append(process_file(path, meta, processed_dir))
        except (ExtractionError, FileNotFoundError, ValueError, OSError) as exc:
            logger.error("Lỗi file %s: %s", path.name, exc)
            results.append({"ok": False, "file": path.name, "error": str(exc)})
        except Exception as exc:
            logger.exception("Lỗi không mong đợi %s: %s", path.name, exc)
            results.append({"ok": False, "file": path.name, "error": str(exc)})
    return results
