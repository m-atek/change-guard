import XCTest
@testable import Shop

final class BulkTests: XCTestCase {
    func testLeavesASmallOrderAtFullPrice() {
        XCTAssertEqual(Pricing.total(250, 2), 500)
    }

    func testGivesTenItemsTenPercentOff() {
        XCTAssertEqual(Pricing.total(1000, 10), 9000)
    }
}
