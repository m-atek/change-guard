// Demo project, no real data.
using System.Globalization;

namespace Shop;

public static class Pricing
{
    /// <summary>The price of an order line in cents.</summary>
    public static long Total(long unitCents, int quantity)
    {
        return unitCents * quantity;
    }

    /// <summary>A price in cents as euros with two decimals, for example 12.50.</summary>
    public static string FormatPrice(long cents)
    {
        return (cents / 100m).ToString("0.00", CultureInfo.InvariantCulture);
    }
}
