from decimal import Decimal, ROUND_HALF_UP


def round_to_cents(amount: float) -> float:
    """Round a monetary amount to cents, with exact halves away from zero."""
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(value)
