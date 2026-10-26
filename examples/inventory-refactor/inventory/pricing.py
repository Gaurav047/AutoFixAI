BULK_TIERS = [(100, 0.15), (50, 0.10), (10, 0.05)]


def bulk_price(quantity: int, unit_price: float) -> float:
    """Total price for `quantity` units, with the best bulk discount tier applied.

    v2.0: argument order changed to (quantity, unit_price) to match the order API.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    discount = next((pct for threshold, pct in BULK_TIERS if quantity >= threshold), 0.0)
    return round(quantity * unit_price * (1 - discount), 2)
