const { formatPrice } = require("../src/pricing");

describe("format price", () => {
  test("formats a price", () => {
    formatPrice(1250);
  });
});
