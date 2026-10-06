"""Password hashing helpers."""
import bcrypt


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if the password matches the stored bcrypt hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())
