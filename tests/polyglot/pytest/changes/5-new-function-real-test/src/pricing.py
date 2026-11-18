# Demo project, no real data.


def total(unit_cents, quantity):
    """The price of an order line in cents."""
    return unit_cents * quantity


def format_price(cents):
    """A price in cents as euros with two decimals, for example 12.50."""
    return "%d.%02d" % (cents // 100, cents % 100)
