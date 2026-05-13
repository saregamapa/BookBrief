"""
OpenRouter video generation — Google Veo 3.1 Lite (async ``POST /videos`` + poll).

Saves the finished MP4 under ``static/generated/videos/`` for same-origin playback.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _static_output_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    out = root / "static" / "generated" / "videos"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _headers(api_key: str, referer: Optional[str], title: str) -> dict[str, str]:
    h = {"Authorization": f"Bearer {api_key.strip()}"}
    if referer:
        h["HTTP-Referer"] = referer
    h["X-Title"] = title[:128]
    return h


def _build_prompt(title: str, markdown: str, *, target_seconds: int) -> str:
    excerpt = (markdown or "").strip()[:14000]
    return (
        "Motion graphics and cinematic b-roll summarizing a book or long article for adults. "
        "Abstract typography, icons, charts, and tasteful transitions — no real public figures, "
        "no identifiable copyrighted characters, no photorealistic unknown faces. "
        "Structure the piece as a **complete narrative arc** of the book: hook, core themes, "
        "key arguments or plot beats, and a satisfying closing takeaway — paced for roughly "
        f"{target_seconds} seconds of runtime (not a teaser; cover the full summary below).\n\n"
        f"Title: {title or 'Untitled'}\n\n"
        "Source material (Markdown — use ideas only, do not show raw markdown on screen):\n"
        f"{excerpt}"
    )


def generate_video_summary(
    api_key: str,
    title: str,
    markdown: str,
    *,
    summary_id: int,
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/veo-3.1-lite",
    duration: int = 90,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    referer: Optional[str] = None,
    timeout_seconds: float = 1800.0,
    poll_interval: float = 5.0,
    on_progress: Optional[Callable[[str, str], None]] = None,
    generate_audio: bool = True,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Submit Veo job via OpenRouter, poll ``polling_url``, download first ``unsigned_urls`` entry.

    Returns (``/static/generated/videos/...``, None, None).
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    dur = max(8, min(120, int(duration)))
    root = base_url.rstrip("/")

    def emit(phase: str, detail: str) -> None:
        if on_progress:
            on_progress(phase, detail)

    prompt = _build_prompt(title, markdown, target_seconds=dur)
    emit("starting", "Submitting video job to OpenRouter (Google Veo)…")

    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": dur,
        "resolution": resolution,
        "generate_audio": generate_audio,
    }

    timeout = httpx.Timeout(120.0, connect=30.0)
    with httpx.Client(timeout=timeout) as client:
        cr = client.post(
            f"{root}/videos",
            headers={**_headers(key, referer, "BookBrief"), "Content-Type": "application/json"},
            json=payload,
        )
        if cr.status_code not in (200, 201, 202):
            try:
                err = cr.json()
                msg = (err.get("error") or {}).get("message") if isinstance(err, dict) else cr.text
            except Exception:
                msg = (cr.text or "")[:800]
            raise RuntimeError(msg or f"OpenRouter video HTTP {cr.status_code}")

        created = cr.json()
        if not isinstance(created, dict):
            raise RuntimeError("OpenRouter returned invalid JSON for video job")
        job_id = created.get("id")
        poll_url = created.get("polling_url")
        if not job_id or not poll_url:
            raise RuntimeError("OpenRouter video response missing id or polling_url")

        logger.info("openrouter_veo_job_created id=%s model=%s", job_id, model)
        deadline = time.monotonic() + float(timeout_seconds)
        last_status = ""

        while time.monotonic() < deadline:
            pr = client.get(poll_url, headers=_headers(key, referer, "BookBrief"))
            if pr.status_code >= 400:
                try:
                    err = pr.json()
                    msg = (err.get("error") or {}).get("message") if isinstance(err, dict) else pr.text
                except Exception:
                    msg = (pr.text or "")[:800]
                raise RuntimeError(msg or f"OpenRouter poll HTTP {pr.status_code}")

            data = pr.json()
            if not isinstance(data, dict):
                raise RuntimeError("OpenRouter poll returned invalid JSON")

            st = (data.get("status") or "").lower()
            last_status = st
            if st in ("pending", "queued"):
                emit("agent_working", "Queued — Veo is starting…")
            elif st in ("in_progress", "processing"):
                emit("agent_working", "Veo is rendering your video…")
            elif st in ("completed", "complete", "succeeded"):
                urls = list(data.get("unsigned_urls") or [])
                if not urls and isinstance(data.get("url"), str):
                    urls = [data["url"]]
                if not urls:
                    raise RuntimeError("Video completed but no download URLs were returned")
                video_http = str(urls[0])
                break
            elif st in ("failed", "cancelled", "expired"):
                err = data.get("error") or data.get("failure_reason") or st
                raise RuntimeError(str(err))
            else:
                emit("agent_working", f"Status: {st or 'unknown'}")

            time.sleep(poll_interval)
        else:
            raise TimeoutError(
                f"Veo video timed out after {int(timeout_seconds)}s (last status: {last_status})"
            )

        emit("finalizing", "Downloading your video…")
        # OpenRouter-hosted asset URLs often require the same Bearer token; plain GET returns 401.
        # Do not send our API key to unrelated hosts (e.g. signed GCS URLs may reject Bearer).
        parsed = urlparse(video_http)
        host = (parsed.hostname or "").lower()
        dl_headers = _headers(key, referer, "BookBrief") if "openrouter" in host else None

        dl_timeout = httpx.Timeout(600.0, connect=60.0)
        dl = client.get(
            video_http,
            headers=dl_headers,
            timeout=dl_timeout,
            follow_redirects=True,
        )
        if dl.status_code == 401 and dl_headers is None:
            dl = client.get(
                video_http,
                headers=_headers(key, referer, "BookBrief"),
                timeout=dl_timeout,
                follow_redirects=True,
            )
        if dl.status_code >= 400:
            raise RuntimeError(f"Video download failed HTTP {dl.status_code}")
        raw = dl.content
        if len(raw) < 1024:
            raise RuntimeError("Downloaded video is too small to be valid")

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(job_id))[:80] or "video"
    fname = f"summary-{summary_id}-{safe_id}-{uuid.uuid4().hex[:8]}.mp4"
    out_path = _static_output_dir() / fname
    out_path.write_bytes(raw)
    public_path = f"/static/generated/videos/{fname}"
    logger.info("openrouter_veo_saved path=%s bytes=%s", public_path, len(raw))
    emit("finalizing", "Video is ready.")
    return public_path, None, None
