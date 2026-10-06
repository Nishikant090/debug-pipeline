"""Celery task that fulfils paid orders."""
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

from database.transactions import transfer_stock


@shared_task(bind=True, max_retries=3, default_retry_delay=1)
def process_order_task(self, order: dict):
    """Reserve stock for a paid order, retrying on failure.

    Retries are only 1 second apart, too soon for the deadlock or pool exhaustion
    that caused the failure to clear, so all 3 retries fail the same way.
    """
    try:
        transfer_stock(order["product_ids"], order["warehouse_id"])
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            raise MaxRetriesExceededError("Task failed after 3 retries — sending to dead-letter queue")
        raise self.retry(exc=exc)
