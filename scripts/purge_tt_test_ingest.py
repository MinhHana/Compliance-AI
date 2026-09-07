#!/usr/bin/env python3
"""One-off: drop stub Thông tư 39 / tt_test ingest; keep production SOP."""
from __future__ import annotations

from pathlib import Path

from vectordb.embed_and_store import ROOT, collection, delete_by_source_doc, list_documents

STUB_SOURCE = "Thông tư 39/2016/TT-NHNN"
FILES = [
    ROOT / "data" / "raw_docs" / "tt_test.docx",
    ROOT / "data" / "raw_docs" / "tt_test.docx.meta.json",
    ROOT / "data" / "processed" / "tt_test.json",
]


def _delete_tt_test_leftovers() -> int:
    col = collection()
    if col.count() == 0:
        return 0
    raw = col.get(include=["metadatas"])
    ids = []
    for i, cid in enumerate(raw.get("ids") or []):
        meta = (raw.get("metadatas") or [{}])[i] or {}
        blob = f"{meta.get('source_doc') or ''} {meta.get('file_name_goc') or ''}".lower()
        if "tt_test" in blob:
            ids.append(cid)
    if ids:
        col.delete(ids=ids)
    return len(ids)


def main() -> None:
    n = delete_by_source_doc(STUB_SOURCE)
    extra = _delete_tt_test_leftovers()
    print(f"deleted {n} chroma chunks for {STUB_SOURCE}, {extra} tt_test leftovers")
    for path in FILES:
        if path.exists():
            path.unlink()
            print(f"removed {path.relative_to(ROOT)}")
        else:
            print(f"missing {path.relative_to(ROOT)}")
    print("library", list_documents())


if __name__ == "__main__":
    main()
