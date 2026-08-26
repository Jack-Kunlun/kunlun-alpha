import { describe, expect, it } from "vitest";
import schema from "../../schemas/funds/benchmark-series-point.json";
import {
  benchmarkSeriesMatches,
  type BenchmarkSeriesPoint,
  type PreciousMetalFund,
  validateBenchmarkSeriesPoint,
  validatePreciousMetalFund,
} from "./validator";

const CANONICAL_BENCHMARK_ID = "benchmark:v1:gold:gold_cny";
const SCHEMA_VERSION = "benchmark-series-point-v1";

type BenchmarkSeriesPointInput = BenchmarkSeriesPoint & { schemaVersion: unknown };

function point(overrides: Partial<BenchmarkSeriesPointInput> = {}): BenchmarkSeriesPointInput {
  return {
    schemaVersion: SCHEMA_VERSION,
    benchmarkId: CANONICAL_BENCHMARK_ID,
    currency: "CNY",
    priceBasis: "PRICE_RETURN",
    referenceValue: "123.4500" as never,
    eventTime: "2026-08-13T09:00:00Z",
    ingestTime: "2026-08-13T09:01:00Z",
    availableTime: "2026-08-13T09:02:00Z",
    processingTime: "2026-08-13T09:03:00Z",
    source: "provider-x",
    sourceRevision: "2026-08-13-1",
    rawObjectId: "raw-benchmark-1",
    payloadDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    referenceOnly: true,
    ...overrides,
  };
}

function fund(overrides: Partial<PreciousMetalFund> = {}): PreciousMetalFund {
  return {
    unifiedCode: "518880.SH",
    exchange: "SH",
    assetType: "ETF",
    fundAssetClass: "PRECIOUS_METALS",
    underlyingCommodity: "GOLD",
    tradingCurrency: "CNY",
    navCurrency: "CNY",
    benchmarkOrTrackingIndex: "Gold display label",
    managementFeeRate: 0.005,
    validFrom: "2020-01-01",
    validTo: null,
    source: "provider-x",
    publishTime: "2026-08-13T09:00:00Z",
    ingestTime: "2026-08-13T09:01:00Z",
    availableTime: "2026-08-13T09:02:00Z",
    processingTime: "2026-08-13T09:03:00Z",
    rawObjectId: "raw-fund-1",
    confidence: 0.95,
    reviewStatus: "REVIEWED",
    ...overrides,
  };
}

describe("BenchmarkSeriesPoint v1", () => {
  it("declares canonical JSON Schema boundaries", () => {
    const properties = schema.properties as Record<string, Record<string, unknown>>;
    const schemaVersion = properties.schemaVersion!;
    const benchmarkId = properties.benchmarkId!;
    const currency = properties.currency!;
    const priceBasis = properties.priceBasis!;
    const referenceValue = properties.referenceValue!;
    const source = properties.source!;
    const sourceRevision = properties.sourceRevision!;
    const rawObjectId = properties.rawObjectId!;
    const payloadDigest = properties.payloadDigest!;
    const referenceOnly = properties.referenceOnly!;

    expect(schemaVersion).toMatchObject({ const: SCHEMA_VERSION });
    expect(benchmarkId).toMatchObject({
      type: "string",
      pattern: "^benchmark:v1:[a-z0-9][a-z0-9._-]{0,31}:[a-z0-9][a-z0-9._-]{0,127}$",
      maxLength: 174,
    });
    expect(currency).toMatchObject({ type: "string", pattern: "^[A-Z]{3}$" });
    expect(priceBasis).toMatchObject({ type: "string", minLength: 1, maxLength: 64 });
    expect(referenceValue).toMatchObject({
      type: "string",
      pattern:
        "^(?:0\\.[0-9]*[1-9][0-9]*|[1-9][0-9]*(?:\\.[0-9]+)?)$",
      "x-python-decimal": true,
    });
    for (const property of [source, sourceRevision, rawObjectId]) {
      expect(property).toMatchObject({ type: "string", minLength: 1, maxLength: 256 });
    }
    expect(payloadDigest).toMatchObject({
      type: "string",
      pattern: "^sha256:[0-9a-f]{64}$",
    });
    expect(referenceOnly).toMatchObject({
      type: "boolean",
      const: true,
      "x-python-strict": true,
    });

    const benchmarkIdPattern = new RegExp(String(benchmarkId.pattern));
    for (const value of [
      "benchmark:gold-cny",
      "Gold display label",
      " benchmark:v1:gold:key",
      "benchmark:v1:gold:key ",
      "benchmark:v1:Gold:key",
      "benchmark:v1:金:key",
      "benchmark:v1:-gold:key",
      "benchmark:v1:gold:-key",
    ]) {
      expect(benchmarkIdPattern.test(value)).toBe(false);
    }

    const decimalPattern = new RegExp(String(referenceValue.pattern));
    for (const value of [0, -1, "0", "0.0", "-1", "+1", " 1", "1 ", "1e3", "01.0"]) {
      expect(typeof value === "string" && decimalPattern.test(value)).toBe(false);
    }
    for (const value of ["0.1", "0.10", "1", "1.2300"]) {
      expect(decimalPattern.test(value)).toBe(true);
    }

    for (const value of [1, 0, "true", false]) {
      expect(value).not.toBe(referenceOnly.const);
    }
  });

  it("accepts a positive reference-only point with complete provenance", () => {
    expect(validateBenchmarkSeriesPoint(point())).toEqual({ valid: true, errors: [] });
  });

  it.each([
    0,
    -1,
    0.1,
    true,
    "0",
    "0.0",
    "-1",
    "+1",
    " 1",
    "1 ",
    "1e3",
    "01.0",
    "NaN",
    "Infinity",
  ])("rejects non-canonical referenceValue %p", (referenceValue) => {
    expect(
      validateBenchmarkSeriesPoint(point({ referenceValue: referenceValue as never })).valid,
    ).toBe(false);
  });

  it.each(["0.1", "0.10", "1", "1.2300"])(
    "accepts canonical referenceValue %s",
    (referenceValue) => {
      expect(
        validateBenchmarkSeriesPoint(point({ referenceValue: referenceValue as never })).valid,
      ).toBe(true);
    },
  );

  it.each([
    "benchmark:gold-cny",
    "Gold display label",
    " benchmark:v1:gold:key",
    "benchmark:v1:gold:key ",
    "benchmark:v1:Gold:key",
    "benchmark:v1:金:key",
    "benchmark:v1:-gold:key",
    "benchmark:v1:gold:-key",
  ])("rejects non-canonical benchmarkId %s", (benchmarkId) => {
    expect(
      validateBenchmarkSeriesPoint(point({ benchmarkId: benchmarkId as never })).valid,
    ).toBe(false);
  });

  it("enforces the canonical benchmarkId length boundary", () => {
    const atLimit = `benchmark:v1:${"n".repeat(32)}:${"k".repeat(128)}`;
    const overLimit = `benchmark:v1:${"n".repeat(32)}:${"k".repeat(129)}`;
    expect(atLimit).toHaveLength(174);
    expect(overLimit).toHaveLength(175);
    expect(validateBenchmarkSeriesPoint(point({ benchmarkId: atLimit })).valid).toBe(true);
    expect(validateBenchmarkSeriesPoint(point({ benchmarkId: overLimit })).valid).toBe(false);
  });

  it.each(["priceBasis", "source", "sourceRevision", "rawObjectId"] as const)(
    "enforces %s min/max length boundaries",
    (field) => {
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      const property = properties[field]!;
      const minLength = Number(property.minLength);
      const maxLength = Number(property.maxLength);
      const atMin = "x".repeat(minLength);
      const atMax = "x".repeat(maxLength);
      const overMax = "x".repeat(maxLength + 1);
      expect(
        validateBenchmarkSeriesPoint(point({ [field]: atMin } as Partial<BenchmarkSeriesPointInput>))
          .valid,
      ).toBe(true);
      expect(
        validateBenchmarkSeriesPoint(point({ [field]: atMax } as Partial<BenchmarkSeriesPointInput>))
          .valid,
      ).toBe(true);
      expect(
        validateBenchmarkSeriesPoint(
          point({ [field]: overMax } as Partial<BenchmarkSeriesPointInput>),
        ).valid,
      ).toBe(false);
      expect(
        validateBenchmarkSeriesPoint(point({ [field]: "" } as Partial<BenchmarkSeriesPointInput>))
          .valid,
      ).toBe(false);
    },
  );

  it("enforces the exact currency length and uppercase pattern", () => {
    expect(validateBenchmarkSeriesPoint(point({ currency: "USD" })).valid).toBe(true);
    for (const currency of ["US", "USDA", "usd"]) {
      expect(validateBenchmarkSeriesPoint(point({ currency })).valid).toBe(false);
    }
  });

  it("enforces referenceValue maxLength in addition to its decimal pattern", () => {
    const maxLength = Number(
      (schema.properties as Record<string, Record<string, unknown>>).referenceValue!.maxLength,
    );
    const atLimit = `1.${"0".repeat(maxLength - 2)}`;
    const overLimit = `1.${"0".repeat(maxLength - 1)}`;
    expect(atLimit).toHaveLength(maxLength);
    expect(overLimit).toHaveLength(maxLength + 1);
    expect(validateBenchmarkSeriesPoint(point({ referenceValue: atLimit })).valid).toBe(true);
    expect(validateBenchmarkSeriesPoint(point({ referenceValue: overLimit })).valid).toBe(false);
  });

  it("enforces the payloadDigest exact hex pattern", () => {
    expect(
      validateBenchmarkSeriesPoint(
        point({ payloadDigest: `sha256:${"a".repeat(64)}` }),
      ).valid,
    ).toBe(true);
    for (const payloadDigest of [
      `sha256:${"a".repeat(63)}`,
      `sha256:${"a".repeat(65)}`,
      `sha256:${"A".repeat(64)}`,
    ]) {
      expect(validateBenchmarkSeriesPoint(point({ payloadDigest })).valid).toBe(false);
    }
  });

  it("enforces schemaVersion and referenceOnly constants", () => {
    expect(validateBenchmarkSeriesPoint(point()).valid).toBe(true);
    expect(
      validateBenchmarkSeriesPoint(point({ schemaVersion: "other-v1" as never })).valid,
    ).toBe(false);
    expect(validateBenchmarkSeriesPoint(point({ schemaVersion: undefined })).valid).toBe(false);
  });

  it.each([1, 0, "true", false])("rejects non-literal referenceOnly %p", (referenceOnly) => {
    expect(
      validateBenchmarkSeriesPoint(point({ referenceOnly: referenceOnly as never })).valid,
    ).toBe(false);
  });

  it.each([
    "2026-08-13 09:00:00Z",
    "2026-08-13T09:00:00.1234567Z",
    "2026-08-13T09:00:00",
    "2026-02-29T09:00:00Z",
    "2026-08-13T24:00:00Z",
    "2026-08-13T09:00:00+24:00",
  ])("rejects non-strict RFC3339 timestamp %s", (eventTime) => {
    expect(validateBenchmarkSeriesPoint(point({ eventTime })).valid).toBe(false);
  });

  it("rejects year 0000 and accepts year 0001", () => {
    expect(
      validateBenchmarkSeriesPoint(point({ eventTime: "0000-01-01T00:00:00Z" })).valid,
    ).toBe(false);
    expect(
      validateBenchmarkSeriesPoint(point({ eventTime: "0001-01-01T00:00:00Z" })).valid,
    ).toBe(true);
  });

  it.each([
    "2026-08-13T09:00:00Z",
    "2026-08-13T09:00:00.1+08:00",
    "2026-08-13T03:00:00.123456-05:30",
  ])("accepts strict RFC3339 timestamp %s", (eventTime) => {
    expect(validateBenchmarkSeriesPoint(point({ eventTime })).valid).toBe(true);
  });

  it.each([
    { eventTime: "2026-08-13T09:01:00Z", ingestTime: "2026-08-13T09:00:00Z" },
    { ingestTime: "2026-08-13T09:03:00Z", availableTime: "2026-08-13T09:02:00Z" },
    { availableTime: "2026-08-13T09:04:00Z", processingTime: "2026-08-13T09:03:00Z" },
  ])("rejects timestamp order %p", (overrides) => {
    expect(validateBenchmarkSeriesPoint(point(overrides)).valid).toBe(false);
  });

  it("requires source revision, raw object and payload digest provenance", () => {
    const result = validateBenchmarkSeriesPoint(
      point({ sourceRevision: "", rawObjectId: "", payloadDigest: "not-a-digest" }),
    );
    expect(result.valid).toBe(false);
  });
});

describe("explicit fund benchmark binding", () => {
  it("keeps old records valid while missing or null binding fails closed", () => {
    const legacy = fund();
    expect(validatePreciousMetalFund(legacy)).toEqual({ valid: true, errors: [] });
    expect(benchmarkSeriesMatches(legacy, point())).toBe(false);
    expect(benchmarkSeriesMatches(fund({ benchmarkSeriesId: null }), point())).toBe(false);
  });

  it("matches only the explicit benchmark series id, never display text", () => {
    const bound = fund({ benchmarkSeriesId: CANONICAL_BENCHMARK_ID });
    expect(validatePreciousMetalFund(bound)).toEqual({ valid: true, errors: [] });
    expect(benchmarkSeriesMatches(bound, point())).toBe(true);
    expect(
      benchmarkSeriesMatches(bound, point({ benchmarkId: "benchmark:v1:gold:other" })),
    ).toBe(false);
    expect(
      benchmarkSeriesMatches(fund({ benchmarkOrTrackingIndex: CANONICAL_BENCHMARK_ID }), point()),
    ).toBe(false);
  });

  it.each([
    "benchmark:gold-cny",
    "Gold display label",
    " benchmark:v1:gold:key",
    "benchmark:v1:gold:key ",
    "benchmark:v1:Gold:key",
    "benchmark:v1:金:key",
  ])("rejects invalid explicit fund benchmarkSeriesId %s", (benchmarkSeriesId) => {
    const invalid = fund({ benchmarkSeriesId: benchmarkSeriesId as never });
    expect(validatePreciousMetalFund(invalid).valid).toBe(false);
    expect(benchmarkSeriesMatches(invalid, point())).toBe(false);
  });
});
