"""Simple Redis-backed cache helpers."""

import json
from typing import Any, Optional

from ..db.redis import get_redis


def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    r = get_redis()
    r.setex(key, ttl_seconds, json.dumps(value))


def cache_get(key: str) -> Optional[Any]:
    r = get_redis()
    raw = r.get(key)
    if raw is None:
        return None
    return json.loads(raw)
