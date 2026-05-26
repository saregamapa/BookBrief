"""Book summary CRUD and generation (paste, title/author, PDF).

Summarization is performed asynchronously:
  1. POST /summaries or /summaries/pdf creates a row (status=pending) and returns 202 immediately.
  2. A background task runs the LangGraph pipeline and updates the row.
  3. Clients poll GET /summaries/{id}/status until status is 'completed' or 'failed'.
  4. Clients fetch the full summary via GET /summaries/{id} once completed.
"""

from __future__ import annotations

import traceback
from collections import defaultdict
from time import monotonic, time
from typing import DefaultDict, List, Optional

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models.book_summary import BookSummary
from app.models.enums import BookSourceType, SummaryJobStatus, SummaryStyle
from app.models.user import User
from app.schemas.summary import (
    SummaryCreateJSON,
    SummaryDeleteResponse,
    SummaryDetail,
    SummaryListItem,
    SummaryListResponse,
    SummaryStatusResponse,
)
from app.services.pdf_text import extract_text_from_pdf
from app.services.quota import assert_quota_allows_new_summary, sync_subscription_usage_counter
from app.services.stripe_service import ensure_subscription_row
from app.services.summary_graph import run_summarization

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/summaries", tags=["summaries"])

SOURCE_EXCERPT_STORE_MAX = 120_000
MAX_PDF_BYTES = 15 * 1024 * 1024

# In-process per-user sliding window rate limiter (avoids binding Request to JSON body routes).
_summary_hits: DefaultDict[int, List[float]] = defaultdict(list)
_SUMMARY_RATE_MAX = 30
_SUMMARY_RATE_WINDOW_SEC = 3600


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enforce_summary_rate(user: User) -> None:
    now = time()
    q = _summary_hits[user.id]
    q[:] = [t for t in q if now - t < _SUMMARY_RATE_WINDOW_SEC]
    if len(q) >= _SUMMARY_RATE_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many summary requests. Try again in a little while.",
        )
    q.append(now)


def _safe_enum_value(enum_col, fallback: str) -> str:
    """Return enum_col.value safely; fall back to raw string if the DB holds an unknown value."""
    try:
        return enum_col.value
    except (LookupError, ValueError, AttributeError):
        return str(fallback)


def _row_to_detail(row: BookSummary) -> SummaryDetail:
    return SummaryDetail(
        id=row.id,
        title=row.title,
        author=row.author,
        source_type=_safe_enum_value(row.source_type, row.source_type),
        style=_safe_enum_value(row.style, row.style),
        status=_safe_enum_value(row.status, row.status),
        personalization_context=row.personalization_context,
        source_meta=row.source_meta,
        output_markdown=row.output_markdown or "",
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_source_meta(
    *,
    source_type: BookSourceType,
    excerpt: Optional[str] = None,
    filename: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    meta: dict = {"source_type": source_type.value}
    if filename:
        meta["filename"] = filename[:512]
    if excerpt:
        meta["source_excerpt"] = excerpt[:SOURCE_EXCERPT_STORE_MAX]
        meta["source_excerpt_len"] = len(excerpt)
    if extra:
        meta.update(extra)
    return meta


# ---------------------------------------------------------------------------
# Background task — runs after the response has been sent
# ---------------------------------------------------------------------------

def _bg_run_summarization(
    summary_id: int,
    source_text: str,
    title: str,
    author: str,
    style: SummaryStyle,
    personalization: Optional[str],
    user_id: int,
) -> None:
    """Run the LangGraph pipeline in the background.

    Opens its own DB session (the request session is already closed by the time
    this runs) and writes the result back to the BookSummary row.
    """
    with SessionLocal() as db:
        row = db.get(BookSummary, summary_id)
        if row is None:
            log.error("bg_summarization_row_missing", summary_id=summary_id)
            return

        # Mark as processing so the frontend knows work has started.
        row.status = SummaryJobStatus.processing
        row.error_message = None
        db.add(row)
        db.commit()
        log.info("summarization_started", summary_id=summary_id, user_id=user_id, style=style.value)

        try:
            _t0 = monotonic()
            md = run_summarization(
                source_text=source_text,
                title=title,
                author=author,
                style=style,
                personalization_context=personalization,
            )
            _elapsed = monotonic() - _t0
            row = db.get(BookSummary, summary_id)
            if row is None:
                return  # Deleted while processing — nothing to do.
            row.output_markdown = md
            row.status = SummaryJobStatus.completed
            if md.strip().startswith("# Summary unavailable"):
                row.error_message = (
                    "The summarization pipeline reported an issue—often a missing API key or "
                    "empty input. See the markdown body for details."
                )
            else:
                row.error_message = None
            log.info(
                "summarization_completed",
                summary_id=summary_id,
                user_id=user_id,
                elapsed_s=round(_elapsed, 2),
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "summarization_failed",
                summary_id=summary_id,
                user_id=user_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            row = db.get(BookSummary, summary_id)
            if row is None:
                return
            row.status = SummaryJobStatus.failed
            row.error_message = str(exc)[:2000]
            row.output_markdown = ""

        db.add(row)
        db.commit()
        db.refresh(row)

    # Sync usage counter in a fresh session (outside the `with` block above
    # to avoid holding a connection during the commit).
    with SessionLocal() as db2:
        sync_subscription_usage_counter(db2, user_id)


# ---------------------------------------------------------------------------
# Startup recovery — called from main.py on_startup
# ---------------------------------------------------------------------------

def reset_stuck_processing_jobs() -> None:
    """Mark any 'processing' summaries as 'failed' on server start.

    If the server crashed while a background task was running, the row is
    left in 'processing' state forever. This recovery pass resets them so
    users see a clear failure instead of an infinite spinner.
    """
    with SessionLocal() as db:
        stuck = list(
            db.scalars(
                select(BookSummary).where(BookSummary.status == SummaryJobStatus.processing)
            ).all()
        )
        if not stuck:
            return
        for row in stuck:
            row.status = SummaryJobStatus.failed
            row.error_message = "Job was interrupted by a server restart. Please try again."
            db.add(row)
        db.commit()
        log.warning("reset_stuck_jobs", count=len(stuck))


# ---------------------------------------------------------------------------
# POST /summaries — text / title_author (returns 202 immediately)
# ---------------------------------------------------------------------------

@router.post("", response_model=SummaryDetail, status_code=status.HTTP_202_ACCEPTED)
def create_summary_json(
    payload: SummaryCreateJSON,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryDetail:
    _enforce_summary_rate(user)
    sub = ensure_subscription_row(db, user.id)
    assert_quota_allows_new_summary(db, sub)

    st = BookSourceType(payload.source_type)
    style = payload.style
    title = (payload.title or "").strip() or None
    author = (payload.author or "").strip() or None
    content = (payload.content or "").strip() if payload.content else ""

    if st == BookSourceType.paste and not title:
        title = "Pasted excerpt"

    excerpt = content if st == BookSourceType.paste else ""
    meta = _build_source_meta(
        source_type=st,
        excerpt=excerpt if excerpt else None,
        extra={"title_author": st == BookSourceType.title_author},
    )

    row = BookSummary(
        user_id=user.id,
        title=title,
        author=author,
        source_type=st,
        style=style,
        personalization_context=payload.personalization_context,
        source_meta=meta,
        output_markdown="",
        status=SummaryJobStatus.pending,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log.info("summary_queued", summary_id=row.id, user_id=user.id, source_type=st.value, style=style.value)

    # Schedule the LangGraph pipeline to run after this response is sent.
    background_tasks.add_task(
        _bg_run_summarization,
        summary_id=row.id,
        source_text=content if st == BookSourceType.paste else "",
        title=title or "",
        author=author or "",
        style=style,
        personalization=payload.personalization_context,
        user_id=user.id,
    )

    return _row_to_detail(row)


# ---------------------------------------------------------------------------
# POST /summaries/pdf — PDF upload (returns 202 immediately)
# ---------------------------------------------------------------------------

@router.post("/pdf", response_model=SummaryDetail, status_code=status.HTTP_202_ACCEPTED)
def create_summary_pdf(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    style: str = Form("standard"),
    title: Optional[str] = Form(None),
    author: Optional[str] = Form(None),
    personalization_context: Optional[str] = Form(None),
    filename: str = Form("document.pdf"),
    file: UploadFile = File(..., description="PDF document"),
) -> SummaryDetail:
    _enforce_summary_rate(user)
    sub = ensure_subscription_row(db, user.id)
    assert_quota_allows_new_summary(db, sub)

    try:
        style_enum = SummaryStyle(style)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid style: {style}",
        ) from e

    # Read and validate the PDF synchronously (fast, before queuing).
    raw = file.file.read()
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF too large (max {MAX_PDF_BYTES // (1024 * 1024)} MB).",
        )
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file upload.")

    try:
        extracted = extract_text_from_pdf(raw, max_pages=30)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read PDF: {exc}",
        ) from exc

    if not extracted.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extractable text found in the first pages of this PDF.",
        )

    safe_name = (filename or "document.pdf").strip()[:512]
    ttl = (title or "").strip() or safe_name.rsplit(".", 1)[0][:512]
    ath = (author or "").strip() or None
    meta = _build_source_meta(
        source_type=BookSourceType.pdf,
        excerpt=extracted,
        filename=safe_name,
        extra={"pages_scanned": 30},
    )

    row = BookSummary(
        user_id=user.id,
        title=ttl,
        author=ath,
        source_type=BookSourceType.pdf,
        style=style_enum,
        personalization_context=personalization_context,
        source_meta=meta,
        output_markdown="",
        status=SummaryJobStatus.pending,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log.info("pdf_summary_queued", summary_id=row.id, user_id=user.id, filename=safe_name)

    # Schedule background processing — extracted text is passed in so we don't
    # need to re-read the upload (the file handle is gone after the request).
    background_tasks.add_task(
        _bg_run_summarization,
        summary_id=row.id,
        source_text=extracted,
        title=ttl or "",
        author=ath or "",
        style=style_enum,
        personalization=personalization_context,
        user_id=user.id,
    )

    return _row_to_detail(row)


# ---------------------------------------------------------------------------
# GET /summaries/{id}/status — lightweight polling endpoint
# ---------------------------------------------------------------------------

@router.get("/{summary_id}/status", response_model=SummaryStatusResponse)
def get_summary_status(
    summary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryStatusResponse:
    """Poll this endpoint until status is 'completed' or 'failed'.

    Recommended polling interval: 2 s for the first 30 s, then 5 s.
    """
    row = db.get(BookSummary, summary_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    return SummaryStatusResponse(
        id=row.id,
        status=row.status.value,
        error_message=row.error_message,
    )


# ---------------------------------------------------------------------------
# GET /summaries — list
# ---------------------------------------------------------------------------

@router.get("", response_model=SummaryListResponse)
def list_summaries(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: Optional[str] = Query(None, max_length=200),
    style: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None),
    summary_status: Optional[str] = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> SummaryListResponse:
    conds = [BookSummary.user_id == user.id]
    if q:
        like = f"%{q.strip()}%"
        conds.append(
            or_(
                BookSummary.title.ilike(like),
                BookSummary.author.ilike(like),
                BookSummary.output_markdown.ilike(like),
            )
        )
    if style:
        try:
            conds.append(BookSummary.style == SummaryStyle(style))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid style filter") from e
    if source_type:
        try:
            conds.append(BookSummary.source_type == BookSourceType(source_type))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source_type filter"
            ) from e
    if summary_status:
        try:
            conds.append(BookSummary.status == SummaryJobStatus(summary_status))
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter") from e

    total = int(db.scalar(select(func.count()).select_from(BookSummary).where(*conds)) or 0)
    stmt = (
        select(BookSummary)
        .where(*conds)
        .order_by(BookSummary.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    items: list[SummaryListItem] = []
    for r in rows:
        try:
            items.append(SummaryListItem.from_row(r))
        except Exception:  # noqa: BLE001
            log.warning("list_summaries_skip_bad_row", summary_id=getattr(r, "id", "?"))
    return SummaryListResponse(items=items, total=total)


# ---------------------------------------------------------------------------
# GET /summaries/{id} — full detail
# ---------------------------------------------------------------------------

@router.get("/{summary_id}", response_model=SummaryDetail)
def get_summary(
    summary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryDetail:
    row = db.get(BookSummary, summary_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    return _row_to_detail(row)


# ---------------------------------------------------------------------------
# DELETE /summaries/{id}
# ---------------------------------------------------------------------------

@router.delete("/{summary_id}", response_model=SummaryDeleteResponse)
def delete_summary(
    summary_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SummaryDeleteResponse:
    row = db.get(BookSummary, summary_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Summary not found")
    db.delete(row)
    db.commit()
    sync_subscription_usage_counter(db, user.id)
    log.info("summary_deleted", summary_id=summary_id, user_id=user.id)
    return SummaryDeleteResponse(id=summary_id)
