from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateCheckoutRequest(BaseModel):
    plan: Literal["pro", "growth"] = Field(description="Paid plan to subscribe to")


class CheckoutUrlResponse(BaseModel):
    url: str


class PortalUrlResponse(BaseModel):
    url: str


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    plan: str
    status: str
    summaries_used_period: int
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    has_stripe_subscription: bool
    stripe_customer_id: Optional[str] = None
    # Free tier: 7-day trial cap (2 summaries); paid: monthly limits. Mirrors quota enforcement.
    summary_quota_limit: int = 0
    # Set only for free plan — end of the 7-day trial window (UTC).
    free_trial_ends_at: Optional[datetime] = None
