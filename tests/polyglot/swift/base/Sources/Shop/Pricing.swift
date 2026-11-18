// Demo project, no real data.

public enum Pricing {
    /// The price of an order line in cents.
    public static func total(_ unitCents: Int, _ quantity: Int) -> Int {
        return unitCents * quantity
    }
}
