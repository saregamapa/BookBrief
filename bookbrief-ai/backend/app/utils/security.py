from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

_BCRYPT_ROUNDS = 12


def _password_bytes(plain: str) -> bytes:
    """Bcrypt accepts at most 72 bytes."""
    b = plain.encode("utf-8")
    return b[:72] if len(b) > 72 else b


def hash_password(plain: str) -> str:
    hashed = bcrypt.hashpw(_password_bytes(plain), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("ascii"))
    except ValueError:
        return False


_TOKEN_TYPE_ACCESS = "access"


def create_access_token(
    subject: Union[str, int],
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(timezone.utc)
    to_encode: dict[str, Any] = {
        "sub": str(subject),
        "typ": _TOKEN_TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and verify an access token.

    Returns the payload dict on success, or None if the token is invalid,
    expired, or is not an access token (wrong ``typ`` claim).
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None

    # Reject tokens that aren't access tokens (defence against token confusion).
    if payload.get("typ") not in (_TOKEN_TYPE_ACCESS, None):
        return None

    return payload


def token_issued_at(payload: dict[str, Any]) -> Optional[datetime]:
    """Return the UTC datetime when the token was issued, or None if missing."""
    iat = payload.get("iat")
    if iat is None:
        return None
    try:
        return datetime.fromtimestamp(int(iat), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
