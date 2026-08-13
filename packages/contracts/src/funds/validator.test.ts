/**
 * Precious-metal fund validator tests, driven by the shared fixtures file.
 */

import { describe, expect, it } from "vitest";
import fixtures from "../../funds/fixtures.json";
import { validatePreciousMetalFund, type PreciousMetalFund } from "./validator";

interface NamedFund {
  name: string;
  fund: PreciousMetalFund;
}

interface InvalidFund extends NamedFund {
  reason: string;
}

const data = fixtures as unknown as {
  valid: NamedFund[];
  invalid: InvalidFund[];
};

describe("validatePreciousMetalFund valid", () => {
  it.each(data.valid.map((f) => [f.name, f] as const))("%s", (_name, fixture) => {
    const result = validatePreciousMetalFund(fixture.fund);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});

describe("validatePreciousMetalFund invalid", () => {
  it.each(data.invalid.map((f) => [f.name, f] as const))("%s", (_name, fixture) => {
    const result = validatePreciousMetalFund(fixture.fund);
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });
});

describe("classification", () => {
  it("accepts GOLD, SILVER and OTHER asset classes", () => {
    for (const fixture of data.valid) {
      expect(["GOLD", "SILVER", "OTHER"]).toContain(fixture.fund.fundAssetClass);
      expect(fixture.fund.underlyingCommodity).not.toBe("");
    }
  });
});
