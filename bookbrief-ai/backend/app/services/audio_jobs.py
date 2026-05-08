"""
Persistent audio job store (PostgreSQL / SQLite).

POST /audio/narrate returns immediately with job_id; the client polls GET …/poll/{job_id}.
Jobs must survive multiple uvicorn workers (shared DB), unlike an in-memory dict.

Completed / failed rows older than _JOB_TTL_SEC are deleted on create/get.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models.audio_tts_job import AudioTtsJob

_JOB_TTL_SEC = 900  # 15 minutes


@dataclass
class AudioJob:
    job_id: str
    status: str  # "pending" | "done" | "error"
    audio_bytes: Optional[bytes] = None
    media_type: str = "audio/mpeg"
    error: Optional[str] = None


def _purge_expired() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=_JOB_TTL_SEC)
    with SessionLocal() as db:
        db.execute(delete(AudioTtsJob).where(AudioTtsJob.created_at < cutoff))
        db.commit()


def create_job(user_id: int) -> AudioJob:
    _purge_expired()
    job_id = str(uuid.uuid4())
    row = AudioTtsJob(
        job_id=job_id,
        user_id=user_id,
        status="pending",
        media_type="audio/mpeg",
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
    return AudioJob(job_id=job_id, status="pending")


def _row_to_job(row: AudioTtsJob) -> AudioJob:
    if row.status == "pending":
        return AudioJob(job_id=row.job_id, status="pending")
    if row.status == "error":
        return AudioJob(job_id=row.job_id, status="error", error=row.error_message or "TTS failed")
    return AudioJob(
        job_id=row.job_id,
        status="done",
        audio_bytes=row.audio_blob,
        media_type=row.media_type or "audio/mpeg",
    )


def get_job(job_id: str, user_id: int) -> Optional[AudioJob]:
    """Return the job only if it belongs to this user."""
    _purge_expired()
    with SessionLocal() as db:
        row = db.scalar(
            select(AudioTtsJob).where(
                AudioTtsJob.job_id == job_id,
                AudioTtsJob.user_id == user_id,
            )
        )
        if row is None:
            return None
        return _row_to_job(row)


def complete_job(job_id: str, audio_bytes: bytes, media_type: str = "audio/mpeg") -> None:
    with SessionLocal() as db:
        row = db.scalar(select(AudioTtsJob).where(AudioTtsJob.job_id == job_id))
        if row:
            row.status = "done"
            row.audio_blob = audio_bytes
            row.media_type = media_type
            row.error_message = None
            db.add(row)
            db.commit()


def fail_job(job_id: str, error: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(AudioTtsJob).where(AudioTtsJob.job_id == job_id))
        if row:
            row.status = "error"
            row.error_message = error[:4000]
            row.audio_blob = None
            db.add(row)
            db.commit()
