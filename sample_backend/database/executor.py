"""Runs SQL queries with a timeout."""
import psycopg2

from config import QUERY_TIMEOUT_SEC
from database.pool import acquire, release

TIMEOUT = QUERY_TIMEOUT_SEC


class QueryTimeoutError(Exception):
    pass


def run_query(sql: str, params: tuple = ()) -> list:
    """Execute a SQL statement and return the rows as dicts.

    When the statement times out, the raise skips release(conn), so the connection
    is never returned to the pool.
    """
    conn = acquire()
    cur = conn.cursor()
    cur.execute(f"SET statement_timeout = {TIMEOUT * 1000}")
    try:
        cur.execute(sql, params)
    except psycopg2.errors.QueryCanceled:
        raise QueryTimeoutError(f"Query exceeded {TIMEOUT}s limit — consider adding an index")
    cols = [c.name for c in cur.description] if cur.description else []
    rows = [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []
    conn.commit()
    release(conn)
    return rows


def search_orders(customer_email: str) -> list:
    """Find all orders for a customer email. lower() on the column prevents index use, so this scans the whole orders table."""
    return run_query("SELECT * FROM orders WHERE lower(customer_email) = lower(%s)", (customer_email,))
