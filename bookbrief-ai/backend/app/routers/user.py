"""Authenticated user profile and subscription."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.stripe_customer import StripeCustomer
from app.models.user import User
from app.schemas.billing import SubscriptionOut
from app.services.stripe_service import ensure_subscription_row

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/subscription", response_model=SubscriptionOut)
def read_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubscriptionOut:
    sub = ensure_subscription_row(db, user.id)
    cust_id = db.scalar(select(StripeCustomer.stripe_customer_id).where(StripeCustomer.user_id == user.id))
    return SubscriptionOut(
        plan=sub.plan.value,
        status=sub.status.value,
        summaries_used_period=sub.summaries_used_period,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        has_stripe_subscription=bool(sub.stripe_subscription_id),
        stripe_customer_id=cust_id,
    )
