from src.pricing import total


def test_multiplies_the_unit_price_by_the_quantity():
    assert total(250, 4) == 1000
