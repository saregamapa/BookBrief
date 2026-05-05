import secrets
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.limiter import limiter
from app.models.enums import PlanTier, SubscriptionStatus
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserPublic,
)
from app.utils.security import create_access_token, hash_password, verify_password

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TOKEN_TTL_HOURS = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_to_public(user: User) -> UserPublic:
    return UserPublic.model_validate(user)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _issue_token_response(user: User) -> TokenResponse:
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_to_public(user))


def _bump_password_changed_at(user: User, db: Session) -> None:
    """Set password_changed_at to now, invalidating all previously issued tokens."""
    user.password_changed_at = _now_utc()
    db.add(user)
    db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
def register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = _normalize_email(str(body.email))
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )
    fn = body.full_name.strip() if body.full_name else None
    now = _now_utc()
    user = User(
        email=email,
        full_name=fn or None,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_verified=False,
        password_changed_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None

    sub = Subscription(
        user_id=user.id,
        plan=PlanTier.free,
        status=SubscriptionStatus.active,
        summaries_used_period=0,
    )
    db.add(sub)
    db.commit()
    db.refresh(user)
    log.info("user_registered", user_id=user.id, email=email)
    return _issue_token_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = _normalize_email(str(body.email))
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.hashed_password):
        log.warning("login_failed", email=email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        log.warning("login_disabled_account", user_id=user.id, email=email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    log.info("login_success", user_id=user.id)
    return _issue_token_response(user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """JWT is stateless; discard the token on the client.
    Use /auth/revoke-all to invalidate all active sessions immediately."""
    log.info("logout", user_id=current_user.id)
    return MessageResponse(message="Logged out successfully. Please clear the token on your client.")


@router.post("/revoke-all", response_model=MessageResponse)
def revoke_all_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Immediately invalidates every token issued before now for this user.

    Use this when you suspect account compromise or want to force-logout all
    other devices.  The current request still succeeds because the token is
    validated before password_changed_at is bumped.
    """
    _bump_password_changed_at(current_user, db)
    log.info("revoke_all_sessions", user_id=current_user.id)
    return MessageResponse(message="All sessions revoked. Please log in again on your other devices.")


@router.post("/change-password", response_model=TokenResponse)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TokenResponse:
    """Change password while authenticated.

    Verifies the current password, sets the new one, bumps password_changed_at
    (invalidating all other active tokens), then issues a fresh token so the
    caller stays logged in.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        log.warning("change_password_wrong_current", user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = hash_password(body.new_password)
    current_user.password_changed_at = _now_utc()
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    log.info("password_changed", user_id=current_user.id)
    return _issue_token_response(current_user)


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Issues a short-lived reset token.

    In DEBUG mode, the token is returned in the message (no email sending yet).
    """
    email = _normalize_email(str(body.email))
    user = db.scalar(select(User).where(User.email == email))
    msg = "If that email is registered, you can reset your password using the instructions we sent."
    if user is None:
        return MessageResponse(message=msg)

    raw = secrets.token_urlsafe(32)
    user.reset_token = raw
    user.reset_token_expires = _now_utc() + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    db.add(user)
    db.commit()
    log.info("password_reset_requested", user_id=user.id)

    settings = get_settings()
    if settings.debug:
        return MessageResponse(
            message=f"{msg} [DEBUG] reset_token={raw} (expires in {RESET_TOKEN_TTL_HOURS}h)",
        )
    return MessageResponse(message=msg)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("5/minute")
def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    now = _now_utc()
    user = db.scalar(select(User).where(User.reset_token == body.token.strip()))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    if user.reset_token_expires is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    if _as_utc_aware(user.reset_token_expires) < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    user.hashed_password = hash_password(body.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    # Bump password_changed_at to invalidate any active tokens for this account.
    user.password_changed_at = now
    db.add(user)
    db.commit()
    log.info("password_reset_completed", user_id=user.id)
    return MessageResponse(message="Password updated. You can sign in with your new password.")


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return _user_to_public(current_user)
