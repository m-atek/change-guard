// Demo project, no real data.

/** The price of an order line in cents; ten items or more get 10% off. */
function total(unitCents, quantity) {
  const gross = unitCents * quantity;
  return quantity >= 10 ? Math.round(gross * 0.9) : gross;
}

module.exports = { total };
