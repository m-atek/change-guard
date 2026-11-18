from src.pricing import total


def test_bulk_leaves_a_small_order_at_full_price():
    assert total(250, 2) == 500
