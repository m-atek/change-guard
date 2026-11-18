# Demo project, no real data.

module Shop
  # Prices order lines.
  module Pricing
    # The price of an order line in cents.
    def self.total(unit_cents, quantity)
      unit_cents * quantity
    end
  end
end
