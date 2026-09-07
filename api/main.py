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
from matrix.audit import find_outdated_links
from matrix.store import create_link, delete_link, list_links
from matrix.suggest import suggest_links
from vectordb.embed_and_store import CHROMA_DIR, collection, get_chunk, list_documents, upsert_chunks
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
    try:
        n = upsert_chunks(result.get("chunk_dicts") or [])
    except Exception as exc:
        logger.exception("Embed lỗi")
        return _page(request, error=str(exc))
    return _page(request, message=f"Đã nạp {name}: {n} chunk.")


@app.post("/watch")
def watch(request: Request):
    from ingestion.watch_nhnn import run
    from ingestion.watch_summary import summarize_new_items

    try:
        items = run()
        if items:
            items = summarize_new_items(items)
    except Exception as exc:
        return _page(request, error=str(exc))
    msg = f"Có {len(items)} mục mới." if items else "Không có văn bản mới."
    return _page(request, message=msg)


def _chunk_label(chunk: dict | None, fallback_id: str) -> str:
    if not chunk:
        return fallback_id + " (không còn tồn tại)"
    parts = [
        chunk.get("source_doc") or "",
        chunk.get("dieu") or "",
        chunk.get("tieu_de_dieu") or "",
    ]
    label = " · ".join(p for p in parts if p)
    return label or fallback_id


def _sop_chunks() -> list[dict]:
    try:
        raw = collection(CHROMA_DIR).get(where={"loai_van_ban": "sop_noi_bo"})
    except Exception:
        return []
    ids = raw.get("ids") or []
    metas = raw.get("metadatas") or []
    docs = raw.get("documents") or []
    out = []
    for i, cid in enumerate(ids):
        meta = dict(metas[i] or {}) if i < len(metas) else {}
        meta["chunk_id"] = cid
        meta["noi_dung"] = docs[i] if i < len(docs) else ""
        out.append(meta)
    return out


def _matrix_rows() -> list[dict]:
    warnings = {row["id"]: row.get("canh_bao") for row in find_outdated_links()}
    rows = []
    for link in list_links():
        sop = get_chunk(link["sop_chunk_id"])
        qd = get_chunk(link["quydinh_chunk_id"])
        canh_bao = warnings.get(link["id"])
        if sop is None and not canh_bao:
            canh_bao = "sop_khong_con_ton_tai"
        rows.append(
            {
                **link,
                "sop_label": _chunk_label(sop, link["sop_chunk_id"]),
                "qd_label": _chunk_label(qd, link["quydinh_chunk_id"]),
                "trang_thai": (qd or {}).get("trang_thai") or "",
                "canh_bao": canh_bao,
            }
        )
    return rows


def _matrix_page(request: Request, **extra):
    ctx = {
        "request": request,
        "rows": _matrix_rows(),
        "sops": _sop_chunks(),
        "suggestions": extra.get("suggestions") or [],
        "suggest_sop": extra.get("suggest_sop") or "",
        "message": extra.get("message"),
        "error": extra.get("error"),
        "chunk_count": _chunk_count(),
    }
    return templates.TemplateResponse(request, "matrix.html", ctx)


@app.get("/library", response_class=HTMLResponse)
def library(request: Request):
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "request": request,
            "docs": list_documents(),
            "chunk_count": _chunk_count(),
        },
    )


@app.get("/matrix", response_class=HTMLResponse)
def matrix_home(request: Request):
    return _matrix_page(request)


@app.post("/matrix/suggest", response_class=HTMLResponse)
def matrix_suggest(request: Request, sop_chunk_id: str = Form(...)):
    cid = sop_chunk_id.strip()
    if not cid:
        return _matrix_page(request, error="Chọn SOP chunk.")
    if get_chunk(cid) is None:
        return _matrix_page(request, error="Không tìm thấy SOP chunk.")
    hits = suggest_links(cid)
    return _matrix_page(request, suggestions=hits, suggest_sop=cid)


@app.post("/matrix/link", response_class=HTMLResponse)
def matrix_link(
    request: Request,
    sop_chunk_id: str = Form(...),
    quydinh_chunk_id: str = Form(...),
    ghi_chu: str = Form(""),
):
    sop_id = sop_chunk_id.strip()
    qd_id = quydinh_chunk_id.strip()
    if not sop_id or not qd_id:
        return _matrix_page(request, error="Thiếu SOP hoặc quy định.")
    create_link(sop_id, qd_id, ghi_chu.strip(), "nguoi_xac_nhan")
    return _matrix_page(request, message="Đã lưu liên kết.")


@app.post("/matrix/unlink", response_class=HTMLResponse)
def matrix_unlink(request: Request, link_id: int = Form(...)):
    delete_link(link_id)
    return _matrix_page(request, message="Đã xóa liên kết.")


@app.get("/api/health")
def health():
    return {"ok": True, "chunks": _chunk_count(), "llm": configured()}


@app.get("/api/ask")
def api_ask(q: str):
    hits = retrieve(q, n_results=5)
    text = answer(q, hits)
    log_question(q, text, hits)
    return JSONResponse({"answer": text, "citations": hits})
