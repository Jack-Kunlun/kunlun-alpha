import { describe, expect, it } from "vitest";
import {
  MarketCoverageValidationError,
  parseMarketCoverageDaysQuery,
} from "./market-coverage-days.query";

const NOW = new Date("2026-09-05T02:00:00.000Z");

describe("parseMarketCoverageDaysQuery", () => {
  it("requires one supported source and one canonical instrument code", () => {
    expect(
      parseMarketCoverageDaysQuery(
        { unifiedCode: "600519.SH", source: "tushare-pro", date: "2026-09-04" },
        NOW,
      ),
    ).toEqual({
      dateFrom: "2026-09-04",
      dateTo: "2026-09-04",
      unifiedCode: "600519.SH",
      source: "tushare-pro",
    });
    expect(() => parseMarketCoverageDaysQuery({ source: "tushare-pro" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
    expect(() => parseMarketCoverageDaysQuery({ unifiedCode: "600519.SH" }, NOW)).toThrow(
      MarketCoverageValidationError,
    );
  });

  it("reuses the Shanghai default window and accepts an inclusive 366-day range", () => {
    expect(
      parseMarketCoverageDaysQuery({ unifiedCode: "600519.SH", source: "akshare-tencent" }, NOW),
    ).toEqual({
      dateFrom: "2026-06-08",
      dateTo: "2026-09-05",
      unifiedCode: "600519.SH",
      source: "akshare-tencent",
    });
    expect(
      parseMarketCoverageDaysQuery(
        {
          unifiedCode: "600519.SH",
          source: "akshare-tencent",
          dateFrom: "2025-09-05",
          dateTo: "2026-09-05",
        },
        NOW,
      ).dateFrom,
    ).toBe("2025-09-05");
  });

  it("rejects missing, invalid, duplicate, unknown, and client asOf parameters", () => {
    expect(() =>
      parseMarketCoverageDaysQuery({ unifiedCode: "600519.SH", source: ["tushare-pro"] }, NOW),
    ).toThrow(MarketCoverageValidationError);
    expect(() =>
      parseMarketCoverageDaysQuery({ unifiedCode: "600519.SH", source: "unknown-source" }, NOW),
    ).toThrow(MarketCoverageValidationError);
    expect(() =>
      parseMarketCoverageDaysQuery({ unifiedCode: "SH.600519", source: "tushare-pro" }, NOW),
    ).toThrow(MarketCoverageValidationError);
    expect(() =>
      parseMarketCoverageDaysQuery(
        {
          unifiedCode: "600519.SH",
          source: "tushare-pro",
          asOf: "2026-09-05T02:00:00.000Z",
        },
        NOW,
      ),
    ).toThrow(MarketCoverageValidationError);
    expect(() =>
      parseMarketCoverageDaysQuery(
        {
          unifiedCode: "600519.SH",
          source: "tushare-pro",
          date: "2026-09-04",
          dateFrom: "2026-09-01",
          dateTo: "2026-09-04",
        },
        NOW,
      ),
    ).toThrow(MarketCoverageValidationError);
    expect(() =>
      parseMarketCoverageDaysQuery(
        {
          unifiedCode: "600519.SH",
          source: "tushare-pro",
          dateFrom: "2025-01-01",
          dateTo: "2026-09-05",
        },
        NOW,
      ),
    ).toThrow(MarketCoverageValidationError);
  });
});
