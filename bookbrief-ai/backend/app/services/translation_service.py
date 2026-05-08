"""Translate summary markdown with OpenAI; preserve structure (headings, lists, emphasis)."""

from __future__ import annotations

import logging
import re
from typing import FrozenSet

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# BCP-47 style tags we accept (lowercase)
ALLOWED_LOCALES: FrozenSet[str] = frozenset(
    {
        "en",
        "es",
        "fr",
        "de",
        "it",
        "pt",
        "pt-br",
        "ja",
        "zh",
        "zh-cn",
        "zh-tw",
        "ko",
        "hi",
        "ar",
        "nl",
        "pl",
        "ru",
        "sv",
        "tr",
        "vi",
        "id",
        "th",
        "uk",
        "cs",
        "da",
        "fi",
        "no",
        "nb",
        "he",
        "ro",
        "el",
        "hu",
    }
)

_SYSTEM_PROMPT = """You are a professional translator for BookBrief AI.

Rules:
- Translate the user's Markdown book summary into the requested target language.
- Preserve ALL Markdown structure exactly: headings (# ## ###), lists (- * 1.), blockquotes (>), code fences ```, inline `code`, links [text](url), horizontal rules ---, emphasis **bold** and *italic*.
- Do not add commentary, preambles, or explanations — output ONLY the translated Markdown.
- Keep proper names (people, places, book titles) in a natural form for the target language (translate when customary, otherwise transliterate sensibly).
- If a short phrase is already universal (e.g. ISBN numbers), leave digits unchanged.
"""


def normalize_locale(locale: str) -> str:
    loc = (locale or "").strip().lower().replace("_", "-")
    if not loc:
        raise ValueError("locale is required")
    if loc not in ALLOWED_LOCALES:
        raise ValueError(f"Unsupported locale: {locale!r}")
    return loc


def _split_chunks(text: str, max_chars: int = 12000) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    # Prefer splitting on double newlines (paragraph / section boundaries)
    parts: list[str] = []
    buf = ""
    for para in re.split(r"\n\n+", text):
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + "\n\n" + para).strip() if buf else para
        else:
            if buf:
                parts.append(buf)
            if len(para) > max_chars:
                for i in range(0, len(para), max_chars):
                    parts.append(para[i : i + max_chars])
                buf = ""
            else:
                buf = para
    if buf:
        parts.append(buf)
    return parts


def translate_markdown(markdown: str, target_locale: str) -> str:
    """Translate markdown to target_locale (must be in ALLOWED_LOCALES)."""
    loc = normalize_locale(target_locale)
    if loc == "en":
        return markdown

    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    chunks = _split_chunks(markdown or "")
    out_parts: list[str] = []

    for idx, chunk in enumerate(chunks):
        user_msg = (
            f"Target language (BCP-47): {loc}\n"
            f"Part {idx + 1} of {len(chunks)}.\n\n"
            f"---\n{chunk}\n---"
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        piece = (resp.choices[0].message.content or "").strip()
        if not piece:
            raise RuntimeError("OpenAI returned empty translation")
        out_parts.append(piece)
        logger.debug("translation_chunk done part=%s/%s", idx + 1, len(chunks))

    return "\n\n".join(out_parts).strip()
