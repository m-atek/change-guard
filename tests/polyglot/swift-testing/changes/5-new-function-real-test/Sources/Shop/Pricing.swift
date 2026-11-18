// Demo project, no real data.

public enum Pricing {
    /// The price of an order line in cents.
    public static func total(_ unitCents: Int, _ quantity: Int) -> Int {
        return unitCents * quantity
    }

    /// A price in cents as euros with two decimals, for example 12.50.
    public static func formatPrice(_ cents: Int) -> String {
        let rest = cents % 100
        return "\(cents / 100)." + (rest < 10 ? "0" : "") + "\(rest)"
    }
}
