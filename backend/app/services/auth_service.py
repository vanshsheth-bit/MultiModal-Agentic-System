"""JWT authentication helpers.

In Phase 1 this uses an in-memory user store for simplicity; it can be
wired to Postgres-backed users in a later phase without changing the
public API.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from ..core.config import config


_FAKE_USERS = {
    "admin": {
        "id": 1,
        "username": "admin",
        "password": "admin",  # DO NOT use in production; for dev only
        "tier": "free",
    }
}


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    user = _FAKE_USERS.get(username)
    if not user or user["password"] != password:
        return None
    return user


def _create_token(data: Dict[str, Any], expires_delta: timedelta, secret: str, algorithm: str) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=algorithm)


def create_access_token(data: Dict[str, Any]) -> str:
    return _create_token(
        data,
        expires_delta=timedelta(minutes=15),
        secret=config.JWT_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )


def create_refresh_token(data: Dict[str, Any]) -> str:
    return _create_token(
        data,
        expires_delta=timedelta(days=7),
        secret=config.JWT_REFRESH_SECRET,
        algorithm=config.JWT_ALGORITHM,
    )


def _decode_token(token: str, secret: str, algorithms: list[str]) -> Optional[Dict[str, Any]]:
    try:
        return jwt.decode(token, secret, algorithms=algorithms)
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    return _decode_token(token, config.JWT_SECRET, [config.JWT_ALGORITHM])


def decode_refresh_token(token: str) -> Optional[Dict[str, Any]]:
    return _decode_token(token, config.JWT_REFRESH_SECRET, [config.JWT_ALGORITHM])
