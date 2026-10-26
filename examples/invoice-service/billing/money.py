from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value) -> Decimal:
    """Round a value to whole cents using commercial (half-up) rounding."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
