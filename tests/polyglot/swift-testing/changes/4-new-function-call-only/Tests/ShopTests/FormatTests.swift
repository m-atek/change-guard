import Testing
@testable import Shop

struct FormatTests {
    @Test func formatsAPrice() {
        _ = Pricing.formatPrice(1250)
    }
}
