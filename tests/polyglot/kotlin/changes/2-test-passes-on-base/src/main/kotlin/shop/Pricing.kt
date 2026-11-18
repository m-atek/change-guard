// Demo project, no real data.
package shop

object Pricing {
    /** The price of an order line in cents; ten items or more get 10% off. */
    fun total(unitCents: Long, quantity: Int): Long {
        val gross = unitCents * quantity
        return if (quantity >= 10) gross * 9 / 10 else gross
    }
}
