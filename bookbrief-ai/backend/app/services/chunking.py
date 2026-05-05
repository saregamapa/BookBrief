"""Split long book text into overlapping chunks for map-style LLM passes."""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_source_text(
    text: str,
    chunk_size: int = 6000,
    chunk_overlap: int = 400,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def join_chunks_preview(chunks: list[str], max_chars: int = 24000) -> str:
    """Join chunks for a single LLM call, truncating with notice if needed."""
    parts: list[str] = []
    total = 0
    for i, ch in enumerate(chunks):
        if total + len(ch) > max_chars:
            parts.append(f"\n\n[... truncated after chunk {i + 1} of {len(chunks)} ...]\n")
            break
        parts.append(ch)
        total += len(ch)
    return "\n\n---CHUNK_BREAK---\n\n".join(parts)
