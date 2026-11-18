from src.pricing import format_price


def test_format_price_shows_two_decimals():
    assert format_price(1250) == "12.50"
