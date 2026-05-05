"""Summary quota enforcement: per-plan limits with correct time windows.

Plan rules (matches pricing page):
  Free:   3 summaries / week  (rolling calendar week, Monday-based)
  Pro:    15 summaries / month (Stripe billing period, falls back to calendar month)
  Growth: 25 summaries / month (Stripe billing period, falls back to calendar month)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.book_summary import BookSummary
from app.models.enums import PlanTier, SummaryJobStatus
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Plan limits
# ---------------------------------------------------------------------------

_PLAN_LIMITS: dict[PlanTier, Optional[int]] = {
    PlanTier.free: 3,    # per week
    PlanTier.pro: 15,    # per billing period / calendar month
    PlanTier.growth: 25, # per billing period / calendar month
}

_FREE_WINDOW = "weekly"
_PAID_WINDOW = "monthly"


def plan_limit(plan: PlanTier) -> Optional[int]:
    """Return the summary limit for a plan (None = unlimited)."""
    return _PLAN_LIMITS.get(plan, 3)


def plan_window_type(plan: PlanTier) -> str:
    """Return 'weekly' for free tier, 'monthly' for paid tiers."""
    return _FREE_WINDOW if plan == PlanTier.free else _PAID_WINDOW


# ---------------------------------------------------------------------------
# Time window helpers
# ---------------------------------------------------------------------------

def quota_window_bounds(sub: Subscription) -> Tuple[datetime, datetime]:
    """Return half-open interval [start, end) in UTC for the active quota window.

    - Free tier: rolling calendar week (Mon 00:00 → next Mon 00:00 UTC)
    - Paid tiers: Stripe billing period when present, else calendar month
    """
    now = datetime.now(timezone.utc)
    window_type = plan_window_type(sub.plan)

    if window_type == _FREE_WINDOW:
        return calendar_week_bounds_utc(now)

    # Paid: prefer Stripe billing period
    cps = sub.current_period_start
    cpe = sub.current_period_end
    if cps is not None and cpe is not None:
        start = cps if cps.tzinfo else cps.replace(tzinfo=timezone.utc)
        end = cpe if cpe.tzinfo else cpe.replace(tzinfo=timezone.utc)
        if end > start:
            return start, end

    return calendar_month_bounds_utc(now)


def calendar_week_bounds_utc(now: datetime) -> Tuple[datetime, datetime]:
    """Return [this Monday 00:00 UTC, next Monday 00:00 UTC)."""
    now_utc = now.astimezone(timezone.utc)
    days_since_monday = now_utc.weekday()  # Monday == 0
    week_start = (now_utc - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def calendar_month_bounds_utc(now: datetime) -> Tuple[datetime, datetime]:
    """Return [first of month 00:00 UTC, first of next month 00:00 UTC)."""
    now_utc = now.astimezone(timezone.utc)
    start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now_utc.month == 12:
        end = datetime(now_utc.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now_utc.year, now_utc.month + 1, 1, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Usage counting
# ---------------------------------------------------------------------------

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


def subscription_usage(
    db: Session, sub: Subscription
) -> tuple[int, Optional[int], datetime, datetime]:
    """Returns (used_count, limit_or_none, window_start, window_end)."""
    start, end = quota_window_bounds(sub)
    used = count_completed_summaries_in_window(db, sub.user_id, start, end)
    limit = plan_limit(sub.plan)
    return used, limit, start, end


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

def assert_quota_allows_new_summary(db: Session, sub: Subscription) -> None:
    """Raise HTTP 429 if the user has exhausted their quota for this period."""
    used, limit, _start, _end = subscription_usage(db, sub)
    if limit is not None and used >= limit:
        window = "week" if plan_window_type(sub.plan) == _FREE_WINDOW else "billing period"
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Summary limit reached ({used}/{limit} this {window}). "
                f"Upgrade your plan or wait until the next {window}."
            ),
        )


def sync_subscription_usage_counter(db: Session, user_id: int) -> None:
    """Persist ``summaries_used_period`` from actual completed-summary count."""
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is None:
        return
    used, _, _, _ = subscription_usage(db, sub)
    sub.summaries_used_period = used
    db.add(sub)
    db.commit()
    logger.debug("quota_synced user_id=%s used=%s", user_id, used)
