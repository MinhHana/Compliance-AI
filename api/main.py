from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.audit import log_question, recent_questions, recent_watch
from api.ingest_job import start_ingest, take_page_status
from api.llm import answer, configured
from matrix.audit import find_outdated_links
from matrix.store import create_link, delete_link, list_links
from matrix.suggest import suggest_links
from vectordb.embed_and_store import (
    CHROMA_DIR,
    collection,
    get_chunk,
    list_documents,
)
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
    job = take_page_status()
    ctx = {
        "request": request,
        "answer": extra.get("answer"),
        "citations": extra.get("citations") or [],
        "question": extra.get("question") or "",
        "message": extra.get("message") or job.get("message"),
        "error": extra.get("error") or job.get("error"),
        "chunk_count": _chunk_count(),
        "llm_ready": configured(),
        "history": recent_questions(8),
        "watch": recent_watch(8),
        "form": extra.get("form") or {},
        "ingest_warnings": extra.get("ingest_warnings") or job.get("warnings") or [],
        "ingest_running": bool(job.get("running")),
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


def _ingest_meta(
    source_doc: str,
    loai_van_ban: str,
    ngay_hieu_luc: str,
    trang_thai: str,
    van_ban_thay_the: str,
    source_url: str = "",
    ngay_ban_hanh: str = "",
    ly_do_ban_hanh: str = "",
    pending_file: str = "",
    co_quan_ban_hanh: str = "",
) -> dict:
    meta = {
        "source_doc": source_doc.strip(),
        "loai_van_ban": loai_van_ban,
        "ngay_hieu_luc": ngay_hieu_luc.strip(),
        "trang_thai": trang_thai.strip(),
        "van_ban_thay_the": van_ban_thay_the.strip() or None,
        "ngay_ban_hanh": ngay_ban_hanh.strip(),
        "ly_do_ban_hanh": ly_do_ban_hanh.strip(),
        "co_quan_ban_hanh": co_quan_ban_hanh.strip(),
        "pending_file": pending_file.strip(),
    }
    if source_url:
        meta["source_url"] = source_url.strip()
    return meta


def _pending_path(name: str) -> Path | None:
    if not name or Path(name).name != name:
        return None
    path = RAW_DIR / name
    return path if path.is_file() else None


@app.post("/ingest")
async def ingest(
    request: Request,
    file: UploadFile | None = File(None),
    source_url: str = Form(""),
    source_doc: str = Form(""),
    loai_van_ban: str = Form(""),
    ngay_hieu_luc: str = Form(""),
    trang_thai: str = Form(""),
    van_ban_thay_the: str = Form(""),
    ngay_ban_hanh: str = Form(""),
    ly_do_ban_hanh: str = Form(""),
    pending_file: str = Form(""),
    co_quan_ban_hanh: str = Form(""),
):
    filename = (file.filename if file else "") or ""
    has_file = bool(filename.strip())
    url = source_url.strip()
    pending = _pending_path(pending_file.strip())
    if not has_file and not url and pending is None:
        return _page(request, error="Tải file PDF/Word hoặc dán link văn bản.")
    if not trang_thai.strip():
        return _page(request, error="Chọn hiệu lực của văn bản.")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    meta = _ingest_meta(
        source_doc,
        loai_van_ban,
        ngay_hieu_luc,
        trang_thai,
        van_ban_thay_the,
        url,
        ngay_ban_hanh,
        ly_do_ban_hanh,
        pending_file.strip(),
        co_quan_ban_hanh,
    )
    dest: Path | None = None
    if has_file:
        name = Path(filename).name
        if Path(name).suffix.lower() not in {".pdf", ".docx"}:
            return _page(request, error="Chỉ nhận PDF hoặc Word (.docx).", form=meta)
        dest = RAW_DIR / name
        dest.write_bytes(await file.read())
        label = name
    elif url and pending is None:
        label = url
    else:
        dest = pending
        if dest is None:
            return _page(
                request,
                error="Tải file PDF/Word hoặc dán link văn bản.",
                form=meta,
            )
        label = url or dest.name
    started = start_ingest(
        dest=dest,
        url=url,
        meta=meta,
        label=label,
        raw_dir=RAW_DIR,
        processed_dir=PROCESSED_DIR,
    )
    if not started:
        return _page(
            request,
            error="Đang nạp văn bản khác — đợi xong rồi thử lại.",
            form=meta,
        )
    return _page(request, message=f"Đang nạp {label}…", form=meta)


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
def library(request: Request, canh_bao: str = ""):
    level = canh_bao.strip().lower()
    docs = list_documents()
    if level in {"red", "yellow", "gray"}:
        docs = [d for d in docs if d.get("warn_level") == level]
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "request": request,
            "docs": docs,
            "chunk_count": _chunk_count(),
            "canh_bao": level if level in {"red", "yellow", "gray"} else "",
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
