import { describe, expect, it } from "vitest";
import {
  MarketQualityEvidenceValidationError,
  parseMarketQualityEvidenceQuery,
} from "./market-quality-evidence.query";

describe("parseMarketQualityEvidenceQuery", () => {
  it("applies bounded defaults and accepts strict filters", () => {
    expect(
      parseMarketQualityEvidenceQuery({
        source: "akshare-tencent",
        unifiedCode: "600519.SH",
        status: "REJECTED",
        start: "2026-08-01",
        end: "2026-08-31",
        snapshotId: "a".repeat(64),
      }),
    ).toEqual({
      source: "akshare-tencent",
      unifiedCode: "600519.SH",
      status: "REJECTED",
      start: "2026-08-01",
      end: "2026-08-31",
      snapshotId: "a".repeat(64),
      limit: 20,
      offset: 0,
    });
  });

  it("requires a pinned snapshot for later pages", () => {
    expect(() => parseMarketQualityEvidenceQuery({ offset: 20 })).toThrow(
      MarketQualityEvidenceValidationError,
    );
  });

  it("rejects unknown fields, malformed values, and oversized windows", () => {
    expect(() => parseMarketQualityEvidenceQuery({ evil: "x" })).toThrow(
      MarketQualityEvidenceValidationError,
    );
    expect(() => parseMarketQualityEvidenceQuery({ unifiedCode: "SH.600519" })).toThrow(
      MarketQualityEvidenceValidationError,
    );
    expect(() => parseMarketQualityEvidenceQuery({ status: "OK" })).toThrow(
      MarketQualityEvidenceValidationError,
    );
    expect(() => parseMarketQualityEvidenceQuery({ start: "2026-01-01" })).toThrow(
      MarketQualityEvidenceValidationError,
    );
    expect(() =>
      parseMarketQualityEvidenceQuery({ start: "2025-01-01", end: "2026-01-02" }),
    ).toThrow(MarketQualityEvidenceValidationError);
    expect(() => parseMarketQualityEvidenceQuery({ limit: 101 })).toThrow(
      MarketQualityEvidenceValidationError,
    );
    expect(() => parseMarketQualityEvidenceQuery({ offset: -1 })).toThrow(
      MarketQualityEvidenceValidationError,
    );
  });
});
