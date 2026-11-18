const { formatPrice } = require("../src/pricing");

describe("format price", () => {
  test("shows cents as euros with two decimals", () => {
    expect(formatPrice(1250)).toBe("12.50");
  });
});
