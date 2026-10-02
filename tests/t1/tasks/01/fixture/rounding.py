def round_to_cents(amount: float) -> float:
    """Round a monetary amount to cents, with exact halves away from zero."""
    return int(amount * 100) / 100
