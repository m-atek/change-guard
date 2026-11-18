// Demo project, no real data.
package shop

object Pricing {
    /** The price of an order line in cents. */
    fun total(unitCents: Long, quantity: Int): Long {
        return unitCents * quantity
    }

    /** A price in cents as euros with two decimals, for example 12.50. */
    fun formatPrice(cents: Long): String {
        return "${cents / 100}." + (cents % 100).toString().padStart(2, '0')
    }
}
