"""Per-client API rate limiting."""
from cache.redis_client import RedisClient

LIMIT = 100
cache = RedisClient()


class RateLimitError(Exception):
    pass


def check_rate(client_ip: str) -> None:
    """Allow at most LIMIT requests per minute per client IP.

    Behind the load balancer every request arrives from the balancer's IP (the
    X-Forwarded-For header is ignored), so all users share one bucket and the
    whole site hits the limit together.
    """
    key = f"rate:{client_ip}"
    count = cache.incr(key)
    if count == 1:
        cache.expire(key, 60)
    if count > LIMIT:
        raise RateLimitError(f"Client exceeded {LIMIT} requests per minute")
