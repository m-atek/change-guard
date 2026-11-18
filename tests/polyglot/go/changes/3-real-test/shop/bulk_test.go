package shop

import "testing"

func TestBulkSmallOrderAtFullPrice(t *testing.T) {
	if got := Total(250, 2); got != 500 {
		t.Errorf("Total(250, 2) = %d, want 500", got)
	}
}

func TestBulkTenItemsTenPercentOff(t *testing.T) {
	if got := Total(1000, 10); got != 9000 {
		t.Errorf("Total(1000, 10) = %d, want 9000", got)
	}
}
