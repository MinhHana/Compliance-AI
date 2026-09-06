from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from ingestion.extract_text import ExtractedDocument

logger = logging.getLogger("ingestion")

DIEU_SPLIT = re.compile(r"(Điều\s+\d+\.)")
KHOAN_SPLIT = re.compile(r"(\d+\.\s)")
MAX_DIEU_CHARS = 1500

LOAI_VAN_BAN = {"thong_tu", "nghi_dinh", "luat", "sop_noi_bo"}
TRANG_THAI = {"con_hieu_luc", "het_hieu_luc", "da_sua_doi"}


@dataclass
class SourceMetadata:
    source_doc: str
    loai_van_ban: str
    ngay_hieu_luc: str
    trang_thai: str
    van_ban_thay_the: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SourceMetadata:
        loai = data.get("loai_van_ban", "")
        trang = data.get("trang_thai", "")
        if loai not in LOAI_VAN_BAN:
            raise ValueError(f"loai_van_ban không hợp lệ: {loai}")
        if trang not in TRANG_THAI:
            raise ValueError(f"trang_thai không hợp lệ: {trang}")
        return cls(
            source_doc=str(data["source_doc"]),
            loai_van_ban=loai,
            ngay_hieu_luc=str(data["ngay_hieu_luc"]),
            trang_thai=trang,
            van_ban_thay_the=data.get("van_ban_thay_the"),
        )


@dataclass
class Chunk:
    chunk_id: str
    dieu: str | None
    tieu_de_dieu: str | None
    khoan: str | None
    noi_dung: str
    source_doc: str
    loai_van_ban: str
    ngay_hieu_luc: str
    trang_thai: str
    van_ban_thay_the: str | None
    file_name_goc: str
    canh_bao: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def load_source_metadata(path: str | Path) -> SourceMetadata:
    with open(path, encoding="utf-8") as fh:
        return SourceMetadata.from_dict(json.load(fh))


def chunk_by_dieu(
    extracted_doc: ExtractedDocument,
    source_metadata: SourceMetadata,
) -> list[Chunk]:
    """
    Input: ExtractedDocument (từ bước 1) + SourceMetadata (nhập tay hoặc từ config)
    Output: danh sách Chunk, mỗi Chunk = 1 Điều (hoặc 1 Khoản nếu Điều quá dài > 1500 ký tự)
    """
    text = extracted_doc.raw_text or ""
    parts = DIEU_SPLIT.split(text)
    dieu_blocks: list[tuple[str, str]] = []
    i = 1
    while i < len(parts) - 1:
        marker = parts[i]
        body = parts[i + 1]
        dieu_blocks.append((marker, body))
        i += 2

    if not dieu_blocks:
        logger.warning(
            "Không tách được theo Điều — 1 chunk cho cả file %s",
            extracted_doc.file_name,
        )
        return [
            _make_chunk(
                extracted_doc,
                source_metadata,
                dieu=None,
                tieu_de_dieu=None,
                khoan=None,
                noi_dung=text.strip(),
            )
        ]

    numbers = [_dieu_num(m) for m, _ in dieu_blocks]
    discontinuous = _is_discontinuous(numbers)
    warning = (
        "số Điều không liên tục, cần kiểm tra thủ công" if discontinuous else None
    )

    chunks: list[Chunk] = []
    for marker, body in dieu_blocks:
        full = f"{marker}{body}".strip()
        tieu_de = _tieu_de(marker, body)
        if len(full) > MAX_DIEU_CHARS:
            chunks.extend(
                _split_khoan(
                    extracted_doc,
                    source_metadata,
                    marker,
                    tieu_de,
                    full,
                    warning,
                )
            )
        else:
            chunks.append(
                _make_chunk(
                    extracted_doc,
                    source_metadata,
                    dieu=marker.rstrip("."),
                    tieu_de_dieu=tieu_de,
                    khoan=None,
                    noi_dung=full,
                    canh_bao=warning,
                )
            )
    return chunks


def write_chunks_json(chunks: list[Chunk], processed_dir: str | Path, file_name: str) -> Path:
    out_dir = Path(processed_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{Path(file_name).stem}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump([c.to_dict() for c in chunks], fh, ensure_ascii=False, indent=2)
    return out


def _make_chunk(
    extracted_doc: ExtractedDocument,
    meta: SourceMetadata,
    *,
    dieu: str | None,
    tieu_de_dieu: str | None,
    khoan: str | None,
    noi_dung: str,
    canh_bao: str | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=str(uuid.uuid4()),
        dieu=dieu,
        tieu_de_dieu=tieu_de_dieu,
        khoan=khoan,
        noi_dung=noi_dung,
        source_doc=meta.source_doc,
        loai_van_ban=meta.loai_van_ban,
        ngay_hieu_luc=meta.ngay_hieu_luc,
        trang_thai=meta.trang_thai,
        van_ban_thay_the=meta.van_ban_thay_the,
        file_name_goc=extracted_doc.file_name,
        canh_bao=canh_bao,
    )


def _tieu_de(marker: str, body: str) -> str:
    first = body.strip().split("\n", 1)[0].strip()
    if first:
        return f"{marker} {first}".strip()
    return marker.strip()


def _dieu_num(marker: str) -> int | None:
    m = re.search(r"(\d+)", marker)
    return int(m.group(1)) if m else None


def _is_discontinuous(numbers: list[int | None]) -> bool:
    vals = [n for n in numbers if n is not None]
    if len(vals) < 2:
        return False
    expected = list(range(vals[0], vals[0] + len(vals)))
    return vals != expected


def _split_khoan(
    extracted_doc: ExtractedDocument,
    meta: SourceMetadata,
    marker: str,
    tieu_de: str,
    full: str,
    warning: str | None,
) -> list[Chunk]:
    parts = KHOAN_SPLIT.split(full)
    khoan_blocks: list[tuple[str, str]] = []
    i = 1
    while i < len(parts) - 1:
        num = parts[i]
        body = parts[i + 1]
        khoan_blocks.append((num.strip(), body))
        i += 2
    if len(khoan_blocks) < 2:
        return [
            _make_chunk(
                extracted_doc,
                meta,
                dieu=marker.rstrip("."),
                tieu_de_dieu=tieu_de,
                khoan=None,
                noi_dung=full,
                canh_bao=warning,
            )
        ]
    chunks = []
    preamble = parts[0].strip()
    for idx, (num, body) in enumerate(khoan_blocks):
        content = f"{num} {body}".strip()
        if idx == 0 and preamble:
            content = f"{preamble}\n{content}"
        chunks.append(
            _make_chunk(
                extracted_doc,
                meta,
                dieu=marker.rstrip("."),
                tieu_de_dieu=tieu_de,
                khoan=f"Khoản {num.rstrip('.')}",
                noi_dung=content,
                canh_bao=warning,
            )
        )
    return chunks
