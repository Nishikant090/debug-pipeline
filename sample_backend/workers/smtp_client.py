"""SMTP sending."""
import smtplib


class SMTPClient:
    """Keeps one SMTP connection open for the whole worker process."""

    def __init__(self, host: str = "smtp.mailprovider.com", port: int = 587):
        """Connect to the mail server once, when the worker starts."""
        self.server = smtplib.SMTP(host, port)
        self.server.starttls()

    def send(self, msg) -> dict:
        """Send an email on the shared connection.

        The provider closes connections that are idle for 5 minutes and nothing
        reconnects, so the first email after a quiet period fails mid-send.
        """
        try:
            return self.server.send_message(msg)
        except smtplib.SMTPServerDisconnected:
            raise smtplib.SMTPServerDisconnected("Connection to SMTP server lost mid-send")
