"""Stripe Checkout, Customer Portal, and webhooks."""

from typing import NoReturn

import structlog
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.enums import PlanTier
from app.models.user import User
from app.schemas.billing import CheckoutUrlResponse, CreateCheckoutRequest, PortalUrlResponse
from app.services import stripe_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/stripe", tags=["stripe"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _http_from_runtime(err: RuntimeError) -> NoReturn:
    """Convert a RuntimeError from stripe_service into an HTTPException."""
    msg = str(err)
    lowered = msg.lower()
    code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if "not configured" in lowered or "must be set" in lowered
        else status.HTTP_400_BAD_REQUEST
    )
    raise HTTPException(status_code=code, detail=msg) from err


# ---------------------------------------------------------------------------
# Checkout & portal
# ---------------------------------------------------------------------------

@router.post("/create-checkout-session", response_model=CheckoutUrlResponse)
def create_checkout_session(
    body: CreateCheckoutRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckoutUrlResponse:
    plan_map = {"pro": PlanTier.pro, "growth": PlanTier.growth}
    try:
        url = stripe_service.create_checkout_session_url(db, user, plan_map[body.plan])
        return CheckoutUrlResponse(url=url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except RuntimeError as e:
        _http_from_runtime(e)


@router.post("/create-portal-session", response_model=PortalUrlResponse)
def create_portal_session(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortalUrlResponse:
    try:
        url = stripe_service.create_portal_session_url(db, user)
        return PortalUrlResponse(url=url)
    except RuntimeError as e:
        _http_from_runtime(e)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # --- Signature verification ---
    try:
        event = stripe_service.parse_webhook_payload(payload, sig_header, settings)
    except RuntimeError as e:
        # Misconfiguration — webhook secret not set.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
    except ValueError as e:
        # Malformed payload.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except stripe.SignatureVerificationError as e:
        log.warning("webhook_invalid_signature", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        ) from e

    # --- Event dispatch ---
    # We wrap in a broad try/except so:
    #   - IntegrityError (duplicate idempotent write) → 200 (stop Stripe retries)
    #   - Unexpected errors                           → 500 (Stripe will retry later)
    try:
        stripe_service.handle_webhook_event(db, event)
    except IntegrityError as e:
        # Duplicate event — already processed; tell Stripe not to retry.
        log.warning(
            "webhook_duplicate_event",
            event_type=event.type,
            event_id=event.id,
            error=str(e),
        )
        db.rollback()
    except Exception as e:  # noqa: BLE001
        log.error(
            "webhook_handler_error",
            event_type=event.type,
            event_id=event.id,
            error=str(e),
            exc_info=True,
        )
        raise  # Re-raise so Stripe gets a 500 and retries.

    return {"received": "true"}
