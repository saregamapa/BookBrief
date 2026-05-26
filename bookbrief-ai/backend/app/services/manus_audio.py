"""
Manus AI — text-to-speech via the Manus task API (agent produces an audio attachment).

There is no dedicated TTS endpoint in the public Manus API; we create a short-lived task
with interactive_mode=false, poll task.listMessages until the agent stops, then download
the first audio attachment (or a URL from structured output / message text).
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set

import httpx

from app.services import manus_client

logger = logging.getLogger(__name__)

# OpenAI voice ids → spoken style hints for the Manus agent
_VOICE_STYLE: Dict[str, str] = {
    "alloy": "neutral, balanced narrator",
    "echo": "warm, clear male-presenting voice",
    "fable": "expressive, story-forward British-leaning narrator",
    "onyx": "deep, calm male-presenting analytical tone",
    "nova": "warm, energetic female-presenting conversational tone",
    "shimmer": "bright, articulate female-presenting tone",
}

# JSON Schema subset required by Manus structured output
_STRUCTURED_TTS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "audio_https_url": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["audio_https_url", "notes"],
    "additionalProperties": False,
}

# Regex to find audio URLs in plain text — extension-based
_URL_RE = re.compile(
    r"https?://[^\s<>\"']+\.(?:mp3|m4a|wav|ogg|aac|flac|webm)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)
# Broader regex: CDN URLs that don't include extension (e.g. /audio/xyz?dl=1)
_CDN_URL_RE = re.compile(
    r"https?://(?:[a-z0-9\-]+\.)*(?:storage\.googleapis\.com|s3\.amazonaws\.com|"
    r"cdn\.|files\.|media\.|audio\.|dl\.)[^\s<>\"']+",
    re.IGNORECASE,
)


def _create_tts_task(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    chunk: str,
    voice: str,
    *,
    agent_profile: str,
) -> str:
    style = _VOICE_STYLE.get(voice.lower(), _VOICE_STYLE["onyx"])
    prompt = (
        "Libraire needs a single spoken audio file (text-to-speech).\n\n"
        f"Narration style: {style}.\n\n"
        "Requirements:\n"
        "- Attach ONE audio file to your reply: MP3 preferred (WAV acceptable).\n"
        "- The recording must contain a natural narration of the ENTIRE text below — "
        "no extra intro like 'here is the audio'.\n"
        "- Read faithfully; skip characters that are not meant to be spoken.\n"
        "- Do not ask questions. If you cannot attach a file, put a direct https:// link "
        "to the audio file as plain text in your message.\n\n"
        "TEXT TO NARRATE:\n---\n"
        f"{chunk}\n---"
    )
    body: Dict[str, Any] = {
        "message": {"content": prompt},
        "interactive_mode": False,
        "hide_in_task_list": False,
        "agent_profile": agent_profile,
        "title": "Libraire TTS",
        "structured_output_schema": _STRUCTURED_TTS_SCHEMA,
    }
    r = client.post(
        f"{base_url}/v2/task.create",
        headers=manus_client.json_headers(api_key),
        json=body,
        timeout=120.0,
    )
    r.raise_for_status()
    data = manus_client.raise_for_manus(r)
    task_id = manus_client.extract_task_id(data)
    logger.info("manus_tts_task_created task_id=%s", task_id)
    return str(task_id)


def _is_audio_attachment(att: Dict[str, Any]) -> bool:
    ctype = (att.get("content_type") or "").lower()
    fname = (att.get("filename") or "").lower()
    atype = att.get("type")
    if atype == "voice":
        return True
    if "audio" in ctype:
        return True
    _AUDIO_EXTS = (".mp3", ".mpeg", ".wav", ".m4a", ".x-m4a", ".ogg", ".aac", ".webm", ".flac")
    if any(fname.endswith(ext) for ext in _AUDIO_EXTS):
        return True
    return False


def _ordered_audio_urls(messages: List[Dict[str, Any]]) -> List[str]:
    """
    Extract all candidate audio URLs from Manus task messages.
    Priority: direct audio attachments → structured output → inline URLs.
    Returns newest-first (reversed chronological).
    """
    attachments: List[str] = []
    structured_url: Optional[str] = None
    inline_urls: List[str] = []

    for ev in messages:
        # Direct audio attachments on assistant messages
        if ev.get("type") == "assistant_message":
            am = ev.get("assistant_message") or {}
            for att in am.get("attachments") or []:
                if not isinstance(att, dict):
                    continue
                url = att.get("url") or att.get("download_url") or att.get("href")
                if url and _is_audio_attachment(att):
                    attachments.append(str(url))
            # Scan message text for audio URLs
            content = am.get("content") or ""
            if isinstance(content, str):
                inline_urls.extend(_URL_RE.findall(content))
                inline_urls.extend(_CDN_URL_RE.findall(content))

        # Structured output result from the schema we submitted
        if ev.get("type") == "structured_output_result":
            sor = ev.get("structured_output_result") or {}
            if sor.get("success"):
                val = sor.get("value") or {}
                u = val.get("audio_https_url")
                if isinstance(u, str) and u.startswith("http"):
                    structured_url = u

        # Some Manus versions emit tool_result events with download URLs
        if ev.get("type") == "tool_result":
            tr = ev.get("tool_result") or {}
            for att in tr.get("attachments") or []:
                if not isinstance(att, dict):
                    continue
                url = att.get("url") or att.get("download_url")
                if url and _is_audio_attachment(att):
                    attachments.append(str(url))

    # Build deduplicated list (priority: attachments > structured > inline)
    seen: Set[str] = set()
    deduped: List[str] = []
    for u in [*attachments, *([] if not structured_url else [structured_url]), *inline_urls]:
        if u and u not in seen:
            seen.add(u)
            deduped.append(u)

    # Return newest-first (last in chronological list = most recent = best)
    return list(reversed(deduped))


def _terminal_agent_status(messages: List[Dict[str, Any]]) -> Optional[str]:
    last: Optional[str] = None
    for ev in messages:
        if ev.get("type") == "status_update":
            su = ev.get("status_update") or {}
            st = su.get("agent_status")
            if isinstance(st, str):
                last = st
    return last


def _first_error_message(messages: List[Dict[str, Any]]) -> Optional[str]:
    for ev in messages:
        if ev.get("type") == "error_message":
            em = ev.get("error_message") or {}
            c = em.get("content")
            if c:
                return str(c)
    return None


def _download_audio(client: httpx.Client, url: str) -> bytes:
    r = client.get(url, timeout=120.0, follow_redirects=True)
    r.raise_for_status()
    content = r.content
    # Sanity-check: anything under 1 KB is almost certainly not audio
    if len(content) < 1024:
        raise RuntimeError(
            f"Downloaded file from {url[:60]!r} is only {len(content)} bytes — not valid audio"
        )
    return content


def synthesize_speech_chunk(
    text: str,
    voice: str,
    api_key: str,
    *,
    api_base: str = manus_client.DEFAULT_MANUS_BASE,
    timeout_seconds: float = 480.0,
    poll_interval: float = 3.0,
    agent_profile: str = "manus-1.6-lite",
) -> bytes:
    """
    Run one Manus task for a single chunk of plain text and return raw audio bytes.

    BUG FIX: deadline is now set AFTER task creation (not before), so the full
    timeout_seconds is available for polling rather than being eaten by the API call.
    """
    text = text.strip()
    if not text:
        raise ValueError("Empty text for Manus TTS")

    base = manus_client.normalize_base(api_base)
    with httpx.Client() as client:
        # ── Create task ───────────────────────────────────────────────────────
        task_id = _create_tts_task(
            client, base, api_key, text, voice, agent_profile=agent_profile
        )

        # ── Deadline starts AFTER task creation (was previously set before!) ─
        deadline = time.monotonic() + timeout_seconds

        last_status: Optional[str] = None
        messages: List[Dict[str, Any]] = []
        poll_count = 0

        while time.monotonic() < deadline:
            try:
                messages = manus_client.list_task_messages(
                    client,
                    base,
                    api_key,
                    task_id,
                    order="asc",
                    limit=200,
                    request_timeout=30.0,
                )
            except Exception as exc:
                logger.warning("manus_poll_error poll=%s err=%s", poll_count, exc)
                time.sleep(poll_interval)
                poll_count += 1
                continue

            err = _first_error_message(messages)
            if err:
                raise RuntimeError(f"Manus task error: {err}")

            last_status = _terminal_agent_status(messages)
            poll_count += 1

            if last_status == "waiting":
                raise RuntimeError(
                    "Manus task is waiting for user input; "
                    "set interactive_mode=false in task.create."
                )

            if last_status == "error":
                raise RuntimeError("Manus agent reported error status")

            if last_status == "stopped":
                candidate_urls = _ordered_audio_urls(messages)

                if not candidate_urls:
                    raise RuntimeError(
                        f"Manus task stopped but no audio attachment or URL found "
                        f"(scanned {len(messages)} messages)."
                    )

                last_exc: Optional[Exception] = None
                for u in candidate_urls:
                    try:
                        audio = _download_audio(client, u)
                        logger.info(
                            "manus_tts_ok bytes=%s voice=%s polls=%s url=%s",
                            len(audio), voice, poll_count, u[:60],
                        )
                        return audio
                    except Exception as exc:
                        logger.warning("manus_download_fail url=%s err=%s", u[:60], exc)
                        last_exc = exc
                        continue

                raise RuntimeError(
                    "Could not download valid audio from any Manus URL"
                ) from last_exc

            logger.debug(
                "manus_polling task=%s status=%s poll=%s remaining=%.0fs",
                task_id, last_status, poll_count,
                max(0.0, deadline - time.monotonic()),
            )
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Manus TTS timed out after {int(timeout_seconds)}s "
            f"(last_status={last_status}, polls={poll_count})"
        )
