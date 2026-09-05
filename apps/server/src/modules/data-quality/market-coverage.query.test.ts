import { describe, expect, it } from "vitest";
import { MarketCoverageValidationError, parseMarketCoverageQuery } from "./market-coverage.query";

const NOW = new Date("2026-09-05T02:00:00.000Z");

describe("parseMarketCoverageQuery", () => {
  it("accepts a single date, source, and canonical instrument code", () => {
    expect(
      parseMarketCoverageQuery(
        { date: "2026-09-04", source: "tushare-pro", unifiedCode: "600519.SH" },
        NOW,
      ),
    ).toEqual({
      dateFrom: "2026-09-04",
      dateTo: "2026-09-04",
      source: "tushare-pro",
      unifiedCode: "600519.SH",
    });
  });

  it("accepts an inclusive range up to 366 calendar days", () => {
    expect(parseMarketCoverageQuery({ dateFrom: "2025-09-05", dateTo: "2026-09-05" }, NOW)).toEqual(
      { dateFrom: "2025-09-05", dateTo: "2026-09-05" },
    );
  });

  it("uses the Shanghai current date and a 90-calendar-day inclusive window by default", () => {
    expect(parseMarketCoverageQuery({}, NOW)).toEqual({
      dateFrom: "2026-06-08",
      dateTo: "2026-09-05",
    });
  });

  it("rejects conflicting date forms, one-sided ranges, and oversized ranges", () => {
    expect(() =>
      parseMarketCoverageQuery(
        { date: "2026-09-04", dateFrom: "2026-09-01", dateTo: "2026-09-04" },
        NOW,
      ),
    ).toThrow(MarketCoverageValidationError);
    expect(() => parseMarketCoverageQuery({ dateFrom: "2026-09-01" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
    expect(() =>
      parseMarketCoverageQuery({ dateFrom: "2025-08-01", dateTo: "2026-09-05" }, NOW),
    ).toThrow(MarketCoverageValidationError);
  });

  it("rejects duplicate query arrays, unknown keys, invalid dates, and prefix codes", () => {
    expect(() => parseMarketCoverageQuery({ date: ["2026-09-04"] }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
    expect(() => parseMarketCoverageQuery({ unknown: "x" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
    expect(() => parseMarketCoverageQuery({ date: "2026-02-30" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
    expect(() => parseMarketCoverageQuery({ unifiedCode: "SH.600519" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
  });
});
