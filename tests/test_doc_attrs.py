from ingestion.doc_attrs import (
    attr_warnings,
    extract_doc_attrs,
    extract_title,
    infer_loai,
    merge_attrs,
    warn_level,
)

TT39 = """
Thông tư 39/2016/TT-NHNN
Ngày ban hành: 30/12/2016
Ngày hiệu lực: 15/03/2017
Tình trạng: Còn hiệu lực

Căn cứ Luật các tổ chức tín dụng ngày 16 tháng 6 năm 2010;
Căn cứ Nghị định số 156/2013/NĐ-CP ngày 11 tháng 11 năm 2013;
Theo đề nghị của Vụ Tín dụng các ngành kinh tế;
Thống đốc Ngân hàng Nhà nước Việt Nam ban hành Thông tư quy định về hoạt động cho vay.

Điều 1. Phạm vi điều chỉnh
Thông tư này quy định về hoạt động cho vay của tổ chức tín dụng.
"""


def test_extract_title_and_loai_from_text():
    title = extract_title(TT39)
    assert "39/2016/TT-NHNN" in title
    assert title.lower().startswith("thông tư")
    assert infer_loai(title) == "thong_tu"
    assert infer_loai("Bảng phân chia thẩm quyền (Trong tín dụng)") == "sop_noi_bo"
    html_title = extract_title(
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nĐộc lập - Tự do - Hạnh phúc\n",
        fallback="Thông tư 39/2016/TT-NHNN | THƯ VIỆN PHÁP LUẬT",
    )
    assert html_title == "Thông tư 39/2016/TT-NHNN"


def test_extracts_hieu_luc_ban_hanh_and_can_cu():
    attrs = extract_doc_attrs(TT39)
    assert attrs["ngay_ban_hanh"] == "2016-12-30"
    assert attrs["ngay_hieu_luc"] == "2017-03-15"
    assert attrs["trang_thai"] == "con_hieu_luc"
    assert attrs["ly_do_ban_hanh"].startswith("Căn cứ Luật")
    assert "ban hành Thông tư" in attrs["ly_do_ban_hanh"]
    assert attrs["co_quan_ban_hanh"] == "Ngân hàng Nhà nước Việt Nam"


def test_missing_text_warns_by_level():
    attrs = extract_doc_attrs("Điều 1. Không có metadata.")
    attrs["source_doc"] = "Văn bản không số"
    attrs["loai_van_ban"] = "thong_tu"
    warns = attr_warnings(attrs)
    by_level = {w["level"]: w["text"] for w in warns}
    assert by_level["red"]
    assert "hiệu lực" in by_level["red"]
    assert "ngày ban hành" in by_level["yellow"]
    assert any(w["level"] == "gray" and "lý do" in w["text"] for w in warns)
    assert any(w["level"] == "gray" and "số hiệu" in w["text"] for w in warns)
    assert any(w["level"] == "gray" and "cơ quan" in w["text"] for w in warns)
    assert warn_level(warns) == "red"


def test_user_values_win_over_extracted():
    extracted = extract_doc_attrs(TT39)
    merged = merge_attrs(
        {
            "source_doc": "Thông tư 39/2016/TT-NHNN",
            "loai_van_ban": "thong_tu",
            "ngay_ban_hanh": "2016-12-31",
            "ngay_hieu_luc": "",
            "trang_thai": "",
            "ly_do_ban_hanh": "",
            "co_quan_ban_hanh": "",
        },
        extracted,
    )
    assert merged["ngay_ban_hanh"] == "2016-12-31"
    assert merged["ngay_hieu_luc"] == "2017-03-15"
    assert attr_warnings(merged) == []


def test_hieu_luc_before_ban_hanh_is_yellow():
    warns = attr_warnings(
        {
            "source_doc": "Thông tư 39/2016/TT-NHNN",
            "loai_van_ban": "thong_tu",
            "ngay_ban_hanh": "2017-03-15",
            "ngay_hieu_luc": "2016-12-30",
            "trang_thai": "con_hieu_luc",
            "ly_do_ban_hanh": "Căn cứ Luật.",
            "co_quan_ban_hanh": "Ngân hàng Nhà nước Việt Nam",
        }
    )
    assert any(w["level"] == "yellow" and "trước ngày ban hành" in w["text"] for w in warns)


def test_hieu_luc_tu_ngay_vn():
    text = (
        "Hà Nội, ngày 30 tháng 12 năm 2016\n"
        "Thông tư này có hiệu lực thi hành từ ngày 15 tháng 3 năm 2017.\n"
        "Căn cứ Luật các tổ chức tín dụng;\n"
        "Thống đốc ban hành Thông tư này.\n"
        "Điều 1. Phạm vi\n"
    )
    attrs = extract_doc_attrs(text)
    assert attrs["ngay_ban_hanh"] == "2016-12-30"
    assert attrs["ngay_hieu_luc"] == "2017-03-15"
    assert attrs["ly_do_ban_hanh"]


def test_co_quan_from_label():
    text = "Cơ quan ban hành: Bộ Tài chính\nĐiều 1. Phạm vi\n"
    assert extract_doc_attrs(text)["co_quan_ban_hanh"] == "Bộ Tài chính"


def test_answer_banners_unclear_hieu_luc():
    from api.llm import UNCLEAR_HIEU_LUC, answer

    out = answer(
        "cho vay?",
        [
            {
                "noi_dung": "Điều 1 cho vay của TCTD.",
                "dieu": "Điều 1",
                "source_doc": "Thông tư 39/2016/TT-NHNN",
                "distance": 0.1,
                "trang_thai": "",
                "ngay_hieu_luc": "",
            }
        ],
    )
    assert UNCLEAR_HIEU_LUC in out


def test_watch_suggests_replacement(tmp_path, monkeypatch):
    from api import audit

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    processed.joinpath("tt.json").write_text(
        '[{"source_doc": "Thông tư 39/2016/TT-NHNN quy định cho vay"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    items = audit._annotate_replacements(
        [{"title": "Thông tư 39/2016/TT-NHNN sửa đổi", "so_hieu": "39/2016/TT-NHNN"}]
    )
    assert "văn bản thay thế" in (items[0].get("goi_y_thay_the") or "")
