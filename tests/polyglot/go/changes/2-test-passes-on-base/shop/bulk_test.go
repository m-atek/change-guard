package shop

import "testing"

func TestBulkSmallOrderAtFullPrice(t *testing.T) {
	if got := Total(250, 2); got != 500 {
		t.Errorf("Total(250, 2) = %d, want 500", got)
	}
}
