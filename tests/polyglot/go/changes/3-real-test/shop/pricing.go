// Demo project, no real data.

// Package shop prices order lines.
package shop

// Total is the price of an order line in cents; ten items or more get 10% off.
func Total(unitCents int64, quantity int64) int64 {
	gross := unitCents * quantity
	if quantity >= 10 {
		return gross * 9 / 10
	}
	return gross
}
