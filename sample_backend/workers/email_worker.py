"""Celery task that sends order emails."""
from celery import shared_task

from workers.smtp_client import SMTPClient

smtp_client = SMTPClient()


@shared_task(bind=True)
def send_email_task(self, msg):
    """Send a transactional email (order confirmation, password reset). The SMTP error is not caught or retried, so it kills the worker process."""
    result = smtp_client.send(msg)
    return result
