"""
LangGraph multi-step summarization: chunk → extract → draft → refine.

Public entry: `run_summarization(...)`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, List, Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.models.enums import SummaryStyle
from app.services.chunking import chunk_source_text
from app.services.summary_prompts import style_instruction


def _has_summarization_api_key() -> bool:
    return bool((get_settings().openrouter_api_key or "").strip())


def _llm() -> ChatOpenAI:
    """LangChain chat pointed at OpenRouter using ``OPENROUTER_SUMMARY_MODEL``."""
    settings = get_settings()
    key = (settings.openrouter_api_key or "").strip()
    model = (settings.openrouter_summary_model or "").strip() or "google/gemma-4-26b-a4b-it"
    root = settings.openrouter_api_base.strip().rstrip("/")
    headers: dict[str, str] = {"X-Title": "BookBrief"}
    ref = (settings.openrouter_http_referer or "").strip()
    if ref:
        headers["HTTP-Referer"] = ref
    return ChatOpenAI(
        model=model,
        temperature=0.25,
        api_key=key or None,
        base_url=root,
        default_headers=headers,
    )

_EXTRACT_SYSTEM = (
    "You are an expert analytical reader. From the excerpt, extract: main claims or plot beats, "
    "supporting evidence or scenes, important definitions or characters, and any turning points. "
    "Respond in concise bullet lists grouped by subtopic. Stay faithful to the excerpt—do not invent beyond reasonable inference."
)

_REFINE_SYSTEM = (
    "You are an editor polishing a book summary for publication. Improve clarity, flow, and markdown structure. "
    "Use ## and ### headings where helpful, keep a single top-level title as # only once if appropriate. "
    "Remove redundancy and fix awkward phrasing. Preserve factual meaning. Output markdown only, no preamble."
)


class SummaryState(TypedDict, total=False):
    source_text: str
    title: str
    author: str
    style: str
    personalization_context: str
    error: str
    chunks: List[str]
    extracted_notes: str
    draft_summary: str
    final_markdown: str


def _parse_style(value: str) -> SummaryStyle:
    try:
        return SummaryStyle(value)
    except ValueError:
        return SummaryStyle.standard


def _prepare_source_and_chunks(state: SummaryState) -> dict[str, Any]:
    if not _has_summarization_api_key():
        return {
            "error": "OPENROUTER_API_KEY is not configured (required for summarization).",
            "chunks": [],
        }

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
            + "\n\nBased on widely available public knowledge of this work, write 700–1100 words of neutral "
            "factual overview: premise, structure, major themes, and ideas a reader should know before a deeper read. "
            "If the title might refer to multiple works or you are uncertain, say so briefly and still give a careful, "
            "tentative overview labeled as uncertain."
        )
        try:
            resp = llm.invoke(
                [
                    SystemMessage(
                        content="You help readers by synthesizing well-known information about books. "
                        "Do not claim to quote the book unless citing widely known lines. No markdown code fences."
                    ),
                    HumanMessage(content=human),
                ]
            )
            text = (resp.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Could not expand title/author into text: {exc}", "chunks": []}

        if not text:
            return {"error": "Title lookup produced empty text.", "chunks": []}

    if not text:
        return {"error": "No source text provided. Paste an excerpt, upload a PDF (processed elsewhere), or supply a book title.", "chunks": []}

    chunks = chunk_source_text(text)
    return {"source_text": text, "chunks": chunks}


def _extract_key_sections(state: SummaryState) -> dict[str, Any]:
    if state.get("error"):
        return {"extracted_notes": ""}

    chunks = state.get("chunks") or []
    if not chunks:
        return {"error": state.get("error") or "No chunks to process.", "extracted_notes": ""}

    llm = _llm()
    notes_parts: list[str] = []
    max_segments = 10
    try:
        for i, chunk in enumerate(chunks[:max_segments]):
            human = (
                f"Excerpt segment {i + 1} of {len(chunks)}:\n\n"
                f"{chunk[:11000]}"
            )
            resp = llm.invoke(
                [SystemMessage(content=_EXTRACT_SYSTEM), HumanMessage(content=human)]
            )
            notes_parts.append(f"### Segment {i + 1}\n{(resp.content or '').strip()}")

        merged = "\n\n".join(notes_parts)
        if len(chunks) > max_segments:
            merged += (
                f"\n\n_Note: {len(chunks) - max_segments} further segment(s) were not processed "
                "to control cost; consider shortening the source._\n"
            )

        if len(merged) > 16000:
            merged = merged[:16000] + "\n\n[... extraction truncated ...]\n"

        if len(chunks) > 1:
            # Second pass: compress cross-segment notes when multiple chunks were used
            compress_msg = (
                "Merge and de-duplicate the following segment-level notes into one coherent outline "
                "(headings + bullets). Preserve nuance; drop repetition.\n\n"
                + merged[:14000]
            )
            resp2 = llm.invoke(
                [
                    SystemMessage(content="You consolidate reader notes into one structured outline."),
                    HumanMessage(content=compress_msg),
                ]
            )
            merged = (resp2.content or merged).strip()

        return {"extracted_notes": merged}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Extraction failed: {exc}", "extracted_notes": ""}


def _summarize(state: SummaryState) -> dict[str, Any]:
    if state.get("error"):
        err = state["error"]
        return {
            "draft_summary": f"# Summary unavailable\n\n{err}\n",
        }

    style = _parse_style(state.get("style") or "standard")
    notes = (state.get("extracted_notes") or "").strip()
    if not notes:
        return {"draft_summary": "# Summary unavailable\n\nNo extracted notes to summarize.\n"}

    title = (state.get("title") or "").strip()
    author = (state.get("author") or "").strip()
    pers = (state.get("personalization_context") or "").strip()

    book_line = ""
    if title:
        book_line = f"Book: *{title}*" + (f" — {author}" if author else "")

    style_block = style_instruction(style)
    pers_block = ""
    if pers and style == SummaryStyle.personalized:
        pers_block = f"\nReader context (honor closely):\n{pers}\n"
    elif pers:
        pers_block = f"\nOptional reader context:\n{pers}\n"

    human = (
        f"{book_line}\n\n"
        f"{style_block}\n"
        f"{pers_block}\n"
        "---\n"
        "Structured notes from the source material:\n\n"
        f"{notes}\n"
        "---\n"
        "Write the summary in polished markdown. Match the requested style and length guidance."
    )

    llm = _llm()
    try:
        resp = llm.invoke(
            [
                SystemMessage(
                    content="You are BookBrief AI: precise, readable, bookish tone. Output markdown only."
                ),
                HumanMessage(content=human[:118000]),
            ]
        )
        return {"draft_summary": (resp.content or "").strip() or "# Summary\n\n(Empty model response.)\n"}
    except Exception as exc:  # noqa: BLE001
        return {"draft_summary": f"# Summary unavailable\n\nSummarization failed: {exc}\n"}


def _refine_and_format(state: SummaryState) -> dict[str, Any]:
    draft = (state.get("draft_summary") or "").strip()
    if not draft:
        return {"final_markdown": "# Summary\n\n(Empty draft.)\n"}

    if draft.startswith("# Summary unavailable"):
        return {"final_markdown": draft}

    title = (state.get("title") or "").strip()
    llm = _llm()
    hint = ""
    if title and not draft.lstrip().startswith("#"):
        hint = f"Prefer starting with a single markdown title line: # {title}\n\n"

    try:
        resp = llm.invoke(
            [
                SystemMessage(content=_REFINE_SYSTEM),
                HumanMessage(content=hint + "Draft to polish:\n\n" + draft[:118000]),
            ]
        )
        out = (resp.content or draft).strip()
        return {"final_markdown": out or draft}
    except Exception:  # noqa: BLE001
        return {"final_markdown": draft}


@lru_cache(maxsize=1)
def get_compiled_summary_graph() -> Any:
    graph = StateGraph(SummaryState)
    graph.add_node("prepare", _prepare_source_and_chunks)
    graph.add_node("extract", _extract_key_sections)
    graph.add_node("summarize", _summarize)
    graph.add_node("refine", _refine_and_format)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "extract")
    graph.add_edge("extract", "summarize")
    graph.add_edge("summarize", "refine")
    graph.add_edge("refine", END)
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
    Run the LangGraph summarization pipeline and return markdown.

    Provide either ``source_text`` (paste/PDF extraction) or ``title`` (and optionally ``author``)
    for a model-generated overview that is then summarized like other inputs.
    """
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
    return (result.get("final_markdown") or "").strip()
