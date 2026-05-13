"""
OpenRouter video generation — Google Veo 3.1 Lite (async ``POST /videos`` + poll).

Veo 3.1 Lite generates short clips (~8 seconds each regardless of the ``duration`` param).
To produce a longer video (≈90 seconds), we generate ``num_clips`` short clips, each focused
on a different section of the book summary, then concatenate them with ffmpeg.

Saves the finished MP4 under ``static/generated/videos/`` for same-origin playback.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _split_sections(markdown: str, n: int) -> List[str]:
    """Split markdown into n roughly-equal character chunks."""
    text = (markdown or "").strip()
    if not text or n <= 1:
        return [text] * max(n, 1)
    chunk = max(1, len(text) // n)
    result: List[str] = []
    for i in range(n):
        start = i * chunk
        end = start + chunk if i < n - 1 else len(text)
        result.append(text[start:end].strip())
    return result


def _build_clip_prompt(title: str, section_text: str, clip_idx: int, total_clips: int) -> str:
    """
    Build a focused prompt for a single clip that covers a specific narrative arc position.
    """
    if total_clips <= 1:
        position_hint = "Complete book overview — hook, core themes, key arguments, and takeaway"
    elif clip_idx == 0:
        position_hint = (
            "Opening act — cinematic hook that captures the book's central premise "
            "and why it matters, drawing the viewer in"
        )
    elif clip_idx == total_clips - 1:
        position_hint = (
            "Closing act — key insights, lasting impact, and memorable takeaway "
            "that leaves the viewer thinking"
        )
    else:
        mid = clip_idx  # 1-indexed middle clip label
        position_hint = (
            f"Middle section {mid} of {total_clips - 2} — explore a core theme, "
            "key argument, or pivotal idea from the book"
        )

    excerpt = section_text[:10000]
    return (
        "Motion graphics and cinematic b-roll for a professional book-summary video. "
        "Style: abstract typography, floating icons, animated charts, particle effects, "
        "and smooth transitions — no real public figures, no identifiable copyrighted "
        "characters, no photorealistic unknown faces. Keep visuals clean and modern.\n\n"
        f"Scene role: {position_hint}\n\n"
        f"Book title: {title or 'Untitled'}\n\n"
        "Source material (use the ideas only — do NOT show raw Markdown on screen):\n"
        f"{excerpt}"
    )


# ---------------------------------------------------------------------------
# Single-clip job
# ---------------------------------------------------------------------------

def _submit_and_poll_clip(
    client: httpx.Client,
    root: str,
    api_key: str,
    referer: Optional[str],
    model: str,
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    generate_audio: bool,
    deadline: float,
    poll_interval: float,
    emit: Callable[[str, str], None],
    clip_label: str,
) -> bytes:
    """Submit one Veo job, poll until done, return raw MP4 bytes."""
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "generate_audio": generate_audio,
        # duration param kept at 8 (Veo 3.1 Lite cap) — we stack clips to reach target length
        "duration": 8,
    }

    emit("agent_working", f"Submitting {clip_label} to OpenRouter (Google Veo)…")
    cr = client.post(
        f"{root}/videos",
        headers={**_headers(api_key, referer, "BookBrief"), "Content-Type": "application/json"},
        json=payload,
        timeout=httpx.Timeout(120.0, connect=30.0),
    )
    if cr.status_code not in (200, 201, 202):
        try:
            err = cr.json()
            msg = (err.get("error") or {}).get("message") if isinstance(err, dict) else cr.text
        except Exception:
            msg = (cr.text or "")[:800]
        raise RuntimeError(msg or f"OpenRouter video HTTP {cr.status_code} for {clip_label}")

    created = cr.json()
    if not isinstance(created, dict):
        raise RuntimeError(f"OpenRouter returned invalid JSON for {clip_label}")
    job_id = created.get("id")
    poll_url = created.get("polling_url")
    if not job_id or not poll_url:
        raise RuntimeError(f"OpenRouter video response missing id/polling_url for {clip_label}")

    logger.info("veo_clip_submitted label=%s job_id=%s model=%s", clip_label, job_id, model)

    last_status = ""
    while time.monotonic() < deadline:
        pr = client.get(
            poll_url,
            headers=_headers(api_key, referer, "BookBrief"),
            timeout=httpx.Timeout(30.0, connect=15.0),
        )
        if pr.status_code >= 400:
            try:
                err = pr.json()
                msg = (err.get("error") or {}).get("message") if isinstance(err, dict) else pr.text
            except Exception:
                msg = (pr.text or "")[:800]
            raise RuntimeError(msg or f"OpenRouter poll HTTP {pr.status_code} for {clip_label}")

        data = pr.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"OpenRouter poll returned invalid JSON for {clip_label}")

        st = (data.get("status") or "").lower()
        last_status = st

        if st in ("pending", "queued"):
            emit("agent_working", f"{clip_label}: Queued — Veo is starting…")
        elif st in ("in_progress", "processing"):
            emit("agent_working", f"{clip_label}: Rendering…")
        elif st in ("completed", "complete", "succeeded"):
            urls = list(data.get("unsigned_urls") or [])
            if not urls and isinstance(data.get("url"), str):
                urls = [data["url"]]
            if not urls:
                raise RuntimeError(f"{clip_label} completed but no download URLs were returned")
            video_http = str(urls[0])
            break
        elif st in ("failed", "cancelled", "expired"):
            err = data.get("error") or data.get("failure_reason") or st
            raise RuntimeError(f"{clip_label} failed: {err}")
        else:
            emit("agent_working", f"{clip_label}: Status {st or 'unknown'}…")

        time.sleep(poll_interval)
    else:
        raise TimeoutError(
            f"{clip_label} timed out (last status: {last_status})"
        )

    # Download the clip
    emit("agent_working", f"Downloading {clip_label}…")
    parsed = urlparse(video_http)
    host = (parsed.hostname or "").lower()
    dl_headers = _headers(api_key, referer, "BookBrief") if "openrouter" in host else None

    dl = client.get(
        video_http,
        headers=dl_headers,
        timeout=httpx.Timeout(600.0, connect=60.0),
        follow_redirects=True,
    )
    if dl.status_code == 401 and dl_headers is None:
        dl = client.get(
            video_http,
            headers=_headers(api_key, referer, "BookBrief"),
            timeout=httpx.Timeout(600.0, connect=60.0),
            follow_redirects=True,
        )
    if dl.status_code >= 400:
        raise RuntimeError(f"{clip_label} download failed HTTP {dl.status_code}")

    raw = dl.content
    if len(raw) < 1024:
        raise RuntimeError(f"{clip_label} downloaded video is too small to be valid ({len(raw)} bytes)")

    logger.info("veo_clip_downloaded label=%s bytes=%s", clip_label, len(raw))
    return raw


# ---------------------------------------------------------------------------
# ffmpeg concatenation
# ---------------------------------------------------------------------------

def _ffmpeg_available() -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _ffmpeg_concat(clip_paths: List[Path], output_path: Path) -> None:
    """Concatenate MP4 clips using ffmpeg's concat demuxer."""
    concat_txt = output_path.with_suffix(".concat.txt")
    try:
        concat_txt.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in clip_paths),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_txt),
                "-c", "copy",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg concat failed (exit {result.returncode}): {result.stderr[:600]}"
            )
    finally:
        try:
            concat_txt.unlink(missing_ok=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_video_summary(
    api_key: str,
    title: str,
    markdown: str,
    *,
    summary_id: int,
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/veo-3.1-lite",
    duration: int = 90,           # total target seconds (informational; clips are each ~8 s)
    num_clips: int = 10,          # how many ~8-second clips to generate and stack
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    referer: Optional[str] = None,
    timeout_seconds: float = 1800.0,
    poll_interval: float = 5.0,
    on_progress: Optional[Callable[[str, str], None]] = None,
    generate_audio: bool = True,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Generate a multi-clip video summary by stacking Veo 3.1 Lite clips.

    Strategy:
    1. Split the book summary into ``num_clips`` sections.
    2. Generate one Veo clip per section (each ~8 seconds).
    3. Concatenate all clips with ffmpeg → single MP4.

    Returns (``/static/generated/videos/...``, None, None).
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    n = max(1, min(15, int(num_clips)))
    root = base_url.rstrip("/")
    out_dir = _static_output_dir()

    def emit(phase: str, detail: str) -> None:
        if on_progress:
            on_progress(phase, detail)

    sections = _split_sections(markdown, n)
    deadline = time.monotonic() + float(timeout_seconds)

    emit("starting", f"Generating {n} video clips for a ~{n * 8}s summary…")
    logger.info("veo_multi_start summary_id=%s clips=%s model=%s", summary_id, n, model)

    clip_paths: List[Path] = []
    tmp_suffix = uuid.uuid4().hex[:8]

    with httpx.Client() as client:
        for i, section in enumerate(sections):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Overall video timeout reached before clip {i + 1}")

            clip_label = f"Clip {i + 1}/{n}"
            prompt = _build_clip_prompt(title, section, i, n)

            raw_clip = _submit_and_poll_clip(
                client=client,
                root=root,
                api_key=key,
                referer=referer,
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                generate_audio=generate_audio,
                deadline=deadline,
                poll_interval=poll_interval,
                emit=emit,
                clip_label=clip_label,
            )

            clip_path = out_dir / f"_tmp_{summary_id}_{tmp_suffix}_clip{i:02d}.mp4"
            clip_path.write_bytes(raw_clip)
            clip_paths.append(clip_path)
            emit("agent_working", f"{clip_label} saved ({len(raw_clip) // 1024} KB)")

    # ── Assemble final video ──────────────────────────────────────────────────
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(summary_id))
    final_name = f"summary-{safe_id}-{uuid.uuid4().hex[:8]}.mp4"
    final_path = out_dir / final_name

    if len(clip_paths) == 1:
        # Single clip — just rename it
        clip_paths[0].rename(final_path)
        logger.info("veo_single_clip_saved path=%s", final_path)
    else:
        emit("finalizing", f"Concatenating {len(clip_paths)} clips with ffmpeg…")
        try:
            if _ffmpeg_available():
                _ffmpeg_concat(clip_paths, final_path)
                logger.info(
                    "veo_concat_done path=%s clips=%s size=%s",
                    final_path, len(clip_paths), final_path.stat().st_size,
                )
            else:
                # ffmpeg not available — fall back to the longest/last clip
                logger.warning("veo_ffmpeg_missing — falling back to last clip")
                largest = max(clip_paths, key=lambda p: p.stat().st_size)
                largest.rename(final_path)
        finally:
            # Clean up temp clip files
            for p in clip_paths:
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass

    if not final_path.exists() or final_path.stat().st_size < 1024:
        raise RuntimeError("Final video is missing or too small after assembly")

    public_path = f"/static/generated/videos/{final_name}"
    logger.info("veo_video_ready path=%s bytes=%s", public_path, final_path.stat().st_size)
    emit("finalizing", "Video is ready.")
    return public_path, None, None
