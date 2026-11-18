import XCTest
@testable import Shop

final class FormatTests: XCTestCase {
    func testFormatsAPrice() {
        _ = Pricing.formatPrice(1250)
    }
}
