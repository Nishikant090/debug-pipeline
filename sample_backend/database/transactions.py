"""Multi-statement transactions."""
import psycopg2

from database.pool import acquire, release


class DeadlockError(Exception):
    pass


def execute_transaction(statements: list) -> None:
    """Run several (sql, params) statements atomically.

    Checkout locks stock rows in cart order while the nightly restock job locks them
    in product-id order, so two transactions touching the same products can each
    wait for a row the other holds.
    """
    conn = acquire()
    try:
        with conn.cursor() as cur:
            for sql, params in statements:
                cur.execute(sql, params)
        conn.commit()
    except psycopg2.errors.DeadlockDetected:
        conn.rollback()
        raise DeadlockError("Deadlock detected between transactions T1 and T2")
    finally:
        release(conn)


def transfer_stock(product_ids: list, warehouse_id: int) -> None:
    """Reserve stock for every product in a cart, locking rows in the order given."""
    execute_transaction([
        ("UPDATE stock SET reserved = reserved + 1 WHERE product_id = %s AND warehouse_id = %s", (pid, warehouse_id))
        for pid in product_ids
    ])
