using Shop;
using Xunit;

namespace Shop.Tests;

public class FormatTests
{
    [Fact]
    public void ShowsCentsAsEurosWithTwoDecimals()
    {
        Assert.Equal("12.50", Pricing.FormatPrice(1250));
    }
}
