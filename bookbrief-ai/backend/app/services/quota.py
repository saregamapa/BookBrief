"""Summary quota from plan tier and billing / calendar window."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.book_summary import BookSummary
from app.models.enums import PlanTier, SummaryJobStatus
from app.models.subscription import Subscription


def plan_monthly_limit(plan: PlanTier) -> Optional[int]:
    """None means effectively unlimited."""
    if plan == PlanTier.free:
        return 3
    if plan == PlanTier.pro:
        return 50
    if plan == PlanTier.unlimited:
        return None
    return 3


def quota_window_bounds(sub: Subscription) -> Tuple[datetime, datetime]:
    """
    Return half-open interval [start, end) in UTC for counting completed summaries.

    If Stripe billing period is set, use it (normalized to aware UTC). Otherwise use calendar month UTC.
    """
    now = datetime.now(timezone.utc)

    cps = sub.current_period_start
    cpe = sub.current_period_end
    if cps is not None and cpe is not None:
        start = cps if cps.tzinfo else cps.replace(tzinfo=timezone.utc)
        end = cpe if cpe.tzinfo else cpe.replace(tzinfo=timezone.utc)
        if end <= start:
            start, end = calendar_month_bounds_utc(now)
        return start, end

    return calendar_month_bounds_utc(now)


def calendar_month_bounds_utc(now: datetime) -> Tuple[datetime, datetime]:
    now = now.astimezone(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def count_completed_summaries_in_window(
    db: Session,
    user_id: int,
    window_start: datetime,
    window_end: datetime,
) -> int:
    start = window_start if window_start.tzinfo else window_start.replace(tzinfo=timezone.utc)
    end = window_end if window_end.tzinfo else window_end.replace(tzinfo=timezone.utc)
    return int(
        db.scalar(
            select(func.count())
            .select_from(BookSummary)
            .where(
                BookSummary.user_id == user_id,
                BookSummary.status == SummaryJobStatus.completed,
                BookSummary.created_at >= start,
                BookSummary.created_at < end,
            )
        )
        or 0
    )


def subscription_usage(db: Session, sub: Subscription) -> tuple[int, Optional[int], datetime, datetime]:
    """Returns (used_count, limit_or_none, window_start, window_end)."""
    start, end = quota_window_bounds(sub)
    used = count_completed_summaries_in_window(db, sub.user_id, start, end)
    limit = plan_monthly_limit(sub.plan)
    return used, limit, start, end


def assert_quota_allows_new_summary(db: Session, sub: Subscription) -> None:
    used, limit, _, _ = subscription_usage(db, sub)
    if limit is not None and used >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly summary limit reached ({limit} per billing period). Upgrade your plan or wait until the next period.",
        )


def sync_subscription_usage_counter(db: Session, user_id: int) -> None:
    """Persist `summaries_used_period` from completed summaries in the active quota window."""
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None:
        return
    used, _, _, _ = subscription_usage(db, sub)
    sub.summaries_used_period = used
    db.add(sub)
    db.commit()
