// Demo project, no real data.
namespace Shop;

public static class Pricing
{
    /// <summary>The price of an order line in cents; ten items or more get 10% off.</summary>
    public static long Total(long unitCents, int quantity)
    {
        long gross = unitCents * quantity;
        return quantity >= 10 ? gross * 9 / 10 : gross;
    }
}
