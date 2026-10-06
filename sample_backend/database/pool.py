"""PostgreSQL connection pool."""
import queue

import psycopg2

from config import DB_PARAMS, MAX_POOL

_pool = queue.Queue(maxsize=MAX_POOL)
_created = 0


class PoolExhausted(Exception):
    pass


def get_connection():
    """Open a brand-new PostgreSQL connection using DB_PARAMS. No retry if the server is down or restarting."""
    conn = psycopg2.connect(**DB_PARAMS, connect_timeout=5)
    return conn


def acquire(timeout: float = 2.0):
    """Borrow a connection from the pool, creating one while the pool is not yet full.

    Callers must call release() when done. run_query() skips release() when a query
    times out, so every timed-out query leaks one connection until all MAX_POOL
    connections are gone.
    """
    global _created
    try:
        return _pool.get_nowait()
    except queue.Empty:
        if _created < MAX_POOL:
            _created += 1
            return get_connection()
    try:
        return _pool.get(timeout=timeout)
    except queue.Empty:
        raise PoolExhausted(f"All {MAX_POOL} connections are in use")


def release(conn) -> None:
    """Return a connection to the pool."""
    _pool.put_nowait(conn)
