package shop

import kotlin.test.Test
import kotlin.test.assertEquals

class BulkTest {
    @Test
    fun leavesASmallOrderAtFullPrice() {
        assertEquals(500L, Pricing.total(250, 2))
    }
}
