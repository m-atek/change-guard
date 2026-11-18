# Demo project, no real data.

module Shop
  # Prices order lines.
  module Pricing
    # The price of an order line in cents; ten items or more get 10% off.
    def self.total(unit_cents, quantity)
      gross = unit_cents * quantity
      quantity >= 10 ? gross * 9 / 10 : gross
    end
  end
end
