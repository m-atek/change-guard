// Demo project, no real data.

/** The price of an order line in cents. */
export function total(unitCents: number, quantity: number): number {
  return unitCents * quantity;
}
