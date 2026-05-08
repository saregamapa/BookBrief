"""Video summary (Manus AI) and translation (OpenAI) for completed book summaries."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models.book_summary import BookSummary
from app.models.enums import SummaryJobStatus, VideoJobStatus
from app.models.summary_translation import SummaryTranslation
from app.models.summary_video import SummaryVideo
from app.models.user import User
from app.schemas.summary_enrichment import (
    TranslateRequest,
    TranslateResponse,
    TranslationListItem,
    TranslationsListResponse,
    VideoSummaryResponse,
)
from app.services import manus_video
from app.services.translation_service import normalize_locale, translate_markdown

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/summaries", tags=["summaries"])


def _get_owned_summary(db: Session, user: User, summary_id: int) -> BookSummary:
    row = db.get(BookSummary, summary_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    return row


def _require_completed(summary: BookSummary) -> None:
    if summary.status != SummaryJobStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Summary must be completed before using this feature",
        )


def _video_response(row: SummaryVideo | None) -> VideoSummaryResponse:
    if row is None:
        return VideoSummaryResponse(status="none")
    return VideoSummaryResponse(
        status=row.status.value,
        video_url=row.video_url,
        subtitle_vtt=row.subtitle_vtt,
        poster_url=row.poster_url,
        error_message=row.error_message,
        progress_phase=row.progress_phase,
        progress_detail=row.progress_detail,
    )


def _persist_video_progress(video_row_id: int, phase: str, detail: str) -> None:
    """Update progress fields so GET /video-summary can show live steps."""
    with SessionLocal() as db:
        r = db.get(SummaryVideo, video_row_id)
        if r is None:
            return
        r.progress_phase = phase[:64] if phase else None
        r.progress_detail = detail[:2000] if detail else None
        db.add(r)
        db.commit()


def _run_video_job(video_row_id: int) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        row = db.get(SummaryVideo, video_row_id)
        if row is None:
            return
        summary = db.get(BookSummary, row.summary_id)
        if summary is None:
            row.status = VideoJobStatus.failed
            row.error_message = "Summary was deleted"
            db.add(row)
            db.commit()
            return
        try:
            key = (settings.manus_api_key or "").strip()
            if not key:
                raise RuntimeError("MANUS_API_KEY is not configured")
            vurl, vtt, poster = manus_video.generate_video_summary(
                key,
                summary.title or "Book brief",
                summary.output_markdown or "",
                api_base=settings.manus_api_base,
                timeout_seconds=float(settings.manus_video_timeout_seconds),
                agent_profile=settings.manus_video_agent_profile,
                on_progress=lambda ph, msg: _persist_video_progress(video_row_id, ph, msg),
            )
            row.status = VideoJobStatus.ready
            row.video_url = vurl
            row.subtitle_vtt = vtt
            row.poster_url = poster
            row.error_message = None
            row.progress_phase = None
            row.progress_detail = None
        except Exception as exc:
            log.exception("video_job_failed", video_row_id=video_row_id)
            row.status = VideoJobStatus.failed
            row.error_message = str(exc)[:4000]
            row.progress_phase = None
            row.progress_detail = None
        db.add(row)
        db.commit()


@router.get("/{summary_id}/translations", response_model=TranslationsListResponse)
def list_translations(
    summary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TranslationsListResponse:
    summary = _get_owned_summary(db, user, summary_id)
    _require_completed(summary)
    rows = db.scalars(
        select(SummaryTranslation)
        .where(SummaryTranslation.summary_id == summary_id)
        .order_by(SummaryTranslation.created_at.asc())
    ).all()
    items = [TranslationListItem(locale=r.locale, created_at=r.created_at) for r in rows]
    return TranslationsListResponse(items=items)


@router.post("/{summary_id}/translate", response_model=TranslateResponse)
def translate_summary(
    summary_id: int,
    body: TranslateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TranslateResponse:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Translation is not configured (missing OPENAI_API_KEY)",
        )
    summary = _get_owned_summary(db, user, summary_id)
    _require_completed(summary)
    try:
        loc = normalize_locale(body.locale)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if loc == "en":
        return TranslateResponse(
            locale=loc,
            markdown=summary.output_markdown or "",
            from_cache=True,
        )

    cached = db.scalar(
        select(SummaryTranslation).where(
            SummaryTranslation.summary_id == summary_id,
            SummaryTranslation.locale == loc,
        )
    )
    if cached:
        return TranslateResponse(locale=loc, markdown=cached.translated_markdown, from_cache=True)

    md = translate_markdown(summary.output_markdown or "", loc)
    row = SummaryTranslation(summary_id=summary_id, locale=loc, translated_markdown=md)
    db.add(row)
    db.commit()
    return TranslateResponse(locale=loc, markdown=md, from_cache=False)


@router.post("/{summary_id}/video-summary")
def start_video_summary(
    summary_id: int,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoSummaryResponse:
    settings = get_settings()
    if not (settings.manus_api_key or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video summaries require MANUS_API_KEY to be configured",
        )
    summary = _get_owned_summary(db, user, summary_id)
    _require_completed(summary)

    row = db.scalar(select(SummaryVideo).where(SummaryVideo.summary_id == summary_id))
    if row and row.status == VideoJobStatus.ready and row.video_url:
        response.status_code = status.HTTP_200_OK
        return _video_response(row)
    if row and row.status == VideoJobStatus.processing:
        response.status_code = status.HTTP_202_ACCEPTED
        return _video_response(row)

    if row is None:
        row = SummaryVideo(
            summary_id=summary_id,
            status=VideoJobStatus.processing,
            progress_phase="queued",
            progress_detail="Your video job is queued…",
        )
        db.add(row)
    else:
        row.status = VideoJobStatus.processing
        row.video_url = None
        row.subtitle_vtt = None
        row.poster_url = None
        row.error_message = None
        row.progress_phase = "queued"
        row.progress_detail = "Your video job is queued…"
        db.add(row)
    db.flush()
    db.commit()
    background_tasks.add_task(_run_video_job, row.id)
    row = db.scalar(select(SummaryVideo).where(SummaryVideo.summary_id == summary_id))
    response.status_code = status.HTTP_202_ACCEPTED
    return _video_response(row)


@router.get("/{summary_id}/video-summary", response_model=VideoSummaryResponse)
def get_video_summary(
    summary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VideoSummaryResponse:
    _get_owned_summary(db, user, summary_id)
    row = db.scalar(select(SummaryVideo).where(SummaryVideo.summary_id == summary_id))
    return _video_response(row)
