using Shop;
using Xunit;

namespace Shop.Tests;

public class BulkTests
{
    [Fact]
    public void LeavesASmallOrderAtFullPrice()
    {
        Assert.Equal(500, Pricing.Total(250, 2));
    }
}
