import { describe, expect, it } from "vitest";
import { total } from "../src/pricing";

describe("bulk discount", () => {
  it("leaves a small order at full price", () => {
    expect(total(250, 2)).toBe(500);
  });
});
