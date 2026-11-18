// Demo project, no real data.

// Package shop prices order lines.
package shop

// Total is the price of an order line in cents.
func Total(unitCents int64, quantity int64) int64 {
	return unitCents * quantity
}
