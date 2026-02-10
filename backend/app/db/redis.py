import redis

from ..core.config import config


_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(config.REDIS_URL)
    return _redis_client


def get_redis_status() -> bool:
    """Return True if Redis responds to PING."""

    try:
        client = get_redis()
        return bool(client.ping())
    except Exception:
        return False
