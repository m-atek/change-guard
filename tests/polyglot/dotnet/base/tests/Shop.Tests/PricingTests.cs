using Shop;
using Xunit;

namespace Shop.Tests;

public class PricingTests
{
    [Fact]
    public void MultipliesTheUnitPriceByTheQuantity()
    {
        Assert.Equal(1000, Pricing.Total(250, 4));
    }
}
