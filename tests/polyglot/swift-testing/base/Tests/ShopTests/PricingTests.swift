import Testing
@testable import Shop

struct PricingTests {
    @Test func multipliesTheUnitPriceByTheQuantity() {
        #expect(Pricing.total(250, 4) == 1000)
    }
}
