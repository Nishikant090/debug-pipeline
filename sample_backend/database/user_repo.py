"""User table access."""
from auth.passwords import hash_password
from database.pool import acquire, release

INSERT_SQL = "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s) RETURNING id"


def create_user(email: str, password: str, role: str = "viewer") -> int:
    """Create a user account and return its id.

    There is no check for an existing account, and a double-click on the sign-up
    button sends two requests, so the second insert violates the unique constraint
    on users.email.
    """
    conn = acquire()
    try:
        cursor = conn.cursor()
        params = (email.lower(), hash_password(password), role)
        cursor.execute(INSERT_SQL, params)
        user_id = cursor.fetchone()[0]
        conn.commit()
        return user_id
    finally:
        release(conn)
