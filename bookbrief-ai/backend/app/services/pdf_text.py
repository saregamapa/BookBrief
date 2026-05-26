"""Extract plain text from PDF bytes (used before the summarization graph)."""

from __future__ import annotations

import fitz  # PyMuPDF


def extract_text_from_pdf(
    file_bytes: bytes,
    *,
    max_pages: int = 24,
    max_total_chars: int = 80_000,
) -> str:
    """
    Read up to ``max_pages`` pages and concatenate text.

    Stops early if ``max_total_chars`` is reached to keep downstream LLM costs bounded.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        parts: list[str] = []
        total = 0
        n = min(len(doc), max_pages)
        for i in range(n):
            page = doc.load_page(i)
            text = page.get_text("text") or ""
            if total + len(text) > max_total_chars:
                parts.append(text[: max_total_chars - total])
                break
            parts.append(text)
            total += len(text)
        return "\n\n".join(parts).strip()
    finally:
        doc.close()
