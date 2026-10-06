"""Login brute-force protection."""
from cache.redis_client import RedisClient

MAX_ATTEMPTS = 5
LOCK_WINDOW_SEC = 900
cache = RedisClient()


class AccountLockedException(Exception):
    pass


def record_failed_login(email: str) -> int:
    """Increment the failed-login counter for an email and return the new count."""
    key = f"login_fail:{email}"
    count = cache.incr(key)
    cache.expire(key, LOCK_WINDOW_SEC)
    return count


def check_login_attempts(email: str) -> None:
    """Block the login if the account has too many recent failed attempts.

    record_failed_login() pushes the expiry forward on every failure and a
    successful login never clears the counter, so a user who keeps mistyping stays
    locked out far longer than LOCK_WINDOW_SEC.
    """
    attempts = int(cache.get(f"login_fail:{email}") or 0)
    if attempts >= MAX_ATTEMPTS:
        raise AccountLockedException(f"Account locked after {MAX_ATTEMPTS} failed attempts")
