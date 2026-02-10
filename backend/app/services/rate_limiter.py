"""Redis-backed rate limiting utilities."""

from datetime import datetime, timedelta

from ..db.redis import get_redis


try:
    from redis.exceptions import ConnectionError as RedisConnectionError  # type: ignore[import]
except Exception:  # pragma: no cover - redis is an optional runtime dependency
    RedisConnectionError = Exception  # type: ignore[assignment]


def is_rate_limited(user_id: str, endpoint: str, limit: int, window_seconds: int) -> bool:
    r = get_redis()
    key = f"rate:{user_id}:{endpoint}"
    now = int(datetime.utcnow().timestamp())
    window_start = now - window_seconds

    try:
        with r.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, window_seconds)
            _, _, count, _ = pipe.execute()
    except RedisConnectionError:
        # If Redis is unavailable, fail open so the API stays usable in dev.
        return False

    return int(count) > limit
