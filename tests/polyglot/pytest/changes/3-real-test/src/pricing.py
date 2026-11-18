# Demo project, no real data.


def total(unit_cents, quantity):
    """The price of an order line in cents; ten items or more get 10% off."""
    gross = unit_cents * quantity
    return gross * 9 // 10 if quantity >= 10 else gross
