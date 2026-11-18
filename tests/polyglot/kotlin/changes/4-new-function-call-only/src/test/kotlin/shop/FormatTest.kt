package shop

import kotlin.test.Test

class FormatTest {
    @Test
    fun formatsAPrice() {
        Pricing.formatPrice(1250)
    }
}
