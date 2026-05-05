from datetime import timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.utils.security import decode_access_token

http_bearer = HTTPBearer(auto_error=False)


def get_token_credentials(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def _check_token_not_revoked(payload: dict, user: User) -> None:
    """Reject tokens that predate the user's last password change.

    This implements instant token invalidation on password change / "revoke all
    sessions" without needing a server-side deny-list.  If ``password_changed_at``
    is unset (existing accounts that predate the column), the check is skipped.

    Compare using **Unix whole seconds**: JWT ``iat`` is second-resolution, while
    ``password_changed_at`` may include microseconds. Comparing datetimes directly
    treated ``iat`` as the *start* of that second and wrongly revoked fresh tokens.
    """
    if user.password_changed_at is None:
        return
    raw_iat = payload.get("iat")
    if raw_iat is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing issuance timestamp",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        iat_sec = int(raw_iat)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing issuance timestamp",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    pca = user.password_changed_at
    if pca.tzinfo is None:
        pca = pca.replace(tzinfo=timezone.utc)
    else:
        pca = pca.astimezone(timezone.utc)
    pca_sec = int(pca.timestamp())

    if iat_sec < pca_sec:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(get_token_credentials),
) -> User:
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    _check_token_not_revoked(payload, user)
    return user


def get_current_user_optional(
    db: Session = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
) -> Optional[User]:
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    try:
        _check_token_not_revoked(payload, user)
    except HTTPException:
        return None
    return user
