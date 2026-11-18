// Demo project, no real data.
package shop;

import java.util.Locale;

public final class Pricing {
    private Pricing() {
    }

    /** The price of an order line in cents. */
    public static long total(long unitCents, int quantity) {
        return unitCents * quantity;
    }

    /** A price in cents as euros with two decimals, for example 12.50. */
    public static String formatPrice(long cents) {
        return String.format(Locale.ROOT, "%d.%02d", cents / 100, cents % 100);
    }
}
