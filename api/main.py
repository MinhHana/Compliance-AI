from __future__ import annotations

import json
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.audit import log_question, recent_questions, recent_watch
from api.llm import answer, configured
from ingestion.batch import process_file
from ingestion.chunk_by_dieu import SourceMetadata
from vectordb.embed_and_store import CHROMA_DIR, collection, upsert_chunks
from vectordb.query import query as retrieve

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_docs"
PROCESSED_DIR = ROOT / "data" / "processed"
WEB = ROOT / "web"

app = FastAPI(title="Compliance AI")
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB / "templates"))


def _chunk_count() -> int:
    try:
        return collection(CHROMA_DIR).count()
    except Exception:
        return 0


def _page(request: Request, **extra):
    ctx = {
        "request": request,
        "answer": extra.get("answer"),
        "citations": extra.get("citations") or [],
        "question": extra.get("question") or "",
        "message": extra.get("message"),
        "error": extra.get("error"),
        "chunk_count": _chunk_count(),
        "llm_ready": configured(),
        "history": recent_questions(8),
        "watch": recent_watch(8),
    }
    return templates.TemplateResponse(request, "index.html", ctx)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _page(request)


@app.post("/ask", response_class=HTMLResponse)
async def ask(request: Request, question: str = Form(...)):
    q = question.strip()
    if not q:
        return _page(request, error="Nhập câu hỏi.")
    hits = retrieve(q, n_results=5)
    text = answer(q, hits)
    log_question(q, text, hits)
    return _page(request, question=q, answer=text, citations=hits)


@app.post("/ingest")
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    source_doc: str = Form(...),
    loai_van_ban: str = Form(...),
    ngay_hieu_luc: str = Form(...),
    trang_thai: str = Form(...),
    van_ban_thay_the: str = Form(""),
):
    name = Path(file.filename or "upload").name
    if Path(name).suffix.lower() not in {".pdf", ".docx"}:
        return _page(request, error="Chỉ nhận PDF hoặc Word (.docx).")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / name
    dest.write_bytes(await file.read())
    meta = {
        "source_doc": source_doc.strip(),
        "loai_van_ban": loai_van_ban,
        "ngay_hieu_luc": ngay_hieu_luc,
        "trang_thai": trang_thai,
        "van_ban_thay_the": van_ban_thay_the.strip() or None,
    }
    dest.with_suffix(dest.suffix + ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        source = SourceMetadata.from_dict(meta)
        result = process_file(dest, source, PROCESSED_DIR)
    except Exception as exc:
        logger.exception("Ingest lỗi")
        return _page(request, error=str(exc))
    if not result.get("ok"):
        return _page(request, error=result.get("error") or "Ingest lỗi")
    if result.get("needs_ocr"):
        return _page(request, message=f"{name} là PDF scan — cần OCR thủ công, chưa đưa vào DB.")
    n = upsert_chunks(result.get("chunk_dicts") or [])
    return _page(request, message=f"Đã nạp {name}: {n} chunk.")


@app.post("/watch")
def watch(request: Request):
    from ingestion.watch_nhnn import run

    try:
        items = run()
    except Exception as exc:
        return _page(request, error=str(exc))
    msg = f"Có {len(items)} mục mới." if items else "Không có văn bản mới."
    return _page(request, message=msg)


@app.get("/api/health")
def health():
    return {"ok": True, "chunks": _chunk_count(), "llm": configured()}


@app.get("/api/ask")
def api_ask(q: str):
    hits = retrieve(q, n_results=5)
    text = answer(q, hits)
    log_question(q, text, hits)
    return JSONResponse({"answer": text, "citations": hits})
