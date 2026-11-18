package shop;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class BulkTest {
    @Test
    void leavesASmallOrderAtFullPrice() {
        assertEquals(500, Pricing.total(250, 2));
    }
}
