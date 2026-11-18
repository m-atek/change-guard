const { total } = require("../src/pricing");

describe("bulk discount", () => {
  test("leaves a small order at full price", () => {
    expect(total(250, 2)).toBe(500);
  });

  test("gives ten items 10% off", () => {
    expect(total(1000, 10)).toBe(9000);
  });
});
