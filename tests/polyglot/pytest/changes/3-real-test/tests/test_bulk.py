from src.pricing import total


def test_bulk_leaves_a_small_order_at_full_price():
    assert total(250, 2) == 500


def test_bulk_gives_ten_items_ten_percent_off():
    assert total(1000, 10) == 9000
