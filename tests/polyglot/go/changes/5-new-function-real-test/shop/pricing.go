// Demo project, no real data.

// Package shop prices order lines.
package shop

import "fmt"

// Total is the price of an order line in cents.
func Total(unitCents int64, quantity int64) int64 {
	return unitCents * quantity
}

// FormatPrice shows a price in cents as euros with two decimals, for example 12.50.
func FormatPrice(cents int64) string {
	return fmt.Sprintf("%d.%02d", cents/100, cents%100)
}
