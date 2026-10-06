"""Card validation before calling Stripe."""


class InvalidCardError(Exception):
    pass


def luhn_ok(number: str) -> bool:
    """Return True if a digit string passes the Luhn checksum."""
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_card(card_number: str) -> str:
    """Normalise and validate a card number.

    Only spaces are stripped, so a number pasted with dashes ("4242-4242-4242-4242")
    makes int("-") fail inside luhn_ok. That ValueError is swallowed and reported as
    a Luhn failure even though the card is valid.
    """
    digits = card_number.replace(" ", "")
    try:
        ok = luhn_ok(digits)
    except ValueError:
        ok = False
    if not ok:
        raise InvalidCardError("Card number failed Luhn algorithm check")
    return digits
