"""Thin wrapper around redis-py."""
import redis

from config import REDIS_URL


class RedisClient:
    """Redis wrapper used for sessions, rate limits and cached objects."""

    def __init__(self, url: str = REDIS_URL):
        """Create the client. REDIS_URL defaults to localhost, which is wrong inside Docker, where the host is 'redis'."""
        self._client = redis.Redis.from_url(url, socket_connect_timeout=2)

    def get(self, key: str):
        """Read a key. Connection errors propagate to the caller instead of being treated as a cache miss."""
        return self._client.get(key)

    def set(self, key: str, value, ttl=None) -> None:
        """Write a key with an optional TTL in seconds."""
        self._client.set(key, value, ex=ttl)

    def incr(self, key: str) -> int:
        """Atomically increment a counter."""
        return self._client.incr(key)

    def expire(self, key: str, seconds: int) -> None:
        """Set a key's time to live."""
        self._client.expire(key, seconds)
