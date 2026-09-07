"""Hiệu lực, ngày ban hành, bối cảnh — lấy từ văn bản; thiếu thì người dùng nhập."""

from __future__ import annotations

import re
from datetime import date

_NUM_DATE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_VN_DATE = re.compile(
    r"(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.I,
)
_BAN_HANH_NUM = re.compile(
    r"(?:ngày\s+)?ban\s+hành\s*[:\-]?\s*(?:ngày\s*)?(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})",
    re.I,
)
_HIEU_LUC_NUM = re.compile(
    r"ngày\s+hiệu\s+lực\s*[:\-]?\s*(?:ngày\s*)?(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})",
    re.I,
)
_HIEU_LUC_TU = re.compile(
    r"có\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+từ\s+ngày\s+"
    r"(\d{1,2}\s+tháng\s+\d{1,2}\s+năm\s+\d{4}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})",
    re.I,
)
_HEADER_DATE = re.compile(
    r"(?:Hà\s+Nội|TP\.?\s*Hồ\s+Chí\s+Minh).{0,40}"
    r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.I,
)
_TINH_TRANG = re.compile(
    r"tình\s+trạng(?:\s+hiệu\s+lực)?\s*[:\-]\s*([^\n]{3,80})",
    re.I,
)
_LY_DO_LABEL = re.compile(
    r"(?:lý\s+do|bối\s+cảnh)\s*(?:ban\s+hành)?\s*[:\-]\s*(.+?)(?:\n\n|Điều\s+1\.)",
    re.I | re.S,
)
_CAN_CU_LINE = re.compile(r"^(Căn cứ|Theo đề nghị)\b", re.I)
_CO_QUAN_LABEL = re.compile(
    r"cơ\s+quan\s+ban\s+hành\s*[:\-]\s*([^\n]{3,120})",
    re.I,
)
_CO_QUAN_KNOWN = (
    (re.compile(r"Ngân hàng Nhà nước(?: Việt Nam)?", re.I), "Ngân hàng Nhà nước Việt Nam"),
    (re.compile(r"Quốc hội", re.I), "Quốc hội"),
    (re.compile(r"Chính phủ", re.I), "Chính phủ"),
    (re.compile(r"Bộ Tài chính", re.I), "Bộ Tài chính"),
    (re.compile(r"Bộ Công an", re.I), "Bộ Công an"),
)
_LOAI_OK = {"thong_tu", "nghi_dinh", "luat", "sop_noi_bo"}
_SOP_MARK = re.compile(
    r"sop|quy\s*chế|quy\s*trình|bảng phân chia|thẩm quyền|hướng dẫn nội bộ",
    re.I,
)
_LOAI_HEAD = re.compile(
    r"^(thông\s*tư|nghị\s*định|luật|quyết\s*định|chỉ\s*thị|công\s*văn|"
    r"quy\s*chế|quy\s*trình)\b",
    re.I,
)
_SKIP_TITLE_LINE = re.compile(
    r"^(cộng\s+hòa|xã\s+hội\s+chủ\s+nghĩa|độc\s+lập|hà\s+nội[, ]|tp\.|"
    r"căn cứ|theo đề nghị|nơi nhận|điều\s+\d|chương\s+|mục\s+|phần\s+\d|"
    r"tình trạng|ngày\s+ban\s+hành|ngày\s+hiệu\s+lực|kính gửi)",
    re.I,
)
_SITE_TAIL = re.compile(
    r"\s*[\|\-–—]\s*(thư viện pháp luật|vbpl(?:\.vn)?|cổng thông tin).*$",
    re.I,
)


def _iso(day: str | int, month: str | int, year: str | int) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _parse_date_token(token: str) -> str | None:
    token = (token or "").strip()
    m = _VN_DATE.search(token)
    if m:
        return _iso(m.group(1), m.group(2), m.group(3))
    m = _NUM_DATE.search(token)
    if m:
        return _iso(m.group(1), m.group(2), m.group(3))
    return None


def _trang_thai(blob: str) -> str | None:
    t = (blob or "").lower()
    if "hết hiệu lực một phần" in t or "sửa đổi" in t or "bổ sung" in t:
        return "da_sua_doi"
    if "hết hiệu lực" in t or "không còn hiệu lực" in t:
        return "het_hieu_luc"
    if "còn hiệu lực" in t:
        return "con_hieu_luc"
    return None


def _ly_do(text: str) -> str:
    m = _LY_DO_LABEL.search(text or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:1500]
    pre = (text or "").split("Điều 1.")[0]
    lines = [ln.strip() for ln in pre.splitlines() if ln.strip()]
    block: list[str] = []
    started = False
    for ln in lines:
        if _CAN_CU_LINE.match(ln):
            started = True
            block.append(ln)
            continue
        if started:
            if re.match(r"^(Chương|Phần|Mục)\b", ln, re.I):
                break
            block.append(ln)
            if "ban hành" in ln.lower() and ln.endswith((".", ";")):
                break
    if not block:
        return ""
    return re.sub(r"\s+", " ", " ".join(block)).strip()[:1500]


def _co_quan(text: str) -> str:
    raw = text or ""
    m = _CO_QUAN_LABEL.search(raw)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:120]
    pre = raw.split("Điều 1.")[0][:2500]
    if re.search(r"Thống đốc Ngân hàng Nhà nước", pre, re.I):
        return "Ngân hàng Nhà nước Việt Nam"
    for pat, name in _CO_QUAN_KNOWN:
        if pat.search(pre):
            return name
    return ""


def _clean_title(s: str) -> str:
    s = _SITE_TAIL.sub("", s or "")
    return re.sub(r"\s+", " ", s).strip(" .")[:300]


def extract_title(text: str, fallback: str = "") -> str:
    from ingestion.watch_nhnn import parse_doc_ref

    fb = _clean_title(fallback)
    if fb and parse_doc_ref(fb).get("so_hieu"):
        return fb
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    for i, ln in enumerate(lines[:80]):
        if _SKIP_TITLE_LINE.match(ln):
            continue
        ref = parse_doc_ref(ln)
        if _LOAI_HEAD.match(ln):
            parts = [ln]
            if not ref.get("so_hieu"):
                for nxt in lines[i + 1 : i + 6]:
                    if _SKIP_TITLE_LINE.match(nxt):
                        continue
                    parts.append(nxt)
                    if parse_doc_ref(" ".join(parts)).get("so_hieu"):
                        break
            extra = ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and re.match(r"^(quy định|hướng dẫn)\b", nxt, re.I):
                extra = " " + nxt
            title = _clean_title(" ".join(parts) + extra)
            if title:
                return title
        if ref.get("so_hieu"):
            extra = ""
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if nxt and re.match(r"^(quy định|hướng dẫn)\b", nxt, re.I):
                extra = " " + nxt
            return _clean_title(ln + extra)
    if len(fb) >= 12:
        return fb
    for ln in lines[:40]:
        if _SKIP_TITLE_LINE.match(ln) or len(ln) < 12 or ln.lower().startswith("điều "):
            continue
        return _clean_title(ln)
    return fb


def infer_loai(title: str, text: str = "") -> str:
    from ingestion.watch_nhnn import parse_doc_ref

    blob = f"{title or ''}\n{(text or '')[:2500]}"
    loai = parse_doc_ref(title or "").get("loai_van_ban_doan") or parse_doc_ref(
        blob
    ).get("loai_van_ban_doan")
    if loai in _LOAI_OK:
        return loai
    if _SOP_MARK.search(blob):
        return "sop_noi_bo"
    if loai:
        return "thong_tu"
    return "sop_noi_bo"


def extract_doc_attrs(text: str) -> dict:
    raw = text or ""
    ngay_ban_hanh = None
    m = _BAN_HANH_NUM.search(raw)
    if m:
        ngay_ban_hanh = _parse_date_token(m.group(1))
    if not ngay_ban_hanh:
        m = _HEADER_DATE.search(raw)
        if m:
            ngay_ban_hanh = _iso(m.group(1), m.group(2), m.group(3))

    ngay_hieu_luc = None
    m = _HIEU_LUC_NUM.search(raw)
    if m:
        ngay_hieu_luc = _parse_date_token(m.group(1))
    if not ngay_hieu_luc:
        m = _HIEU_LUC_TU.search(raw)
        if m:
            ngay_hieu_luc = _parse_date_token(m.group(1))

    trang_thai = None
    m = _TINH_TRANG.search(raw)
    if m:
        trang_thai = _trang_thai(m.group(1))
    if not trang_thai:
        head = raw[:4000]
        if re.search(r"tình\s+trạng.{0,40}còn hiệu lực", head, re.I | re.S):
            trang_thai = "con_hieu_luc"
        elif re.search(r"tình\s+trạng.{0,40}hết hiệu lực", head, re.I | re.S):
            trang_thai = "het_hieu_luc"

    return {
        "ngay_ban_hanh": ngay_ban_hanh or "",
        "ngay_hieu_luc": ngay_hieu_luc or "",
        "trang_thai": trang_thai or "",
        "ly_do_ban_hanh": _ly_do(raw),
        "co_quan_ban_hanh": _co_quan(raw),
    }


def merge_attrs(user: dict, extracted: dict) -> dict:
    out = dict(user)
    for key in (
        "ngay_ban_hanh",
        "ngay_hieu_luc",
        "trang_thai",
        "ly_do_ban_hanh",
        "co_quan_ban_hanh",
    ):
        if not str(out.get(key) or "").strip():
            val = extracted.get(key) or ""
            if val:
                out[key] = val
    return out


def _filled(meta: dict, key: str) -> bool:
    return bool(str(meta.get(key) or "").strip())


def attr_warnings(meta: dict) -> list[dict]:
    """Đỏ = thiếu hiệu lực; vàng = thiếu ngày ban hành; xám = còn lại. Không chặn nạp."""
    warnings: list[dict] = []
    if not _filled(meta, "trang_thai") or not _filled(meta, "ngay_hieu_luc"):
        warnings.append(
            {
                "level": "red",
                "text": (
                    "Thiếu thuộc tính hiệu lực (trạng thái hoặc ngày hiệu lực). "
                    "Vẫn nạp — bổ sung khi có."
                ),
            }
        )
    if not _filled(meta, "ngay_ban_hanh"):
        warnings.append(
            {
                "level": "yellow",
                "text": "Thiếu ngày ban hành. Vẫn nạp — bổ sung khi có.",
            }
        )
    ban, hieu = meta.get("ngay_ban_hanh") or "", meta.get("ngay_hieu_luc") or ""
    if ban and hieu and hieu < ban:
        warnings.append(
            {
                "level": "yellow",
                "text": "Ngày hiệu lực trước ngày ban hành — kiểm tra lại.",
            }
        )
    if not _filled(meta, "ly_do_ban_hanh"):
        warnings.append(
            {
                "level": "gray",
                "text": "Thiếu bối cảnh/lý do ban hành.",
            }
        )
    loai = meta.get("loai_van_ban") or ""
    if loai != "sop_noi_bo":
        from ingestion.watch_nhnn import parse_doc_ref

        title = meta.get("source_doc") or ""
        if not parse_doc_ref(title).get("so_hieu"):
            warnings.append(
                {
                    "level": "gray",
                    "text": "Không thấy số hiệu trong tên văn bản.",
                }
            )
    if not _filled(meta, "co_quan_ban_hanh"):
        warnings.append(
            {
                "level": "gray",
                "text": "Thiếu cơ quan ban hành.",
            }
        )
    if meta.get("trang_thai") in {"het_hieu_luc", "da_sua_doi"} and not (
        meta.get("van_ban_thay_the") or ""
    ).strip():
        warnings.append(
            {
                "level": "gray",
                "text": "Đã hết hiệu lực hoặc sửa đổi nhưng chưa ghi văn bản thay thế.",
            }
        )
    return warnings


def hieu_luc_chua_ro(meta: dict) -> bool:
    return not _filled(meta, "trang_thai") or not _filled(meta, "ngay_hieu_luc")


def missing_attr_warnings(meta: dict) -> list[str]:
    return [w["text"] for w in attr_warnings(meta)]


def warn_level(warnings: list[dict]) -> str:
    order = {"red": 0, "yellow": 1, "gray": 2}
    best = ""
    best_n = 9
    for w in warnings or []:
        n = order.get(w.get("level") or "", 9)
        if n < best_n:
            best, best_n = w["level"], n
    return best
