import XCTest
@testable import Shop

final class BulkTests: XCTestCase {
    func testLeavesASmallOrderAtFullPrice() {
        XCTAssertEqual(Pricing.total(250, 2), 500)
    }
}
