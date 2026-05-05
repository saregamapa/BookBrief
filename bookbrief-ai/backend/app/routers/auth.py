import secrets
from datetime import datetime, timedelta, timezone

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
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserPublic,
)
from app.utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

RESET_TOKEN_TTL_HOURS = 1


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_to_public(user: User) -> UserPublic:
    return UserPublic.model_validate(user)


def _issue_token_response(user: User) -> TokenResponse:
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=_user_to_public(user))


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
    user = User(
        email=email,
        full_name=fn or None,
        hashed_password=hash_password(body.password),
        is_active=True,
        is_verified=False,
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
    return _issue_token_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
def login(
    request: Request,
    body: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    email = _normalize_email(str(body.email))
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    return _issue_token_response(user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """JWT is stateless; discard the token on the client. This endpoint validates the session."""
    return MessageResponse(message="Logged out successfully")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Sets a short-lived reset token. In DEBUG, the token is returned in the message (no email yet)."""
    email = _normalize_email(str(body.email))
    user = db.scalar(select(User).where(User.email == email))
    msg = "If that email is registered, you can reset your password using the instructions we sent."
    if user is None:
        return MessageResponse(message=msg)

    raw = secrets.token_urlsafe(32)
    user.reset_token = raw
    user.reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    db.add(user)
    db.commit()

    settings = get_settings()
    if settings.debug:
        return MessageResponse(
            message=f"{msg} [DEBUG] reset_token={raw} (expires in {RESET_TOKEN_TTL_HOURS}h)",
        )
    return MessageResponse(message=msg)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("10/minute")
def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    now = datetime.now(timezone.utc)
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
    db.add(user)
    db.commit()
    return MessageResponse(message="Password updated. You can sign in with your new password.")


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return _user_to_public(current_user)
