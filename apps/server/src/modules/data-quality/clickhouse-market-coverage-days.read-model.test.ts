import { describe, expect, it } from "vitest";
import type { ClickHouseJsonClient } from "../instrument-intelligence/clickhouse-json-client";
import {
  ClickHouseMarketCoverageDaysReadModel,
  MARKET_COVERAGE_DAYS_SQL,
} from "./clickhouse-market-coverage-days.read-model";
import type { MarketCoverageDaysQuery } from "./market-coverage-days.query";

const filters: MarketCoverageDaysQuery = {
  dateFrom: "2026-09-01",
  dateTo: "2026-09-04",
  unifiedCode: "600519.SH",
  source: "tushare-pro",
};
const asOf = "2026-09-05T00:00:00.123000Z";

const row = {
  observed_date: "2026-09-03",
  latest_event_time: "2026-09-03T07:00:00.123000Z",
  latest_available_time: "2026-09-03T07:01:00.123000Z",
  latest_processing_time: "2026-09-03T07:02:00.123000Z",
};

function client(values: unknown[]): ClickHouseJsonClient {
  return { query: async () => values } as unknown as ClickHouseJsonClient;
}

describe("ClickHouse market coverage days read model", () => {
  it("queries one code/source with one PIT cutoff and preserves independent latest clocks", async () => {
    const calls: Array<{ sql: string; parameters: Readonly<Record<string, string>> }> = [];
    const readModel = new ClickHouseMarketCoverageDaysReadModel({
      query: async (sql: string, parameters: Readonly<Record<string, string>>) => {
        calls.push({ sql, parameters });
        return [
          row,
          {
            ...row,
            observed_date: "2026-09-04",
            latest_event_time: "2026-09-04T08:00:00.000001Z",
            latest_available_time: "2026-09-04T07:01:00.000000Z",
            latest_processing_time: "2026-09-04T07:02:00.000000Z",
          },
        ];
      },
    } as unknown as ClickHouseJsonClient);

    await expect(readModel.query(filters, asOf)).resolves.toEqual([
      {
        date: "2026-09-03",
        latestEventTime: row.latest_event_time,
        latestAvailableTime: row.latest_available_time,
        latestProcessingTime: row.latest_processing_time,
      },
      {
        date: "2026-09-04",
        latestEventTime: "2026-09-04T08:00:00.000001Z",
        latestAvailableTime: "2026-09-04T07:01:00.000000Z",
        latestProcessingTime: "2026-09-04T07:02:00.000000Z",
      },
    ]);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.parameters).toEqual({
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      unifiedCode: filters.unifiedCode,
      source: filters.source,
      asOf,
      limit: "367",
    });
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("interval = 'DAILY'");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("price_type = 'RAW'");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("source = {source:String}");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("unified_code = {unifiedCode:String}");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("event_time <= cutoff");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("available_time <= cutoff");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("processing_time <= cutoff");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("GROUP BY date");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("ORDER BY date ASC");
    expect(MARKET_COVERAGE_DAYS_SQL).toContain("LIMIT {limit:UInt32}");
    expect(MARKET_COVERAGE_DAYS_SQL).not.toContain("FINAL");
    expect(MARKET_COVERAGE_DAYS_SQL).not.toContain("argMax");
    expect(MARKET_COVERAGE_DAYS_SQL).not.toContain("suspended");
  });

  it("returns an empty observed-only result", async () => {
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(client([])).query(filters, asOf),
    ).resolves.toEqual([]);
  });

  it("fails closed for duplicates, unsorted/out-of-window days, malformed rows, future microseconds, and 367 rows", async () => {
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client([row, { ...row, observed_date: row.observed_date }]),
      ).query(filters, asOf),
    ).rejects.toThrow();
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client([{ ...row, observed_date: "2026-09-04" }, row]),
      ).query(filters, asOf),
    ).rejects.toThrow();
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client([{ ...row, observed_date: "2026-08-31" }]),
      ).query(filters, asOf),
    ).rejects.toThrow();
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client([{ ...row, latest_event_time: "2026-09-05T00:00:00.123001Z" }]),
      ).query(filters, asOf),
    ).rejects.toThrow();
    for (const field of ["latest_available_time", "latest_processing_time"] as const) {
      await expect(
        new ClickHouseMarketCoverageDaysReadModel(
          client([{ ...row, [field]: "2026-09-05T00:00:00.123001Z" }]),
        ).query(filters, asOf),
      ).rejects.toThrow();
    }
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client([{ ...row, latest_event_time: "not-an-instant" }]),
      ).query(filters, asOf),
    ).rejects.toThrow();
    await expect(
      new ClickHouseMarketCoverageDaysReadModel(
        client(
          Array.from({ length: 367 }, (_, index) => ({
            ...row,
            observed_date: `2026-09-${String((index % 30) + 1).padStart(2, "0")}`,
          })),
        ),
      ).query(filters, asOf),
    ).rejects.toThrow();
  });
});
