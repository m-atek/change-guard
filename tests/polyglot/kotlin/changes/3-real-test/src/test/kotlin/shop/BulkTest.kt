package shop

import kotlin.test.Test
import kotlin.test.assertEquals

class BulkTest {
    @Test
    fun leavesASmallOrderAtFullPrice() {
        assertEquals(500L, Pricing.total(250, 2))
    }

    @Test
    fun givesTenItemsTenPercentOff() {
        assertEquals(9000L, Pricing.total(1000, 10))
    }
}
