import { describe, it } from "vitest";
import { formatPrice } from "../src/pricing";

describe("format price", () => {
  it("formats a price", () => {
    formatPrice(1250);
  });
});
