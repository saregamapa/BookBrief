"""System / user instructions per summary style (aligned with SummaryStyle enum)."""

from __future__ import annotations

from app.models.enums import SummaryStyle

STYLE_INSTRUCTIONS: dict[SummaryStyle, str] = {
    SummaryStyle.ultra_short: (
        "Produce an ultra-short summary (roughly a 2-minute read: ~400–550 words). "
        "Lead with the core thesis, then 3–5 tight bullets of the most important ideas. "
        "No fluff, no long quotes."
    ),
    SummaryStyle.standard: (
        "Produce a clear standard summary suitable for a busy reader: overview, key arguments, "
        "important examples, and a short closing takeaway. Aim for balanced depth (~700–1000 words unless the source is tiny)."
    ),
    SummaryStyle.detailed: (
        "Produce a detailed summary with logical sections. Include: overview, chapter- or theme-style "
        "subsections (infer themes if chapters are not explicit), key insights per section, and notable "
        "examples or data points when present. This should read like structured study notes."
    ),
    SummaryStyle.takeaways: (
        "Focus on key takeaways and actionable advice. Use numbered takeaways (8–12 items when the "
        "material supports it). For each, add a one-line 'Try this:' action where practical. "
        "Keep tone encouraging and concrete."
    ),
    SummaryStyle.personalized: (
        "Honor the reader's personalization context (reading goal, background, constraints) when provided. "
        "Shape emphasis, tone, and which ideas to foreground accordingly. Still stay faithful to the source."
    ),
}


def style_instruction(style: SummaryStyle) -> str:
    return STYLE_INSTRUCTIONS.get(
        style,
        STYLE_INSTRUCTIONS[SummaryStyle.standard],
    )
