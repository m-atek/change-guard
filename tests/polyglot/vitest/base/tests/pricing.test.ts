import { describe, expect, it } from "vitest";
import { total } from "../src/pricing";

describe("total", () => {
  it("multiplies the unit price by the quantity", () => {
    expect(total(250, 4)).toBe(1000);
  });
});
