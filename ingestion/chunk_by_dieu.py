from __future__ import annotations

import json
import logging
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from ingestion.extract_text import ExtractedDocument

logger = logging.getLogger("ingestion")

DIEU_SPLIT = re.compile(r"(Điều\s+\d+\.)")
KHOAN_SPLIT = re.compile(r"(\d+\.\s)")
MAX_DIEU_CHARS = 1500
_PHU_LUC = re.compile(r"^\[?\s*PH[UỤ][\s-]*L[UỤ]C\b", re.I)
_NUMBERED_HEAD = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")
_CHUONG_MUC = re.compile(r"^(Chương|Mục)\s+\S", re.I)

LOAI_VAN_BAN = {"thong_tu", "nghi_dinh", "luat", "sop_noi_bo"}
TRANG_THAI = {"con_hieu_luc", "het_hieu_luc", "da_sua_doi"}


@dataclass
class SourceMetadata:
    source_doc: str
    loai_van_ban: str
    ngay_hieu_luc: str
    trang_thai: str
    van_ban_thay_the: str | None = None
    ngay_ban_hanh: str | None = None
    ly_do_ban_hanh: str | None = None
    co_quan_ban_hanh: str | None = None
    attr_warnings: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SourceMetadata:
        loai = data.get("loai_van_ban", "")
        trang = data.get("trang_thai", "") or ""
        if loai not in LOAI_VAN_BAN:
            raise ValueError(f"loai_van_ban không hợp lệ: {loai}")
        if trang and trang not in TRANG_THAI:
            raise ValueError(f"trang_thai không hợp lệ: {trang}")
        return cls(
            source_doc=str(data["source_doc"]),
            loai_van_ban=loai,
            ngay_hieu_luc=str(data.get("ngay_hieu_luc") or ""),
            trang_thai=trang,
            van_ban_thay_the=data.get("van_ban_thay_the") or None,
            ngay_ban_hanh=data.get("ngay_ban_hanh") or None,
            ly_do_ban_hanh=data.get("ly_do_ban_hanh") or None,
            co_quan_ban_hanh=data.get("co_quan_ban_hanh") or None,
            attr_warnings=data.get("attr_warnings") or None,
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
    ngay_ban_hanh: str | None = None
    ly_do_ban_hanh: str | None = None
    co_quan_ban_hanh: str | None = None
    attr_warnings: str | None = None

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
    Luật/thông tư: 1 chunk / Điều (tách Khoản nếu > 1500 ký tự).
    SOP / văn bản không có Điều: tách theo mục 1. 2. …, Chương/Mục, PHỤ LỤC;
    khối dài cắt theo dòng (giữ hàng bảng).
    """
    text = unicodedata.normalize("NFC", extracted_doc.raw_text or "").strip()
    if not text:
        return []

    parts = DIEU_SPLIT.split(text)
    dieu_blocks: list[tuple[str, str]] = []
    i = 1
    while i < len(parts) - 1:
        marker = parts[i]
        body = parts[i + 1]
        dieu_blocks.append((marker, body))
        i += 2

    if dieu_blocks:
        return _chunks_from_dieu(extracted_doc, source_metadata, dieu_blocks)

    sections = _split_sections(text)
    if sections:
        logger.info(
            "Tách %s theo mục/phụ lục: %s khối",
            extracted_doc.file_name,
            len(sections),
        )
        return _chunks_from_sections(extracted_doc, source_metadata, sections)

    logger.warning(
        "Không tách được theo Điều/mục — cắt theo độ dài %s",
        extracted_doc.file_name,
    )
    return _chunks_from_plain(extracted_doc, source_metadata, text, tieu_de=None)


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
        ngay_ban_hanh=meta.ngay_ban_hanh,
        ly_do_ban_hanh=meta.ly_do_ban_hanh,
        co_quan_ban_hanh=meta.co_quan_ban_hanh,
        attr_warnings=meta.attr_warnings,
    )


def _chunks_from_dieu(
    extracted_doc: ExtractedDocument,
    source_metadata: SourceMetadata,
    dieu_blocks: list[tuple[str, str]],
) -> list[Chunk]:
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


def _is_section_heading(line: str) -> bool:
    s = line.strip()
    if not s or " | " in s:
        return False
    if _PHU_LUC.match(s) or _CHUONG_MUC.match(s):
        return True
    if s.startswith("Điều "):
        return False
    m = _NUMBERED_HEAD.match(s)
    if not m or len(s) > 200:
        return False
    rest = m.group(2).lstrip()
    return bool(rest) and rest[0].isupper()


def _split_sections(text: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _is_section_heading(line)]
    if not starts:
        return []
    blocks: list[tuple[str, str]] = []
    if starts[0] > 0:
        pre = "\n".join(lines[: starts[0]]).strip()
        if pre:
            blocks.append(("Mở đầu", pre))
    for j, i in enumerate(starts):
        end = starts[j + 1] if j + 1 < len(starts) else len(lines)
        heading = lines[i].strip()
        body = "\n".join(lines[i:end]).strip()
        if body:
            blocks.append((heading, body))
    return _coalesce_short_phu_luc(blocks)


def _coalesce_short_phu_luc(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for heading, body in blocks:
        bare = _PHU_LUC.match(heading) and "[" not in heading and len(body) < 400
        if bare and out and _PHU_LUC.match(out[-1][0]) and "[" not in out[-1][0]:
            prev_h, prev_b = out[-1]
            out[-1] = (prev_h, f"{prev_b}\n{body}")
        else:
            out.append((heading, body))
    return out


def _chunks_from_sections(
    extracted_doc: ExtractedDocument,
    meta: SourceMetadata,
    sections: list[tuple[str, str]],
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in sections:
        title = heading[:200]
        if len(body) <= MAX_DIEU_CHARS:
            chunks.append(
                _make_chunk(
                    extracted_doc,
                    meta,
                    dieu=None,
                    tieu_de_dieu=title,
                    khoan=None,
                    noi_dung=body,
                )
            )
        else:
            chunks.extend(
                _chunks_from_plain(extracted_doc, meta, body, tieu_de=title)
            )
    return chunks


def _chunks_from_plain(
    extracted_doc: ExtractedDocument,
    meta: SourceMetadata,
    text: str,
    tieu_de: str | None,
) -> list[Chunk]:
    packed = list(_pack_lines(text, MAX_DIEU_CHARS))
    if not packed:
        return []
    if len(packed) == 1:
        return [
            _make_chunk(
                extracted_doc,
                meta,
                dieu=None,
                tieu_de_dieu=tieu_de,
                khoan=None,
                noi_dung=packed[0],
            )
        ]
    chunks = []
    for i, piece in enumerate(packed, start=1):
        chunks.append(
            _make_chunk(
                extracted_doc,
                meta,
                dieu=None,
                tieu_de_dieu=tieu_de,
                khoan=f"Phần {i}",
                noi_dung=piece,
            )
        )
    return chunks


def _pack_lines(text: str, max_chars: int) -> list[str]:
    buf: list[str] = []
    size = 0
    out: list[str] = []
    for line in text.splitlines():
        extra = len(line) + (1 if buf else 0)
        if buf and size + extra > max_chars:
            out.append("\n".join(buf))
            buf = [line]
            size = len(line)
        else:
            buf.append(line)
            size += extra
    if buf:
        out.append("\n".join(buf))
    return out


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
