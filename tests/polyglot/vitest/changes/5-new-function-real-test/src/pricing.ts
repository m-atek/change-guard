// Demo project, no real data.

/** The price of an order line in cents. */
export function total(unitCents: number, quantity: number): number {
  return unitCents * quantity;
}

/** A price in cents as euros with two decimals, for example 12.50. */
export function formatPrice(cents: number): string {
  return (cents / 100).toFixed(2);
}
