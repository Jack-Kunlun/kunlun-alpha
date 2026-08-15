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
  it("keeps PRECIOUS_METALS separate from GOLD, SILVER and OTHER commodities", () => {
    for (const fixture of data.valid) {
      expect(fixture.fund.fundAssetClass).toBe("PRECIOUS_METALS");
      expect(["GOLD", "SILVER", "OTHER"]).toContain(fixture.fund.underlyingCommodity);
    }
  });
});

describe("precious-metals contract semantics", () => {
  const validMetadata = {
    unifiedCode: "518880.SH",
    exchange: "SH",
    assetType: "ETF",
    fundAssetClass: "PRECIOUS_METALS",
    underlyingCommodity: "GOLD",
    tradingCurrency: "CNY",
    navCurrency: "CNY",
    benchmarkOrTrackingIndex: "Au99.99",
    managementFeeRate: 0.005,
    validFrom: "2020-01-01",
    validTo: null,
    source: "provider-x",
    publishTime: "2026-08-13T09:00:00Z",
    ingestTime: "2026-08-13T09:01:00Z",
    availableTime: "2026-08-13T09:02:00Z",
    processingTime: "2026-08-13T09:03:00Z",
    rawObjectId: "sha256:classification",
    confidence: 0.95,
    reviewStatus: "REVIEWED",
  };

  it("accepts explicit classification with separate currencies and review provenance", () => {
    const result = validatePreciousMetalFund(validMetadata as never);
    expect(result).toEqual({ valid: true, errors: [] });
  });

  it("rejects commodity values used as the fund asset class", () => {
    const result = validatePreciousMetalFund({
      ...validMetadata,
      fundAssetClass: "GOLD",
    } as never);
    expect(result.valid).toBe(false);
  });

  it("rejects missing provenance, invalid confidence, and reversed validity windows", () => {
    const result = validatePreciousMetalFund({
      ...validMetadata,
      source: "",
      confidence: 1.1,
      validFrom: "2025-01-01",
      validTo: "2024-01-01",
    } as never);
    expect(result.valid).toBe(false);
    expect(result.errors).toEqual(
      expect.arrayContaining([
        "source must be non-empty",
        "confidence must be between 0 and 1",
        "validFrom must be <= validTo",
      ]),
    );
  });

  it("rejects classification evidence that was unavailable at the decision time", () => {
    const validateWithDecision = validatePreciousMetalFund as unknown as (
      fund: never,
      options?: { decisionTime?: string },
    ) => { valid: boolean; errors: string[] };
    const result = validateWithDecision(
      {
        ...validMetadata,
        publishTime: "2026-08-14T09:00:00Z",
        ingestTime: "2026-08-14T09:01:00Z",
        availableTime: "2026-08-14T09:02:00Z",
        processingTime: "2026-08-14T09:03:00Z",
        rawObjectId: "sha256:classification",
      } as never,
      { decisionTime: "2026-08-13T12:00:00Z" },
    );
    expect(result.valid).toBe(false);
  });

  it("rejects a suffix code whose exchange field disagrees", () => {
    const result = validatePreciousMetalFund({
      ...validMetadata,
      exchange: "SZ",
    } as never);
    expect(result.valid).toBe(false);
  });
});
