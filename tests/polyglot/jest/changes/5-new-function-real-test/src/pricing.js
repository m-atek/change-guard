// Demo project, no real data.

/** The price of an order line in cents. */
function total(unitCents, quantity) {
  return unitCents * quantity;
}

/** A price in cents as euros with two decimals, for example 12.50. */
function formatPrice(cents) {
  return (cents / 100).toFixed(2);
}

module.exports = { total, formatPrice };
