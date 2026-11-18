import XCTest
@testable import Shop

final class FormatTests: XCTestCase {
    func testShowsCentsAsEurosWithTwoDecimals() {
        XCTAssertEqual(Pricing.formatPrice(1250), "12.50")
    }
}
