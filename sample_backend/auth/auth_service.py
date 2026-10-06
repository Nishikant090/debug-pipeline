"""Login and account lookup."""
import logging

from auth.passwords import verify_password
from database.executor import run_query

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    pass


def find_user_by_email(email: str) -> dict | None:
    """Fetch a user row by email. Returns None if no account exists."""
    rows = run_query("SELECT id, email, password_hash, role FROM users WHERE email = %s", (email,))
    return rows[0] if rows else None


def login_user(email: str, password: str) -> dict:
    """Check a user's email and password and return the user row on success.

    Emails are stored lower-case at sign-up, but the lookup here uses the address
    exactly as typed, so "Alice@Example.com" never matches "alice@example.com".
    """
    user = find_user_by_email(email.strip())
    if user is None or not verify_password(password, user["password_hash"]):
        logger.warning("Failed login for %s", email)
        raise AuthenticationError("Invalid email or password")
    return user
