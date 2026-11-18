import XCTest
@testable import Shop

final class PricingTests: XCTestCase {
    func testMultipliesTheUnitPriceByTheQuantity() {
        XCTAssertEqual(Pricing.total(250, 4), 1000)
    }
}
