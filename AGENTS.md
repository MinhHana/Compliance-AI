# Compliance AI

Saving usage is the top priority.

- Follow the current Notion spec slice only. Do not start the next module until asked.
- Parent-inline. No extra skills, subagents, or Notion re-fetch if the spec is already in context.
- After a task: update Task Tracker if the spec says so, then stop.

## Active slice
See PURPOSE_FILTER.md — Watch must only keep banking-compliance docs.

## Ask
Documents ingested with empty `trang_thai` (red warning, still stored) must be searchable. `only_active` = `con_hieu_luc` or empty — never `where={"trang_thai": "con_hieu_luc"}` alone.
