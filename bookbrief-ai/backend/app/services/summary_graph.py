"""
LangGraph summarization optimized for sub-60-second completion.

Pipeline (2 nodes):
  prepare — resolve title-only input, cap source length for one fast LLM pass
  summarize — single publication-ready markdown call (no per-chunk extract, no separate refine)

Public entry: ``run_summarization(...)``.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any, Optional, TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.models.enums import SummaryStyle
from app.services.summary_prompts import style_instruction

log = structlog.get_logger(__name__)

_SUMMARIZE_SYSTEM = (
    "You are BookBrief AI: precise, readable, bookish tone. "
    "Output polished markdown only — use ## and ### headings, one top-level # title if appropriate. "
    "No preamble, no code fences, no meta commentary about being an AI."
)


def _has_summarization_api_key() -> bool:
    return bool((get_settings().openrouter_api_key or "").strip())


def _llm() -> ChatOpenAI:
    """OpenRouter chat client with tight timeout for the <60s product target."""
    settings = get_settings()
    key = (settings.openrouter_api_key or "").strip()
    model = (settings.openrouter_summary_model or "").strip() or "google/gemma-4-26b-a4b-it"
    root = settings.openrouter_api_base.strip().rstrip("/")
    headers: dict[str, str] = {"X-Title": "BookBrief"}
    ref = (settings.openrouter_http_referer or "").strip()
    if ref:
        headers["HTTP-Referer"] = ref
    timeout = float(settings.summary_llm_timeout_seconds)
    return ChatOpenAI(
        model=model,
        temperature=0.2,
        api_key=key or None,
        base_url=root,
        default_headers=headers,
        timeout=timeout,
        max_retries=1,
    )


def _cap_source_text(text: str, max_chars: int) -> str:
    """Fit long books into one LLM context window (head + tail preserves arc)."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head_len = int(max_chars * 0.72)
    tail_len = max_chars - head_len - 80
    if tail_len < 2000:
        return text[:max_chars] + "\n\n[... truncated for speed ...]\n"
    return (
        text[:head_len]
        + "\n\n[... middle of source omitted to meet speed target — beginning and ending preserved ...]\n\n"
        + text[-tail_len:]
    )


class SummaryState(TypedDict, total=False):
    source_text: str
    title: str
    author: str
    style: str
    personalization_context: str
    error: str
    final_markdown: str


def _parse_style(value: str) -> SummaryStyle:
    try:
        return SummaryStyle(value)
    except ValueError:
        return SummaryStyle.standard


def _prepare_source(state: SummaryState) -> dict[str, Any]:
    if not _has_summarization_api_key():
        return {
            "error": "OPENROUTER_API_KEY is not configured (required for summarization).",
        }

    settings = get_settings()
    text = (state.get("source_text") or "").strip()
    title = (state.get("title") or "").strip()
    author = (state.get("author") or "").strip()

    if not text and title:
        llm = _llm()
        meta = f"Title: {title}"
        if author:
            meta += f"\nAuthor: {author}"
        human = (
            meta
            + "\n\nIn 450–650 words, give a neutral factual overview from widely known information: "
            "premise, structure, major themes, and key ideas. If uncertain which edition/work, say so briefly."
        )
        try:
            resp = llm.invoke(
                [
                    SystemMessage(
                        content="Synthesize well-known book information. No code fences. Be concise."
                    ),
                    HumanMessage(content=human),
                ]
            )
            text = (resp.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Could not expand title/author into text: {exc}"}

        if not text:
            return {"error": "Title lookup produced empty text."}

    if not text:
        return {
            "error": "No source text provided. Paste an excerpt, upload a PDF (processed elsewhere), or supply a book title.",
        }

    capped = _cap_source_text(text, settings.summary_max_input_chars)
    return {"source_text": capped}


def _summarize_once(state: SummaryState) -> dict[str, Any]:
    if state.get("error"):
        err = state["error"]
        return {"final_markdown": f"# Summary unavailable\n\n{err}\n"}

    text = (state.get("source_text") or "").strip()
    if not text:
        return {"final_markdown": "# Summary unavailable\n\nNo source text to summarize.\n"}

    style = _parse_style(state.get("style") or "standard")
    title = (state.get("title") or "").strip()
    author = (state.get("author") or "").strip()
    pers = (state.get("personalization_context") or "").strip()

    book_line = ""
    if title:
        book_line = f"Book: *{title}*" + (f" — {author}" if author else "")
    elif author:
        book_line = f"Author: {author}"

    style_block = style_instruction(style)
    pers_block = ""
    if pers and style == SummaryStyle.personalized:
        pers_block = f"\nReader context (honor closely):\n{pers}\n"
    elif pers:
        pers_block = f"\nOptional reader context:\n{pers}\n"

    title_hint = ""
    if title:
        title_hint = f"\nUse `# {title}` as the main title line.\n"

    human = (
        f"{book_line}\n\n"
        f"{style_block}\n"
        f"{pers_block}"
        f"{title_hint}\n"
        "---\n"
        "Source material:\n\n"
        f"{text}\n"
        "---\n"
        "Write the complete summary now in polished markdown matching the style above."
    )

    settings = get_settings()
    t0 = time.monotonic()
    try:
        resp = _llm().invoke(
            [
                SystemMessage(content=_SUMMARIZE_SYSTEM),
                HumanMessage(content=human[: settings.summary_max_input_chars + 8000]),
            ]
        )
        out = (resp.content or "").strip() or "# Summary\n\n(Empty model response.)\n"
        elapsed = time.monotonic() - t0
        log.info(
            "summary_llm_done",
            elapsed_s=round(elapsed, 2),
            target_s=settings.summary_target_seconds,
            source_chars=len(text),
        )
        return {"final_markdown": out}
    except Exception as exc:  # noqa: BLE001
        return {"final_markdown": f"# Summary unavailable\n\nSummarization failed: {exc}\n"}


@lru_cache(maxsize=1)
def get_compiled_summary_graph() -> Any:
    graph = StateGraph(SummaryState)
    graph.add_node("prepare", _prepare_source)
    graph.add_node("summarize", _summarize_once)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


def run_summarization(
    *,
    source_text: str = "",
    title: str = "",
    author: str = "",
    style: SummaryStyle = SummaryStyle.standard,
    personalization_context: Optional[str] = None,
) -> str:
    """
    Run the fast summarization pipeline and return markdown.

    Typical path: 1 LLM call (paste/PDF). Title-only: 2 calls (expand + summarize).
    Designed to complete within ``SUMMARY_TARGET_SECONDS`` when the model/API is healthy.
    """
    settings = get_settings()
    t0 = time.monotonic()
    graph = get_compiled_summary_graph()
    result = graph.invoke(
        {
            "source_text": source_text or "",
            "title": title or "",
            "author": author or "",
            "style": style.value,
            "personalization_context": personalization_context or "",
        }
    )
    elapsed = time.monotonic() - t0
    log.info(
        "run_summarization_complete",
        elapsed_s=round(elapsed, 2),
        target_s=settings.summary_target_seconds,
        style=style.value,
    )
    return (result.get("final_markdown") or "").strip()
