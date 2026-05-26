"""OpenAI Python SDK configured for OpenRouter (chat, JSON, etc.)."""

from __future__ import annotations

from openai import OpenAI

from app.config import get_settings


def get_openrouter_openai_client() -> OpenAI:
    s = get_settings()
    key = (s.openrouter_api_key or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")
    base = (s.openrouter_api_base or "").strip().rstrip("/")
    headers: dict[str, str] = {"X-Title": "Libraire"}
    ref = (s.openrouter_http_referer or "").strip()
    if ref:
        headers["HTTP-Referer"] = ref
    return OpenAI(api_key=key, base_url=base, default_headers=headers)
