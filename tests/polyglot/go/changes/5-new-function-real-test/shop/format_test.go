package shop

import "testing"

func TestFormatPriceShowsTwoDecimals(t *testing.T) {
	if got := FormatPrice(1250); got != "12.50" {
		t.Errorf("FormatPrice(1250) = %q, want \"12.50\"", got)
	}
}
