import { describe, expect, it } from "vitest";
import type { MarketCoverageDaysResponse } from "@kunlun/shared-types";
import {
  buildMarketCoverageDaysQuery,
  parseMarketCoverageDaysResponse,
} from "./market-coverage-days";

const valid: MarketCoverageDaysResponse = {
  schemaVersion: "market-data-coverage-days-v1",
  scope: "DAILY_RAW_SINGLE_SUPPORTED_SOURCE",
  meaning: "OBSERVED_ONLY",
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.123456Z",
  },
  unifiedCode: "600519.SH",
  source: "tushare-pro",
  days: [
    {
      date: "2026-09-03",
      latestEventTime: "2026-09-03T07:00:00.123456Z",
      latestAvailableTime: "2026-09-03T07:01:00Z",
      latestProcessingTime: "2026-09-03T07:02:00.000001Z",
    },
    {
      date: "2026-09-04",
      latestEventTime: "2026-09-04T07:00:00Z",
      latestAvailableTime: "2026-09-04T07:01:00.654321Z",
      latestProcessingTime: "2026-09-04T07:02:00Z",
    },
  ],
};

describe("market coverage days response boundary", () => {
  it("accepts the generated shape, microsecond timestamps, and builds the scoped query", () => {
    expect(parseMarketCoverageDaysResponse(valid)).toEqual(valid);
    expect(
      buildMarketCoverageDaysQuery({
        dateFrom: "2026-09-01",
        dateTo: "2026-09-04",
        unifiedCode: "600519.SH",
        source: "tushare-pro",
      }),
    ).toEqual({
      dateFrom: "2026-09-01",
      dateTo: "2026-09-04",
      unifiedCode: "600519.SH",
      source: "tushare-pro",
    });
  });

  it("does not impose an ordering between independent aggregate timestamps", () => {
    const parsed = parseMarketCoverageDaysResponse({
      ...valid,
      days: [
        {
          ...valid.days[0],
          latestEventTime: "2026-09-04T07:02:00Z",
          latestAvailableTime: "2026-09-03T07:01:00Z",
          latestProcessingTime: "2026-09-03T07:00:00Z",
        },
      ],
    });
    expect(parsed.days[0]?.latestEventTime).toBe("2026-09-04T07:02:00Z");
  });

  it("rejects unknown fields, invalid windows, duplicate or out-of-order days", () => {
    expect(() => parseMarketCoverageDaysResponse({ ...valid, extra: "secret" })).toThrow(
      "行情日明细响应格式无效",
    );
    expect(() =>
      parseMarketCoverageDaysResponse({
        ...valid,
        window: { ...valid.window, dateTo: "2026-08-31" },
      }),
    ).toThrow("行情日明细响应格式无效");
    expect(() =>
      parseMarketCoverageDaysResponse({
        ...valid,
        days: [valid.days[1], valid.days[1]],
      }),
    ).toThrow("行情日明细响应格式无效");
    expect(() =>
      parseMarketCoverageDaysResponse({
        ...valid,
        days: [valid.days[1], valid.days[0]],
      }),
    ).toThrow("行情日明细响应格式无效");
  });

  it.each(["latestEventTime", "latestAvailableTime", "latestProcessingTime"] as const)(
    "rejects %s when it is microscopically after asOf",
    (field) => {
      expect(() =>
        parseMarketCoverageDaysResponse({
          ...valid,
          window: { ...valid.window, asOf: "2026-09-05T02:00:00.123Z" },
          days: [
            {
              ...valid.days[0],
              [field]: "2026-09-05T02:00:00.123001Z",
            },
          ],
        }),
      ).toThrow("行情日明细响应格式无效");
    },
  );

  it("allows a future query window with no days but caps observed dates at the Shanghai asOf date", () => {
    const futureWindow = {
      ...valid,
      window: {
        dateFrom: "2026-09-06",
        dateTo: "2026-09-07",
        asOf: "2026-09-05T15:59:59.999999Z",
      },
      days: [],
    };
    expect(parseMarketCoverageDaysResponse(futureWindow).days).toEqual([]);
    expect(() =>
      parseMarketCoverageDaysResponse({
        ...futureWindow,
        days: [{ ...valid.days[0], date: "2026-09-06" }],
      }),
    ).toThrow("行情日明细响应格式无效");
  });

  it.each(["2026-09-05T16:00:00Z", "2026-09-06T00:00:00+08:00"])(
    "accepts a day on the Shanghai asOf date across the UTC boundary (%s)",
    (asOf) => {
      const response = {
        ...valid,
        window: { dateFrom: "2026-09-06", dateTo: "2026-09-06", asOf },
        days: [{ ...valid.days[0], date: "2026-09-06" }],
      };
      expect(parseMarketCoverageDaysResponse(response).days[0]?.date).toBe("2026-09-06");
    },
  );
});
