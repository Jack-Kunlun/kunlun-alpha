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

  it.each(["2026-02-30", "2026-13-01", "0000-01-01"])(
    "rejects impossible civil window date %s",
    (date) => {
      expect(() =>
        parseMarketCoverageResponse({
          ...valid,
          window: { ...valid.window, dateFrom: date },
        }),
      ).toThrow("行情覆盖响应格式无效");
    },
  );

  it.each(["2026-02-30T00:00:00Z", "2026-09-05T24:00:00Z", "2026-09-05T00:00:00-00:00"])(
    "rejects non-RFC3339 asOf %s",
    (asOf) => {
      expect(() =>
        parseMarketCoverageResponse({
          ...valid,
          window: { ...valid.window, asOf },
        }),
      ).toThrow("行情覆盖响应格式无效");
    },
  );

  it("accepts six-digit microseconds and compares aggregate clocks without millisecond rounding", () => {
    const microsecondWindow = {
      ...valid,
      window: { ...valid.window, asOf: "2026-09-05T02:00:00.123456Z" },
      rows: [
        {
          ...valid.rows[0],
          latestEventTime: "2026-09-05T02:00:00.123456Z",
          latestAvailableTime: "2026-09-05T02:00:00.123455Z",
          latestProcessingTime: "2026-09-05T02:00:00.123456Z",
        },
      ],
    };
    expect(parseMarketCoverageResponse(microsecondWindow).window.asOf).toBe(
      "2026-09-05T02:00:00.123456Z",
    );
    expect(() =>
      parseMarketCoverageResponse({
        ...microsecondWindow,
        rows: [
          {
            ...microsecondWindow.rows[0],
            latestAvailableTime: "2026-09-05T02:00:00.123457Z",
          },
        ],
      }),
    ).toThrow("行情覆盖响应格式无效");
  });

  it("rejects self-inconsistent windows, row ranges, counts, future clocks, and duplicate groups", () => {
    const row = valid.rows[0]!;
    const response = (overrides: Record<string, unknown>) => ({ ...valid, ...overrides });
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        window: { ...valid.window, dateFrom: "2026-09-05" },
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: [{ ...row, firstDate: "2026-08-31" }],
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: [{ ...row, firstDate: "2026-09-04", lastDate: "2026-09-03" }],
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: [{ ...row, observedBarDays: 3 }],
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() =>
      parseMarketCoverageResponse({
        ...valid,
        rows: [
          {
            ...row,
            latestProcessingTime: "2026-09-05T02:00:00.000001Z",
          },
        ],
      }),
    ).toThrow("行情覆盖响应格式无效");
    expect(() => parseMarketCoverageResponse(response({ rows: [row, { ...row }] }))).toThrow(
      "行情覆盖响应格式无效",
    );
  });

  it("allows a future query window with no rows but caps observed dates at the Shanghai asOf date", () => {
    const futureWindow = {
      ...valid,
      window: {
        dateFrom: "2026-09-06",
        dateTo: "2026-09-07",
        asOf: "2026-09-05T15:59:59.999999Z",
      },
      rows: [],
    };
    expect(parseMarketCoverageResponse(futureWindow).rows).toEqual([]);
    expect(() =>
      parseMarketCoverageResponse({
        ...futureWindow,
        rows: [
          {
            ...valid.rows[0],
            firstDate: "2026-09-06",
            lastDate: "2026-09-06",
            observedBarDays: 1,
          },
        ],
      }),
    ).toThrow("行情覆盖响应格式无效");
  });

  it.each(["2026-09-05T16:00:00Z", "2026-09-06T00:00:00+08:00"])(
    "accepts a row on the Shanghai asOf date across the UTC boundary (%s)",
    (asOf) => {
      const response = {
        ...valid,
        window: { dateFrom: "2026-09-06", dateTo: "2026-09-06", asOf },
        rows: [
          {
            ...valid.rows[0],
            firstDate: "2026-09-06",
            lastDate: "2026-09-06",
            observedBarDays: 1,
          },
        ],
      };
      expect(parseMarketCoverageResponse(response).rows[0]?.lastDate).toBe("2026-09-06");
    },
  );
});
