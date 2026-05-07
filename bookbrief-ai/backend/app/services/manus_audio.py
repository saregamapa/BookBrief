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

logger = logging.getLogger(__name__)

MANUS_BASE = "https://api.manus.ai"

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

_URL_RE = re.compile(
    r"https?://[^\s<>\"']+\.(?:mp3|m4a|wav)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "x-manus-api-key": api_key,
        "Content-Type": "application/json",
    }


def _raise_for_manus(resp: httpx.Response) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception as exc:
        resp.raise_for_status()
        raise RuntimeError("Manus API returned non-JSON body") from exc
    if not data.get("ok"):
        err = data.get("error") or {}
        msg = err.get("message") or str(data)
        raise RuntimeError(f"Manus API error: {msg}")
    return data


def _create_tts_task(
    client: httpx.Client,
    api_key: str,
    chunk: str,
    voice: str,
    *,
    agent_profile: str,
) -> str:
    style = _VOICE_STYLE.get(voice.lower(), _VOICE_STYLE["onyx"])
    prompt = (
        "BookBrief needs a single spoken audio file (text-to-speech).\n\n"
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
        "hide_in_task_list": True,
        "agent_profile": agent_profile,
        "title": "BookBrief TTS",
        "structured_output_schema": _STRUCTURED_TTS_SCHEMA,
    }
    r = client.post(
        f"{MANUS_BASE}/v2/task.create",
        headers=_headers(api_key),
        json=body,
        timeout=120.0,
    )
    r.raise_for_status()
    data = _raise_for_manus(r)
    task_id = data.get("task_id")
    if not task_id:
        raise RuntimeError("Manus task.create missing task_id")
    logger.info("manus_tts_task_created task_id=%s", task_id)
    return str(task_id)


def _list_messages(
    client: httpx.Client, api_key: str, task_id: str
) -> List[Dict[str, Any]]:
    r = client.get(
        f"{MANUS_BASE}/v2/task.listMessages",
        headers={"x-manus-api-key": api_key},
        params={"task_id": task_id, "order": "asc", "limit": 200},
        timeout=120.0,
    )
    r.raise_for_status()
    data = _raise_for_manus(r)
    return list(data.get("messages") or [])


def _is_audio_attachment(att: Dict[str, Any]) -> bool:
    ctype = (att.get("content_type") or "").lower()
    fname = (att.get("filename") or "").lower()
    atype = att.get("type")
    if atype == "voice":
        return True
    if "audio" in ctype:
        return True
    if fname.endswith((".mp3", ".mpeg", ".wav", ".m4a", ".x-m4a")):
        return True
    return False


def _ordered_audio_urls(messages: List[Dict[str, Any]]) -> List[str]:
    """Chronological candidates; caller should try newest-first."""
    attachments: List[str] = []
    structured_url: Optional[str] = None
    inline_urls: List[str] = []

    for ev in messages:
        if ev.get("type") == "assistant_message":
            am = ev.get("assistant_message") or {}
            for att in am.get("attachments") or []:
                if not isinstance(att, dict):
                    continue
                url = att.get("url")
                if url and _is_audio_attachment(att):
                    attachments.append(str(url))
            content = am.get("content") or ""
            if isinstance(content, str):
                inline_urls.extend(_URL_RE.findall(content))

        if ev.get("type") == "structured_output_result":
            sor = ev.get("structured_output_result") or {}
            if sor.get("success"):
                val = sor.get("value") or {}
                u = val.get("audio_https_url")
                if isinstance(u, str) and u.startswith("http"):
                    structured_url = u

    out: List[str] = []
    out.extend(attachments)
    if structured_url:
        out.append(structured_url)
    out.extend(inline_urls)
    # Deduplicate preserving order
    seen: Set[str] = set()
    deduped: List[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


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
    return r.content


def synthesize_speech_chunk(
    text: str,
    voice: str,
    api_key: str,
    *,
    timeout_seconds: float = 480.0,
    poll_interval: float = 3.0,
    agent_profile: str = "manus-1.6-lite",
) -> bytes:
    """
    Run one Manus task for a single chunk of plain text and return raw audio bytes.
    """
    text = text.strip()
    if not text:
        raise ValueError("Empty text for Manus TTS")

    deadline = time.monotonic() + timeout_seconds

    with httpx.Client() as client:
        task_id = _create_tts_task(
            client, api_key, text, voice, agent_profile=agent_profile
        )

        last_status: Optional[str] = None
        messages: List[Dict[str, Any]] = []

        while time.monotonic() < deadline:
            messages = _list_messages(client, api_key, task_id)
            err = _first_error_message(messages)
            if err:
                raise RuntimeError(f"Manus task error: {err}")

            last_status = _terminal_agent_status(messages)

            if last_status == "waiting":
                raise RuntimeError(
                    "Manus task is waiting for user input; set interactive_mode=false "
                    "or complete the task in the Manus app."
                )

            if last_status == "error":
                raise RuntimeError("Manus agent reported error status")

            if last_status == "stopped":
                candidate_urls = _ordered_audio_urls(messages)
                # Prefer newest URLs last in chronological list → try reversed
                candidate_urls = list(reversed(candidate_urls))

                if not candidate_urls:
                    raise RuntimeError(
                        "Manus task finished but no audio attachment or URL was found"
                    )

                last_exc: Optional[Exception] = None
                for u in candidate_urls:
                    try:
                        audio = _download_audio(client, u)
                        if len(audio) < 256:
                            continue
                        logger.info(
                            "manus_tts_downloaded bytes=%s url_prefix=%s",
                            len(audio),
                            u[:48],
                        )
                        return audio
                    except Exception as exc:
                        last_exc = exc
                        continue
                raise RuntimeError(
                    "Could not download audio from Manus output URLs"
                ) from last_exc

            time.sleep(poll_interval)

        raise TimeoutError(
            f"Manus TTS timed out after {int(timeout_seconds)}s (last_status={last_status})"
        )
