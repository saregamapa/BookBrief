"""Stripe Checkout, Portal, and webhook subscription sync."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

import stripe
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.enums import PlanTier, SubscriptionStatus
from app.models.stripe_customer import StripeCustomer
from app.models.subscription import Subscription
from app.models.user import User


def _configure_stripe(settings: Settings) -> None:
    if not settings.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = settings.stripe_secret_key


def _stripe_obj_to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


def price_to_plan(settings: Settings, price_id: Optional[str]) -> Optional[PlanTier]:
    if not price_id:
        return None
    if price_id == settings.stripe_price_pro:
        return PlanTier.pro
    if price_id == settings.stripe_price_unlimited:
        return PlanTier.unlimited
    return None


def stripe_status_to_db(stripe_status: Optional[str]) -> SubscriptionStatus:
    if not stripe_status:
        return SubscriptionStatus.active
    mapping = {
        "active": SubscriptionStatus.active,
        "trialing": SubscriptionStatus.trialing,
        "past_due": SubscriptionStatus.past_due,
        "canceled": SubscriptionStatus.canceled,
        "unpaid": SubscriptionStatus.canceled,
        "incomplete_expired": SubscriptionStatus.canceled,
        "incomplete": SubscriptionStatus.incomplete,
        "paused": SubscriptionStatus.active,
    }
    return mapping.get(stripe_status, SubscriptionStatus.active)


def _utc_from_ts(ts: Optional[Union[int, float]]) -> Optional[datetime]:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def ensure_subscription_row(db: Session, user_id: int) -> Subscription:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user_id))
    if sub is not None:
        return sub
    sub = Subscription(
        user_id=user_id,
        plan=PlanTier.free,
        status=SubscriptionStatus.active,
        summaries_used_period=0,
    )
    db.add(sub)
    db.flush()
    return sub


def get_or_create_stripe_customer(db: Session, user: User, settings: Optional[Settings] = None) -> str:
    settings = settings or get_settings()
    _configure_stripe(settings)
    existing = db.scalar(select(StripeCustomer).where(StripeCustomer.user_id == user.id))
    if existing:
        return existing.stripe_customer_id
    cust = stripe.Customer.create(
        email=user.email,
        metadata={"user_id": str(user.id)},
    )
    row = StripeCustomer(user_id=user.id, stripe_customer_id=cust.id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(StripeCustomer).where(StripeCustomer.user_id == user.id))
        if existing:
            return existing.stripe_customer_id
        raise
    return cust.id


def build_checkout_success_url(settings: Settings) -> str:
    base = settings.stripe_success_url.strip()
    if not base:
        base = f"{settings.resolved_public_origin}/frontend/dashboard.html"
    if "{CHECKOUT_SESSION_ID}" in base:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}session_id={{CHECKOUT_SESSION_ID}}"


def _has_active_paid_subscription(sub_row: Subscription) -> bool:
    if not sub_row.stripe_subscription_id:
        return False
    if sub_row.plan not in (PlanTier.pro, PlanTier.unlimited):
        return False
    return sub_row.status in (
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
        SubscriptionStatus.past_due,
    )


def create_checkout_session_url(db: Session, user: User, plan: PlanTier) -> str:
    settings = get_settings()
    if plan not in (PlanTier.pro, PlanTier.unlimited):
        raise ValueError("Checkout only supports pro or unlimited plans")
    if not settings.stripe_price_pro or not settings.stripe_price_unlimited:
        raise RuntimeError("STRIPE_PRICE_PRO and STRIPE_PRICE_UNLIMITED must be set")
    _configure_stripe(settings)

    sub_row = ensure_subscription_row(db, user.id)
    if _has_active_paid_subscription(sub_row):
        raise RuntimeError("You already have an active subscription. Use the billing portal to manage it.")

    price_id = (
        settings.stripe_price_pro if plan == PlanTier.pro else settings.stripe_price_unlimited
    )
    get_or_create_stripe_customer(db, user, settings)
    db.refresh(user)

    customer_id = db.scalar(select(StripeCustomer.stripe_customer_id).where(StripeCustomer.user_id == user.id))
    if not customer_id:
        raise RuntimeError("Could not create Stripe customer")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(user.id),
        metadata={"user_id": str(user.id), "plan": plan.value},
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=build_checkout_success_url(settings),
        cancel_url=(
            settings.stripe_cancel_url.strip()
            or f"{settings.resolved_public_origin}/frontend/index.html"
        ),
        allow_promotion_codes=True,
        subscription_data={"metadata": {"user_id": str(user.id)}},
    )
    if not session.url:
        raise RuntimeError("Stripe did not return a checkout URL")
    return session.url


def create_portal_session_url(db: Session, user: User) -> str:
    settings = get_settings()
    _configure_stripe(settings)
    customer_id = db.scalar(select(StripeCustomer.stripe_customer_id).where(StripeCustomer.user_id == user.id))
    if not customer_id:
        raise RuntimeError("No Stripe customer on file; complete Checkout once to create it.")
    base = settings.resolved_public_origin.rstrip("/")
    return_url = f"{base}/frontend/dashboard.html"
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    if not session.url:
        raise RuntimeError("Stripe did not return a portal URL")
    return session.url


def _primary_price_id(sub_dict: dict[str, Any]) -> Optional[str]:
    items = (sub_dict.get("items") or {}).get("data") or []
    if not items:
        return None
    first = items[0]
    price = first.get("price") if isinstance(first, dict) else None
    if isinstance(price, dict):
        return price.get("id")
    return None


def apply_stripe_subscription_to_user(
    db: Session,
    user_id: int,
    stripe_customer_id: str,
    stripe_subscription: Any,
    settings: Optional[Settings] = None,
) -> None:
    settings = settings or get_settings()
    sub_dict = _stripe_obj_to_dict(stripe_subscription)
    sub_id = sub_dict.get("id")
    if not sub_id:
        return
    status_raw = sub_dict.get("status")
    price_id = _primary_price_id(sub_dict)
    plan = price_to_plan(settings, price_id) or PlanTier.pro
    cps = sub_dict.get("current_period_start")
    cpe = sub_dict.get("current_period_end")

    user = db.get(User, user_id)
    if user is None:
        return

    cust = db.scalar(select(StripeCustomer).where(StripeCustomer.user_id == user_id))
    if cust is None:
        db.add(StripeCustomer(user_id=user_id, stripe_customer_id=stripe_customer_id))
    else:
        cust.stripe_customer_id = stripe_customer_id
        db.add(cust)

    sub_row = ensure_subscription_row(db, user_id)
    sub_row.stripe_subscription_id = str(sub_id)
    sub_row.stripe_price_id = price_id
    sub_row.plan = plan
    sub_row.status = stripe_status_to_db(str(status_raw) if status_raw else None)
    sub_row.current_period_start = _utc_from_ts(cps)  # type: ignore[arg-type]
    sub_row.current_period_end = _utc_from_ts(cpe)  # type: ignore[arg-type]
    db.add(sub_row)
    db.commit()


def downgrade_to_free(db: Session, stripe_subscription_id: str) -> None:
    sub_row = db.scalar(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
    )
    if sub_row is None:
        return
    sub_row.plan = PlanTier.free
    sub_row.status = SubscriptionStatus.active
    sub_row.stripe_subscription_id = None
    sub_row.stripe_price_id = None
    sub_row.current_period_start = None
    sub_row.current_period_end = None
    db.add(sub_row)
    db.commit()


def sync_subscription_from_stripe(db: Session, stripe_subscription: Any) -> None:
    settings = get_settings()
    _configure_stripe(settings)
    sub_dict = _stripe_obj_to_dict(stripe_subscription)
    sub_id = sub_dict.get("id")
    if not sub_id:
        return
    cust_id = sub_dict.get("customer")
    if not cust_id:
        return
    sub_row = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == str(sub_id)))
    if sub_row is None:
        return
    apply_stripe_subscription_to_user(db, sub_row.user_id, str(cust_id), stripe_subscription, settings)


def parse_webhook_payload(payload: bytes, sig_header: Optional[str], settings: Settings) -> stripe.Event:
    if not settings.stripe_webhook_secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured")
    return stripe.Webhook.construct_event(
        payload,
        sig_header or "",
        settings.stripe_webhook_secret,
    )


def handle_webhook_event(db: Session, event: stripe.Event) -> None:
    settings = get_settings()
    _configure_stripe(settings)
    etype = event.type
    data_object = event.data.object

    if etype == "checkout.session.completed":
        obj = _stripe_obj_to_dict(data_object)
        if obj.get("mode") != "subscription":
            return
        user_id_raw = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
        if not user_id_raw:
            return
        user_id = int(user_id_raw)
        cust_id = obj.get("customer")
        sub_id = obj.get("subscription")
        if not cust_id or not sub_id:
            return
        stripe_sub = stripe.Subscription.retrieve(str(sub_id))
        apply_stripe_subscription_to_user(db, user_id, str(cust_id), stripe_sub, settings)
        return

    if etype in ("customer.subscription.updated", "customer.subscription.created"):
        sync_subscription_from_stripe(db, data_object)
        return

    if etype == "customer.subscription.deleted":
        obj = _stripe_obj_to_dict(data_object)
        sid = obj.get("id")
        if sid:
            downgrade_to_free(db, str(sid))
        return
