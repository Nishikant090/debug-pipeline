"""Role-based access control."""
from functools import wraps

ROLE_ORDER = ["viewer", "editor", "admin"]


class PermissionDenied(Exception):
    pass


def require_role(required_role: str):
    """Decorator: allow the endpoint only for users whose role is at least required_role.

    The role is read from the JWT, which is only issued at login, so a user who was
    just promoted keeps getting denied until they log out and back in.
    """
    def decorator(handler):
        @wraps(handler)
        def wrapper(request, *args, **kwargs):
            user_role = request.token_payload.get("role", "viewer")
            if ROLE_ORDER.index(user_role) < ROLE_ORDER.index(required_role):
                raise PermissionDenied(f'Role "{required_role}" required but user has "{user_role}"')
            return handler(request, *args, **kwargs)
        return wrapper
    return decorator
