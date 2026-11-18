// Demo project, no real data.
package shop

object Pricing {
    /** The price of an order line in cents. */
    fun total(unitCents: Long, quantity: Int): Long {
        return unitCents * quantity
    }
}
