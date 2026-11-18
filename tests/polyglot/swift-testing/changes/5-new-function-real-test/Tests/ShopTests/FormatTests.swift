import Testing
@testable import Shop

struct FormatTests {
    @Test func showsCentsAsEurosWithTwoDecimals() {
        #expect(Pricing.formatPrice(1250) == "12.50")
    }
}
