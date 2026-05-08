"""
Manus AI — short animated video summaries via the Manus task API.

The agent is asked to produce an MP4 (with narration, motion, and subtitles) and
return a public HTTPS URL (and optional WebVTT / poster URLs) via structured output
or message attachments.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from app.services import manus_client

logger = logging.getLogger(__name__)

_STRUCTURED_VIDEO_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "video_https_url": {"type": ["string", "null"]},
        "subtitle_vtt_https_url": {"type": ["string", "null"]},
        "poster_https_url": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
    "required": ["video_https_url", "subtitle_vtt_https_url", "poster_https_url", "notes"],
    "additionalProperties": False,
}

_VIDEO_EXT_RE = re.compile(
    r"https?://[^\s<>\"']+\.(?:mp4|webm|mov|m4v)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)
_VTT_EXT_RE = re.compile(
    r"https?://[^\s<>\"']+\.(?:vtt|srt)(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _is_video_attachment(att: Dict[str, Any]) -> bool:
    ctype = (att.get("content_type") or "").lower()
    fname = (att.get("filename") or "").lower()
    if "video" in ctype:
        return True
    return fname.endswith((".mp4", ".webm", ".mov", ".m4v"))


def _collect_video_and_meta(
    messages: List[Dict[str, Any]],
) -> Tuple[List[str], Optional[str], Optional[str], Optional[str]]:
    """
    Returns (video_urls_chronological, structured_video_url, structured_vtt_url, structured_poster_url).
    Prefer the last video URL in time (caller picks videos[-1]).
    """
    attachments: List[str] = []
    structured_video: Optional[str] = None
    structured_vtt: Optional[str] = None
    structured_poster: Optional[str] = None
    inline_videos: List[str] = []

    for ev in messages:
        if ev.get("type") == "assistant_message":
            am = ev.get("assistant_message") or {}
            for att in am.get("attachments") or []:
                if not isinstance(att, dict):
                    continue
                url = att.get("url")
                if url and _is_video_attachment(att):
                    attachments.append(str(url))
            content = am.get("content") or ""
            if isinstance(content, str):
                inline_videos.extend(_VIDEO_EXT_RE.findall(content))

        if ev.get("type") == "structured_output_result":
            sor = ev.get("structured_output_result") or {}
            if sor.get("success"):
                val = sor.get("value") or {}
                v = val.get("video_https_url")
                if isinstance(v, str) and v.startswith("http"):
                    structured_video = v
                t = val.get("subtitle_vtt_https_url")
                if isinstance(t, str) and t.startswith("http"):
                    structured_vtt = t
                p = val.get("poster_https_url")
                if isinstance(p, str) and p.startswith("http"):
                    structured_poster = p

    ordered: List[str] = []
    for u in [*attachments, *([] if not structured_video else [structured_video]), *inline_videos]:
        if u and u not in ordered:
            ordered.append(u)
    return ordered, structured_video, structured_vtt, structured_poster


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


def _fetch_text(client: httpx.Client, url: str, max_bytes: int = 512_000) -> Optional[str]:
    try:
        r = client.get(url, timeout=60.0, follow_redirects=True)
        r.raise_for_status()
        raw = r.content[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("manus_video_fetch_text_failed url=%s err=%s", url[:80], exc)
        return None


def _humanize_agent_status(st: Optional[str]) -> str:
    if not st:
        return "The agent is producing your video (this often takes several minutes)."
    s = st.lower()
    hints = {
        "running": "Rendering visuals and narration…",
        "thinking": "Planning scenes and script…",
        "stopped": "Finishing up…",
        "waiting": "Waiting…",
        "error": "Encountered an issue…",
    }
    return hints.get(s, f"Agent status: {st}")


def generate_video_summary(
    api_key: str,
    title: str,
    markdown: str,
    *,
    api_base: str = manus_client.DEFAULT_MANUS_BASE,
    timeout_seconds: float = 900.0,
    poll_interval: float = 4.0,
    agent_profile: str = "manus-1.6",
    on_progress: Optional[Callable[[str, str], None]] = None,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Run a Manus task to produce a short video summary.

    Returns (video_https_url, subtitle_vtt_body_or_none, poster_https_url_or_none).
    """
    excerpt = (markdown or "").strip()[:12000]
    prompt = (
        "BookBrief needs a polished SHORT video summary (roughly 45–120 seconds) for readers.\n\n"
        f"Book / topic title: {title or 'Untitled'}\n\n"
        "Creative direction:\n"
        "- Animated or kinetic style: subtle motion graphics, tasteful transitions between beats.\n"
        "- Professional narration (voiceover) that tracks the script — warm, clear, confident.\n"
        "- Legible subtitles (burned into the video OR as a separate WebVTT file you also deliver).\n"
        "- Vertical-safe framing is nice but 16:9 landscape MP4 is preferred.\n\n"
        "Deliverables:\n"
        "1) One MP4 file (H.264/AAC or similar) attached or linked via HTTPS.\n"
        "2) Optional: WebVTT subtitles (attach or HTTPS URL) if not fully burned in.\n"
        "3) Optional: a poster frame image URL (16:9).\n\n"
        "Do not ask clarifying questions — work from the summary text below.\n\n"
        "SUMMARY (Markdown):\n---\n"
        f"{excerpt}\n---"
    )
    body: Dict[str, Any] = {
        "message": {"content": prompt},
        "interactive_mode": False,
        "hide_in_task_list": False,
        "agent_profile": agent_profile,
        "title": "BookBrief video summary",
        "structured_output_schema": _STRUCTURED_VIDEO_SCHEMA,
    }

    emit_state: Dict[str, Any] = {"t": 0.0, "phase": "", "detail": ""}

    def emit(phase: str, detail: str) -> None:
        if not on_progress:
            return
        now = time.monotonic()
        phase_changed = phase != emit_state["phase"]
        detail_changed = detail != emit_state["detail"]
        min_gap = 3.5
        if phase_changed:
            min_gap = 0.0
        elif detail_changed:
            min_gap = 1.75
        if (now - float(emit_state["t"])) < min_gap:
            return
        emit_state["phase"] = phase
        emit_state["detail"] = detail
        emit_state["t"] = now
        on_progress(phase, detail)

    base = manus_client.normalize_base(api_base)
    with httpx.Client() as client:
        emit("starting", "Creating your video task on Manus…")
        r = client.post(
            f"{base}/v2/task.create",
            headers=manus_client.json_headers(api_key),
            json=body,
            timeout=120.0,
        )
        r.raise_for_status()
        data = manus_client.raise_for_manus(r)
        task_id = manus_client.extract_task_id(data)
        logger.info("manus_video_task_created task_id=%s", task_id)
        emit("agent_working", "Task started — generating narration, motion, and video…")

        deadline = time.monotonic() + timeout_seconds
        last_status: Optional[str] = None

        while time.monotonic() < deadline:
            messages = manus_client.list_task_messages(
                client, base, api_key, str(task_id), order="asc", limit=200
            )
            err = _first_error_message(messages)
            if err:
                raise RuntimeError(f"Manus task error: {err}")

            last_status = _terminal_agent_status(messages)
            emit(
                "agent_working",
                _humanize_agent_status(last_status),
            )
            if last_status == "waiting":
                raise RuntimeError("Manus task is waiting for user input")
            if last_status == "error":
                raise RuntimeError("Manus agent reported error status")

            if last_status == "stopped":
                emit("finalizing", "Collecting your video file and any subtitle track…")
                video_urls, _sv, struct_vtt_url, struct_poster = _collect_video_and_meta(messages)
                if not video_urls:
                    raise RuntimeError(
                        "Manus finished but no video URL was found — check the task in Manus"
                    )
                video_url = video_urls[-1]
                vtt_body: Optional[str] = None
                if struct_vtt_url:
                    vtt_body = _fetch_text(client, struct_vtt_url)
                if not vtt_body:
                    for ev in messages:
                        if ev.get("type") != "assistant_message":
                            continue
                        am = ev.get("assistant_message") or {}
                        content = am.get("content") or ""
                        if isinstance(content, str):
                            m = _VTT_EXT_RE.search(content)
                            if m:
                                vtt_body = _fetch_text(client, m.group(0))
                                break
                return video_url, vtt_body, struct_poster

            time.sleep(poll_interval)

        raise TimeoutError(
            f"Manus video generation timed out after {int(timeout_seconds)}s (last_status={last_status})"
        )
