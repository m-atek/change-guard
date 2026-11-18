package shop;

import org.junit.jupiter.api.Test;

class FormatTest {
    @Test
    void formatsAPrice() {
        Pricing.formatPrice(1250);
    }
}
