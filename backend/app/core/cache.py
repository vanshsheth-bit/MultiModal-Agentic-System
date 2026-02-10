import hashlib
import json
import random
from typing import Any, Optional

from app.core.config import config
from app.db.redis import get_redis


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_cache_key(*, prefix: str, payload: Any, version: str = "v1") -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}:{version}:{_stable_digest(raw)}"


def cache_get_json(key: str) -> Optional[Any]:
    if not bool(getattr(config, "CACHE_ENABLED", True)):
        return None
    client = get_redis()
    raw = client.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def cache_set_json(*, key: str, value: Any, ttl_s: int) -> None:
    if not bool(getattr(config, "CACHE_ENABLED", True)):
        return
    if ttl_s <= 0:
        return
    client = get_redis()
    client.setex(key, int(ttl_s), json.dumps(value, ensure_ascii=False))


def should_log_cache_metrics() -> bool:
    if not bool(getattr(config, "CACHE_LOG_METRICS", True)):
        return False
    try:
        rate = float(getattr(config, "CACHE_LOG_SAMPLE_RATE", 1.0))
    except Exception:
        rate = 1.0
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate
