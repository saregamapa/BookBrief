"""
Audio router — TTS narration + podcast script generation.

Endpoints:
  POST /audio/narrate                 → {job_id, status:"pending"}   (starts background job)
  GET  /audio/narrate/poll/{job_id}   → 202 while pending, 200+binary when done
  POST /audio/podcast-script          → JSON segments (fast, uses GPT)

Why the job pattern?
  Manus TTS tasks take 1–8 minutes.  A synchronous HTTP endpoint would be killed
  by Render (30s), nginx (60s), or the browser long before Manus finishes.
  The background-task + poll pattern avoids all proxy / browser timeouts.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import Response

from app.schemas.audio import (
    NarrateRequest,
    PodcastScriptRequest,
    PodcastScriptResponse,
)
from app.deps import get_current_user
from app.models.user import User
from app.services import audio_jobs, audio_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audio", tags=["audio"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _audio_media_type(data: bytes) -> str:
    """Detect audio format from magic bytes."""
    if len(data) >= 4 and data[:4] == b"RIFF":
        return "audio/wav"
    if len(data) >= 3 and data[:3] == b"ID3":
        return "audio/mpeg"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio/mpeg"   # MPEG sync word
    return "audio/mpeg"       # safe default


# ── Background worker ─────────────────────────────────────────────────────────

def _run_tts(job_id: str, text: str, voice: str) -> None:
    """Run in FastAPI's thread-pool via BackgroundTasks. Never raises."""
    try:
        mp3_bytes = audio_service.text_to_speech(text, voice)
        media = _audio_media_type(mp3_bytes)
        audio_jobs.complete_job(job_id, mp3_bytes, media)
        logger.info("tts_job_done job_id=%s bytes=%s media=%s", job_id, len(mp3_bytes), media)
    except Exception as exc:
        logger.exception("tts_job_failed job_id=%s", job_id)
        audio_jobs.fail_job(job_id, str(exc))


# ── Narrate (async job) ───────────────────────────────────────────────────────

@router.post("/narrate", summary="Start an async TTS audio generation job")
def narrate_text(
    body: NarrateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Enqueues a background TTS job and returns immediately with a job_id.
    Poll GET /audio/narrate/poll/{job_id} until you receive a 200 with audio bytes.
    """
    job = audio_jobs.create_job(current_user.id)
    background_tasks.add_task(_run_tts, job.job_id, body.text, body.voice)
    logger.info(
        "tts_job_created job_id=%s voice=%s text_len=%s",
        job.job_id, body.voice, len(body.text),
    )
    return {"job_id": job.job_id, "status": "pending"}


@router.get(
    "/narrate/poll/{job_id}",
    summary="Poll audio generation job",
    responses={
        200: {"description": "Audio ready — returns binary audio bytes"},
        202: {"description": "Job still in progress"},
        404: {"description": "Job not found or expired"},
        502: {"description": "TTS generation failed"},
    },
)
def poll_narrate(
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """
    Returns:
      • 202  while the job is still running
      • 200  with binary audio when done
      • 404  if job_id is unknown / expired (jobs live 15 min)
      • 502  if TTS generation failed (error detail in body)
    """
    job = audio_jobs.get_job(job_id, current_user.id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found. It may have expired (jobs live for 15 minutes).",
        )

    if job.status == "pending":
        return Response(
            content='{"status":"pending"}',
            status_code=status.HTTP_202_ACCEPTED,
            media_type="application/json",
        )

    if job.status == "error":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=job.error or "TTS generation failed",
        )

    # status == "done" — stream the audio bytes
    return Response(
        content=job.audio_bytes,
        media_type=job.media_type,
        headers={
            "Cache-Control": "private, max-age=900",
            "X-Job-Id": job_id,
        },
    )


# ── Podcast script (synchronous — GPT is fast enough) ─────────────────────────

@router.post(
    "/podcast-script",
    response_model=PodcastScriptResponse,
    summary="Generate a two-host podcast discussion script",
)
def generate_podcast(
    body: PodcastScriptRequest,
    current_user: User = Depends(get_current_user),
) -> PodcastScriptResponse:
    """
    Uses GPT to produce a 10–14-segment two-host discussion about the book.
    Returns immediately; the client calls POST /audio/narrate for each segment.
    """
    try:
        data = audio_service.generate_podcast_script(
            summary_text=body.summary_text,
            title=body.title,
            author=body.author,
        )
    except Exception as exc:
        logger.exception("Podcast script generation failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Podcast script generation failed: {exc}",
        ) from exc

    return PodcastScriptResponse(**data)
