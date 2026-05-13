"""OpenRouter ``/api/v1/audio/speech`` — OpenAI GPT-family TTS (e.g. gpt-4o-mini-tts)."""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def _extract_error_message(r: httpx.Response) -> str:
    """
    Extract a human-readable error from an OpenRouter error response.

    OpenRouter wraps provider errors in a nested structure:
    {
      "error": {
        "message": "Provider returned error",
        "code": 502,
        "metadata": {
          "raw": "{\"error\":{\"message\":\"...\",\"type\":\"...\"}}"
          "provider_name": "OpenAI"
        }
      }
    }
    We unpack all layers to surface the real cause.
    """
    try:
        body = r.json()
    except Exception:
        return (r.text or "")[:500]

    if not isinstance(body, dict):
        return (r.text or "")[:500]

    error_obj = body.get("error") or {}
    top_msg: str = error_obj.get("message") or ""

    # Try to extract provider error from metadata.raw (a JSON string inside JSON)
    metadata = error_obj.get("metadata") or {}
    raw_str: str = metadata.get("raw") or ""
    provider_msg = ""
    if raw_str:
        try:
            raw = json.loads(raw_str)
            provider_msg = ((raw.get("error") or {}).get("message") or "").strip()
        except Exception:
            provider_msg = raw_str[:300]

    provider_name: str = metadata.get("provider_name") or ""

    # Build the most informative message possible
    parts = []
    if top_msg:
        parts.append(top_msg)
    if provider_msg and provider_msg.lower() != top_msg.lower():
        prefix = f"{provider_name}: " if provider_name else ""
        parts.append(f"({prefix}{provider_msg})")

    return " ".join(parts) if parts else (r.text or "")[:500]


def _headers(api_key: str, referer: Optional[str], title: str) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }
    if referer:
        h["HTTP-Referer"] = referer
    h["X-Title"] = title[:128]
    return h


def synthesize_speech(
    api_key: str,
    text: str,
    voice: str,
    *,
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "openai/gpt-4o-mini-tts",
    response_format: str = "mp3",
    referer: Optional[str] = None,
    title: str = "BookBrief",
    timeout_seconds: float = 300.0,
) -> bytes:
    """Return raw audio bytes (e.g. MP3)."""
    url = f"{base_url.rstrip('/')}/audio/speech"
    body = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": response_format,
    }
    timeout = httpx.Timeout(timeout_seconds, connect=60.0)
    for attempt in range(4):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, headers=_headers(api_key, referer, title), json=body)
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "OpenRouter TTS timed out — check your network or increase OPENROUTER_TTS_TIMEOUT_SECONDS."
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"OpenRouter TTS could not reach the API ({type(exc).__name__}: {exc}). "
                "Check internet access, firewall, and that OPENROUTER_API_BASE is correct."
            ) from exc

        if r.status_code in (429, 502, 503, 504) and attempt < 3:
            wait = 1.5 * (2**attempt)
            logger.warning(
                "openrouter_tts_retry status=%s attempt=%s sleep=%ss",
                r.status_code,
                attempt + 1,
                wait,
            )
            time.sleep(wait)
            continue

        if r.status_code >= 400:
            msg = _extract_error_message(r)
            raise RuntimeError(f"OpenRouter TTS HTTP {r.status_code}: {msg}")
        raw = r.content
        min_len = 80 if (response_format or "").lower() == "wav" else 256
        if len(raw) < min_len:
            raise RuntimeError("OpenRouter TTS returned empty or trivial audio")
        logger.info("openrouter_tts_ok model=%s bytes=%s", model, len(raw))
        return raw
