# SPEC: Lọc Watch theo mục đích tuân thủ ngân hàng

> Mục đích sản phẩm: bàn làm việc cho nhân viên tuân thủ pháp chế ngân hàng — tổng hợp luật, nghị định, thông tư, quy định/SOP nội bộ + AI hỏi đáp có trích dẫn. Không phải cổng tin chính phủ / thời tiết / menu điều hướng.
> Grok Build: CHỈ slice này. Parent-inline. Không mở rộng ngoài danh sách.

## Fix 1 — is_compliance_doc (ingestion/watch_nhnn.py)
Keep item only if at least one:
- parse_doc_ref has loai_van_ban_doan or so_hieu, OR
- title matches (case-insensitive): thông tư, nghị định, luật, quyết định, chỉ thị, công văn, dự thảo, lấy ý kiến, vbqppl, tt-nhnn, nd-cp, qh, sop, quy chế, quy trình

Always drop if:
- is_junk_title(title) (existing)
- title denylist: trang chủ, giới thiệu, liên hệ, đăng nhập, tìm kiếm, doanh nghiệp, báo điện tử, thư điện tử, nước chxhcn, chính phủ, exact menu "văn bản quy phạm pháp luật"
- len(title) < 20 and no so_hieu

Call in fetch_links before insert.

## Fix 2 — recent_watch filter (api/audit.py)
After SELECT, return only items passing is_compliance_doc(title, url). Import from watch_nhnn.

## Fix 3 — tom_tat not code (ingestion/watch_summary.py)
If snippet/tom_tat matches datalayer|gtag|font-face|@font-face|<script|function(|window. → tom_tat = "" or "không tóm tắt được".

## Fix 4 — DEFAULT_URLS
Remove vanban.chinhphu.vn and sbv.gov.vn fallbacks. Keep vbpl NHNN only (or require watch_urls.txt).

## Tests
1. Thông tư 39/2016/TT-NHNN → True
2. Lai Châu 22° → False
3. Giới thiệu Chính phủ → False
4. Doanh nghiệp → False
5. recent_watch hides junk still in SQLite
6. tom_tat with gtag not shown raw
7. pytest -q pass

Then: sudo systemctl restart compliance-ai.service
