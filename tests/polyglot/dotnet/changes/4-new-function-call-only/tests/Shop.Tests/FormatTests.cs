using Shop;
using Xunit;

namespace Shop.Tests;

public class FormatTests
{
    [Fact]
    public void FormatsAPrice()
    {
        Pricing.FormatPrice(1250);
    }
}
