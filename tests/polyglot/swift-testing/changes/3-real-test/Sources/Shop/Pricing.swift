// Demo project, no real data.

public enum Pricing {
    /// The price of an order line in cents; ten items or more get 10% off.
    public static func total(_ unitCents: Int, _ quantity: Int) -> Int {
        let gross = unitCents * quantity
        return quantity >= 10 ? gross * 9 / 10 : gross
    }
}
