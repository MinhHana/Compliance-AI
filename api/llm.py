from __future__ import annotations

import os

import httpx

MAX_DISTANCE = 0.6
REFUSAL = "Không tìm thấy đoạn quy định đủ liên quan..."


def _settings() -> tuple[str, str, str]:
    key = os.environ.get("LLM_API_KEY") or os.environ.get("XAI_API_KEY") or ""
    base = os.environ.get("LLM_BASE_URL", "https://api.x.ai/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "grok-4")
    return key, base, model


def configured() -> bool:
    return bool(_settings()[0])


def summarize_snippet(text: str) -> str:
    """Gọi LLM (nếu có key) tóm tắt 1 câu tiếng Việt. Không có key hoặc lỗi → trả về text[:200]."""
    snippet = (text or "")[:800]
    if not snippet:
        return ""
    key, base, model = _settings()
    if not key:
        return snippet[:200]
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Tóm tắt đúng 1 câu tiếng Việt, ngắn gọn, chỉ dựa trên đoạn được cung cấp."
                ),
            },
            {"role": "user", "content": snippet},
        ],
        "temperature": 0.1,
    }
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return snippet[:200]


def _relevant(hits: list[dict]) -> list[dict]:
    return [
        h
        for h in hits
        if h.get("distance") is not None and h["distance"] <= MAX_DISTANCE
    ]


def answer(question: str, hits: list[dict]) -> str:
    relevant = _relevant(hits)
    if not relevant:
        return REFUSAL
    key, base, model = _settings()
    if not key:
        return _fallback(relevant)
    context = "\n\n".join(_format_hit(i, h) for i, h in enumerate(relevant, 1))
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Bạn là trợ lý tuân thủ ngân hàng. Chỉ trả lời dựa trên các đoạn "
                    "quy định được cung cấp. Mỗi ý phải nêu Điều và tên văn bản. "
                    "Không đủ căn cứ thì nói không đủ thông tin."
                ),
            },
            {
                "role": "user",
                "content": f"Ngữ cảnh:\n{context}\n\nCâu hỏi: {question}",
            },
        ],
        "temperature": 0.1,
    }
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"{_fallback(hits)}\n\n(LLM lỗi: {exc})"


def _format_hit(i: int, hit: dict) -> str:
    dieu = hit.get("dieu") or "không rõ Điều"
    khoan = hit.get("khoan") or ""
    src = hit.get("source_doc") or hit.get("file_name_goc") or ""
    extra = f", {khoan}" if khoan else ""
    return f"[{i}] {src} — {dieu}{extra}\n{hit.get('noi_dung') or ''}"


def _fallback(hits: list[dict]) -> str:
    if not hits:
        return "Chưa có văn bản trong hệ thống, hoặc không tìm thấy đoạn liên quan."
    lines = [
        "Chưa cấu hình LLM_API_KEY — dưới đây là các đoạn trích gần nhất:",
        "",
    ]
    for i, hit in enumerate(hits, 1):
        lines.append(_format_hit(i, hit))
        lines.append("")
    return "\n".join(lines).strip()
