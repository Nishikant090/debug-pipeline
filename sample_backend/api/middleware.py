"""Request middleware for the API gateway."""
import logging

from auth.jwt_handler import JWTHandler

logger = logging.getLogger(__name__)
jwt_handler = JWTHandler()
PUBLIC_PATHS = {"/health", "/auth/login", "/products"}


class AuthMiddleware:
    """Attaches the logged-in user to each request and writes an audit log line."""

    def dispatch(self, request, call_next):
        """Resolve request.user from the bearer token, then call the endpoint.

        For public paths request.user is left as None, but the audit log line still
        reads request.user.user_id for every request.
        """
        if request.url.path not in PUBLIC_PATHS:
            payload = jwt_handler.verify_token(request.headers.get("Authorization", ""))
            request.user = type("User", (), {"user_id": payload["sub"], "role": payload["role"]})
        else:
            request.user = None
        user_id = request.user.user_id
        logger.info("request path=%s user=%s", request.url.path, user_id)
        return call_next(request)
