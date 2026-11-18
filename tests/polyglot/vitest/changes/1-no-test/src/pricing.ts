// Demo project, no real data.

/** The price of an order line in cents; ten items or more get 10% off. */
export function total(unitCents: number, quantity: number): number {
  const gross = unitCents * quantity;
  return quantity >= 10 ? Math.round(gross * 0.9) : gross;
}
