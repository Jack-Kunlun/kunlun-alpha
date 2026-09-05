import { ForbiddenException, ServiceUnavailableException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityService } from "./data-quality.service";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import type { MarketCoverageClock } from "./market-coverage.query";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";

const now = new Date("2026-09-05T02:00:00.123000Z");
const clock: MarketCoverageClock = { now: () => now };
const days = [
  {
    date: "2026-09-04",
    latestEventTime: "2026-09-04T07:00:00.000001Z",
    latestAvailableTime: "2026-09-04T07:01:00.000000Z",
    latestProcessingTime: "2026-09-04T07:02:00.000000Z",
  },
];
const denyAll: DataQualityAuthorizer = { canAccess: () => false };

describe("DataQualityService market coverage days", () => {
  it("returns one fixed service asOf with the required code/source", async () => {
    const calls: Array<{ filters: unknown; asOf: string }> = [];
    let clockCalls = 0;
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      undefined,
      {
        now: () => {
          clockCalls += 1;
          return now;
        },
      },
      undefined,
      {
        query: async (filters, asOf) => {
          calls.push({ filters, asOf });
          return days;
        },
      },
    );
    await expect(
      service.coverageDays({
        unifiedCode: "600519.SH",
        source: "tushare-pro",
        date: "2026-09-04",
      }),
    ).resolves.toEqual({
      schemaVersion: "market-data-coverage-days-v1",
      scope: "DAILY_RAW_SINGLE_SUPPORTED_SOURCE",
      meaning: "OBSERVED_ONLY",
      window: {
        dateFrom: "2026-09-04",
        dateTo: "2026-09-04",
        asOf: "2026-09-05T02:00:00.123Z",
      },
      unifiedCode: "600519.SH",
      source: "tushare-pro",
      days,
    });
    expect(calls).toEqual([
      {
        filters: {
          dateFrom: "2026-09-04",
          dateTo: "2026-09-04",
          unifiedCode: "600519.SH",
          source: "tushare-pro",
        },
        asOf: "2026-09-05T02:00:00.123Z",
      },
    ]);
    expect(clockCalls).toBe(1);
  });

  it("returns empty days without inferring missing dates", async () => {
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      undefined,
      clock,
      undefined,
      { query: async () => [] },
    );
    await expect(
      service.coverageDays({
        unifiedCode: "600519.SH",
        source: "tushare-pro",
        dateFrom: "2026-09-01",
        dateTo: "2026-09-04",
      }),
    ).resolves.toMatchObject({
      days: [],
      window: { dateFrom: "2026-09-01", dateTo: "2026-09-04" },
    });
  });

  it("checks authorization before parsing or querying", async () => {
    let queried = false;
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      denyAll,
      undefined,
      clock,
      undefined,
      {
        query: async () => {
          queried = true;
          return days;
        },
      },
    );
    await expect(service.coverageDays({ unknown: "x" })).rejects.toBeInstanceOf(ForbiddenException);
    expect(queried).toBe(false);
  });

  it("maps unavailable, malformed, and overlong read-model results to a safe 503", async () => {
    const failing = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      undefined,
      clock,
      undefined,
      {
        query: async () => {
          throw new Error("dsn=secret");
        },
      },
    );
    await expect(
      failing.coverageDays({ unifiedCode: "600519.SH", source: "tushare-pro" }),
    ).rejects.toEqual(new ServiceUnavailableException("行情日线明细暂不可用"));

    const malformed = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      undefined,
      clock,
      undefined,
      { query: async () => [{ ...days[0]!, date: "2026-09-06" }] },
    );
    await expect(
      malformed.coverageDays({ unifiedCode: "600519.SH", source: "tushare-pro" }),
    ).rejects.toEqual(new ServiceUnavailableException("行情日线明细暂不可用"));
  });
});
