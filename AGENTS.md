# Compliance AI

Saving usage is the top priority.

- Follow the current Notion spec slice only. Do not start the next module until asked.
- Parent-inline. No extra skills, subagents, or Notion re-fetch if the spec is already in context.
- After a task: update Task Tracker if the spec says so, then stop.
- Watch never crawls thuvienphapluat.vn (no Chromium). Paste-URL ingest: httpx → Wayback → one Chromium `--dump-dom`. flock, new process group, SIGKILL at 25s, no retry. SIGTERM is ignored — always SIGKILL. Do not use `--virtual-time-budget` as the only exit.
- Scan PDF: pdfplumber empty → pdftoppm + tesseract `vie+eng`, one page at a time, SIGKILL at 90s/page, no Chromium. If OCR still empty, do not store.

## Active slice
Scan PDF auto-OCR in extract_text (see above). PURPOSE_FILTER.md still applies to Watch.

## Ask
Documents ingested with empty `trang_thai` (red warning, still stored) must be searchable. `only_active` = `con_hieu_luc` or empty — never `where={"trang_thai": "con_hieu_luc"}` alone.

## iPhone PWA
Standalone + `viewport-fit=cover`: nav must sit **below** the frosted status bar (inset + 20px opaque cover). Skill `iphone-pwa-safe-area`. Not a `backdrop-filter` bug. After CSS bump, delete & re-add the home-screen icon.
