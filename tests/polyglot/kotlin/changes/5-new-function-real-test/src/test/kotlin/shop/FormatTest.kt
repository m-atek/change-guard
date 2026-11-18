package shop

import kotlin.test.Test
import kotlin.test.assertEquals

class FormatTest {
    @Test
    fun showsCentsAsEurosWithTwoDecimals() {
        assertEquals("12.50", Pricing.formatPrice(1250))
    }
}
