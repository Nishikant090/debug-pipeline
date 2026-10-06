"""HTTP endpoints."""
from fastapi import APIRouter

from auth.auth_service import login_user
from payments.stripe_client import charge_card, create_payment_intent
from payments.validator import validate_card

router = APIRouter()


@router.post("/auth/login")
def login(body: dict):
    """Log a user in with email and password."""
    return login_user(body["email"], body["password"])


@router.post("/checkout")
def checkout(body: dict):
    """Validate the card, create a Stripe PaymentIntent and charge it."""
    validate_card(body["card_number"])
    intent = create_payment_intent(body["amount_cents"])
    return charge_card(intent["id"], body["payment_method"])
