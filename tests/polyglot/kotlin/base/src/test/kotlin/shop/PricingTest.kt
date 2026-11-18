package shop

import kotlin.test.Test
import kotlin.test.assertEquals

class PricingTest {
    @Test
    fun multipliesTheUnitPriceByTheQuantity() {
        assertEquals(1000L, Pricing.total(250, 4))
    }
}
