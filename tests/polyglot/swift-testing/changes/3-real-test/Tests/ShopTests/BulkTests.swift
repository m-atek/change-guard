import Testing
@testable import Shop

struct BulkTests {
    @Test func leavesASmallOrderAtFullPrice() {
        #expect(Pricing.total(250, 2) == 500)
    }

    @Test func givesTenItemsTenPercentOff() {
        #expect(Pricing.total(1000, 10) == 9000)
    }
}
