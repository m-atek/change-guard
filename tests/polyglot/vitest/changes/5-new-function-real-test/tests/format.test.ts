import { describe, expect, it } from "vitest";
import { formatPrice } from "../src/pricing";

describe("format price", () => {
  it("shows cents as euros with two decimals", () => {
    expect(formatPrice(1250)).toBe("12.50");
  });
});
