import Testing
@testable import Shop

struct BulkTests {
    @Test func leavesASmallOrderAtFullPrice() {
        #expect(Pricing.total(250, 2) == 500)
    }
}
