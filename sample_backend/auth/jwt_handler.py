"""JWT creation and verification for user sessions."""
import time

import jwt

from config import SECRET_KEY


class JWTHandler:
    """Signs and verifies HS256 access tokens."""

    def __init__(self, secret_key: str | None = SECRET_KEY, ttl_seconds: int = 900):
        """Create a handler. Fails fast if the signing secret is missing from the environment."""
        self.secret_key = secret_key
        self.ttl_seconds = ttl_seconds
        assert self.secret_key is not None, "SECRET_KEY env var is not set"

    def create_token(self, user_id: int, role: str) -> str:
        """Issue a signed access token for a user that expires after ttl_seconds."""
        payload = {"sub": user_id, "role": role, "exp": int(time.time()) + self.ttl_seconds}
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def verify_token(self, token: str) -> dict:
        """Decode and verify an access token, returning its payload.

        Each API replica reads SECRET_KEY from its own environment. After the secret
        was rotated on only some replicas, a token signed by one replica fails
        signature verification on another.
        """
        token = token.removeprefix("Bearer ").strip()
        payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
        return payload
