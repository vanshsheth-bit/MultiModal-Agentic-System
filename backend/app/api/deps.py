"""Shared FastAPI dependencies (auth, DB sessions, rate limiting)."""

from typing import Generator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..db.postgres import SessionLocal
from ..services.auth_service import decode_access_token
from ..services.rate_limiter import is_rate_limited


security_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing credentials",
        )
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return payload


async def check_rate_limit(request: Request, current_user=Depends(get_current_user)) -> None:
    """Enforce per-user, per-tier rate limits on API calls.

    This uses a Redis-backed sliding window implemented in ``is_rate_limited``.
    The token payload is treated as the source of user identity and tier.
    """

    tier_limits = {
        "free": 100,
        "pro": 5000,
        "enterprise": 999_999,
    }

    tier = str(current_user.get("tier", "free"))  # type: ignore[union-attr]
    limit = tier_limits.get(tier, tier_limits["free"])

    # Use whatever identifier is present in the token payload; fall back to "anonymous".
    user_identifier = str(current_user.get("id") or current_user.get("sub") or "anonymous")

    # Derive an endpoint key so different endpoints can be limited independently if desired.
    endpoint_key = request.url.path

    # 60-second sliding window by default.
    window_seconds = 60

    if is_rate_limited(user_identifier, endpoint_key, limit, window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
