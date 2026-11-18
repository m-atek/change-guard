// Demo project, no real data.
package shop;

public final class Pricing {
    private Pricing() {
    }

    /** The price of an order line in cents; ten items or more get 10% off. */
    public static long total(long unitCents, int quantity) {
        long gross = unitCents * quantity;
        return quantity >= 10 ? Math.round(gross * 0.9) : gross;
    }
}
