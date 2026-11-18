package shop

import "testing"

func TestTotalMultipliesTheUnitPrice(t *testing.T) {
	if got := Total(250, 4); got != 1000 {
		t.Errorf("Total(250, 4) = %d, want 1000", got)
	}
}
