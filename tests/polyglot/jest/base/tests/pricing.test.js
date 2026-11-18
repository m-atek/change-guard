const { total } = require("../src/pricing");

describe("total", () => {
  test("multiplies the unit price by the quantity", () => {
    expect(total(250, 4)).toBe(1000);
  });
});
