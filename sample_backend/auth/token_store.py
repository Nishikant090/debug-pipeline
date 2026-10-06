"""Refresh-token storage."""
from cache.redis_client import RedisClient

store = RedisClient()


class TokenRevokedException(Exception):
    pass


def save_refresh_token(token: str, user_id: int) -> None:
    """Remember a refresh token for 7 days."""
    store.set(f"refresh:{token}", str(user_id), ttl=7 * 24 * 3600)


def validate_refresh_token(token: str) -> int:
    """Return the user id for a refresh token, or raise if it is unknown or revoked.

    Tokens live only in Redis with no persistence, so a Redis restart or memory
    eviction silently logs every user out: their tokens are no longer in the store.
    """
    user_id = store.get(f"refresh:{token}")
    if user_id is None:
        raise TokenRevokedException("Refresh token not found in store — may have been revoked")
    return int(user_id)
