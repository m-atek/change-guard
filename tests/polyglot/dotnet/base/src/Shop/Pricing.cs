// Demo project, no real data.
namespace Shop;

public static class Pricing
{
    /// <summary>The price of an order line in cents.</summary>
    public static long Total(long unitCents, int quantity)
    {
        return unitCents * quantity;
    }
}
