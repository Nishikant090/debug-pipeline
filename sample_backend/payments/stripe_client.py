"""Stripe payment calls."""
import requests

from config import STRIPE_KEY, STRIPE_URL


class PaymentDeclined(Exception):
    pass


def create_payment_intent(amount_cents: int, currency: str = "usd") -> dict:
    """Create a Stripe PaymentIntent. There is no retry and no idempotency key, so a timeout leaves the order unpaid with no record of whether Stripe created the intent."""
    response = requests.post(
        STRIPE_URL,
        data={"amount": amount_cents, "currency": currency},
        headers={"Authorization": f"Bearer {STRIPE_KEY}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def charge_card(payment_intent_id: str, payment_method: str) -> dict:
    """Confirm a PaymentIntent with the customer's card. Raises PaymentDeclined when the bank refuses."""
    resp = requests.post(
        f"{STRIPE_URL}/{payment_intent_id}/confirm",
        data={"payment_method": payment_method},
        headers={"Authorization": f"Bearer {STRIPE_KEY}"},
        timeout=10,
    )
    body = resp.json()
    if resp.status_code == 402:
        stripe_error = type("StripeError", (), body["error"])
        raise PaymentDeclined(f"Card declined: {stripe_error.code}")
    return body
