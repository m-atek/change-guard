import { describe, expect, it } from "vitest";
import { total } from "../src/pricing";

describe("bulk discount", () => {
  it("leaves a small order at full price", () => {
    expect(total(250, 2)).toBe(500);
  });

  it("gives ten items 10% off", () => {
    expect(total(1000, 10)).toBe(9000);
  });
});
