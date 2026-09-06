# Compliance AI

RAG quy định NHNN / pháp luật / SOP. Vector DB trên máy này, LLM gọi API ngoài.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # điền LLM_API_KEY nếu muốn sinh câu trả lời
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8080
```

Mở `http://localhost:8080`. Nạp PDF/docx → hỏi.

Batch thư mục `data/raw_docs/` (kèm file `.pdf.meta.json`):

```bash
PYTHONPATH=. .venv/bin/python -c "from ingestion.batch import process_directory; from vectordb.embed_and_store import embed_processed_dir; print(process_directory()); print(embed_processed_dir())"
```

Cron cảnh báo văn bản mới (không crawl thuvienphapluat.vn):

```bash
PYTHONPATH=. .venv/bin/python -m ingestion.watch_nhnn
```

Test: `PYTHONPATH=. .venv/bin/pytest -q`
