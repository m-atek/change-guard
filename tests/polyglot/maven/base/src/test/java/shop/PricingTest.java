package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class PricingTest {
    @Test
    void multipliesTheUnitPriceByTheQuantity() {
        assertEquals(1000, Pricing.total(250, 4));
    }
}
