package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class FormatTest {
    @Test
    void showsCentsAsEurosWithTwoDecimals() {
        assertEquals("12.50", Pricing.formatPrice(1250));
    }
}
