import { ForbiddenException, ServiceUnavailableException } from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { DataQualityService } from "./data-quality.service";
import type { DataQualityAuthorizer } from "./data-quality.authorizer";
import type { MarketCoverageClock } from "./market-coverage.query";
import type { MarketCoverageReadModel } from "./market-coverage.read-model";
import { InMemoryQualityRepository } from "./in-memory-quality.repository";

const now = new Date("2026-09-05T02:00:00.000Z");
const clock: MarketCoverageClock = { now: () => now };
const expectedFilters = { dateFrom: "2026-09-01", dateTo: "2026-09-04" };

const readModel: MarketCoverageReadModel = {
  query: async () => ({
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
  }),
};

const denyAll: DataQualityAuthorizer = { canAccess: () => false };

describe("DataQualityService market coverage", () => {
  it("returns an observed-only response and uses one fixed service clock", async () => {
    const calls: string[] = [];
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      {
        query: async (_filters, asOf) => {
          calls.push(asOf);
          return readModel.query(expectedFilters, asOf);
        },
      },
      clock,
    );

    await expect(
      service.coverage({ dateFrom: "2026-09-01", dateTo: "2026-09-04", source: "tushare-pro" }),
    ).resolves.toEqual({
      schemaVersion: "market-data-coverage-v1",
      scope: "DAILY_RAW_SUPPORTED_SOURCES",
      meaning: "OBSERVED_ONLY",
      window: {
        dateFrom: "2026-09-01",
        dateTo: "2026-09-04",
        asOf: "2026-09-05T02:00:00.000Z",
      },
      rows: await readModel.query(expectedFilters, now.toISOString()).then((result) => result.rows),
      truncated: false,
    });
    expect(calls).toEqual(["2026-09-05T02:00:00.000Z"]);
  });

  it("returns an empty observed result without fabricating a quality event", async () => {
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      { query: async () => ({ rows: [], truncated: false }) },
      clock,
    );
    const result = await service.coverage({ date: "2026-09-04" });
    expect(result.rows).toEqual([]);
    expect(result.window).toEqual({
      dateFrom: "2026-09-04",
      dateTo: "2026-09-04",
      asOf: "2026-09-05T02:00:00.000Z",
    });
  });

  it("checks authorization before parsing or querying", async () => {
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      denyAll,
      readModel,
      clock,
    );
    await expect(service.coverage({ unknown: "x" })).rejects.toBeInstanceOf(ForbiddenException);
  });

  it("maps missing or failing ClickHouse coverage to a controlled 503", async () => {
    const service = new DataQualityService(
      new InMemoryQualityRepository(),
      undefined,
      {
        query: async () => {
          throw new Error("dsn=secret raw clickhouse failure");
        },
      },
      clock,
    );
    await expect(service.coverage({})).rejects.toEqual(
      new ServiceUnavailableException("行情覆盖暂不可用"),
    );
  });
});
