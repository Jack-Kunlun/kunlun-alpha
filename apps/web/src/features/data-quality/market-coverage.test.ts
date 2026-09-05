import { describe, expect, it } from "vitest";
import { parseMarketCoverageResponse } from "./market-coverage";

const valid = {
  schemaVersion: "market-data-coverage-v1",
  scope: "DAILY_RAW_SUPPORTED_SOURCES",
  meaning: "OBSERVED_ONLY",
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.000Z",
  },
  rows: [
    {
      unifiedCode: "600519.SH",
      source: "tushare-pro",
      observedBarDays: 2,
      firstDate: "2026-09-03",
      lastDate: "2026-09-04",
      latestEventTime: "2026-09-04T07:00:00.000Z",
      latestAvailableTime: "2026-09-04T07:01:00.000Z",
      latestProcessingTime: "2026-09-04T07:02:00.000Z",
    },
  ],
  truncated: false,
};

describe("market coverage response boundary", () => {
  it("parses the generated contract shape", () => {
    expect(parseMarketCoverageResponse(valid).rows[0]?.unifiedCode).toBe("600519.SH");
  });

  it("rejects unknown keys and malformed or oversized data", () => {
    expect(() => parseMarketCoverageResponse({ ...valid, extra: true })).toThrow(
      "行情覆盖响应格式无效",
    );
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: [{ ...valid.rows[0], observedBarDays: "2" }],
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: Array.from({ length: 101 }, () => valid.rows[0]),
      }),
    ).toThrow("行情覆盖响应格式无效");
  });
});
