// Demo project, no real data.
package shop;

public final class Pricing {
    private Pricing() {
    }

    /** The price of an order line in cents. */
    public static long total(long unitCents, int quantity) {
        return unitCents * quantity;
    }
}
