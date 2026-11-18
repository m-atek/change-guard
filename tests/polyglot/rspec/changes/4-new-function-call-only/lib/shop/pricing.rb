# Demo project, no real data.

module Shop
  # Prices order lines.
  module Pricing
    # The price of an order line in cents.
    def self.total(unit_cents, quantity)
      unit_cents * quantity
    end

    # A price in cents as euros with two decimals, for example 12.50.
    def self.format_price(cents)
      format("%d.%02d", cents / 100, cents % 100)
    end
  end
end
