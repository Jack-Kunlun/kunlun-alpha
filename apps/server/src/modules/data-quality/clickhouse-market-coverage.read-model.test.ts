import { describe, expect, it } from "vitest";
import type { ClickHouseJsonClient } from "../instrument-intelligence/clickhouse-json-client";
import {
  ClickHouseMarketCoverageReadModel,
  MARKET_COVERAGE_SQL,
} from "./clickhouse-market-coverage.read-model";

const row = {
  unified_code: "600519.SH",
  source: "tushare-pro",
  observed_bar_days: 2,
  first_date: "2026-09-03",
  last_date: "2026-09-04",
  latest_event_time: "2026-09-04T07:00:00.000000Z",
  latest_available_time: "2026-09-04T07:01:00.000000Z",
  latest_processing_time: "2026-09-04T07:02:00.000000Z",
};

function client(values: unknown[]): ClickHouseJsonClient {
  return { query: async () => values } as unknown as ClickHouseJsonClient;
}

describe("ClickHouse market coverage read model", () => {
  it("passes one asOf and parameterized filters, maps rows, and truncates 101 results", async () => {
    const values = Array.from({ length: 101 }, (_, index) => ({
      ...row,
      unified_code: index === 0 ? row.unified_code : `000${String(index).padStart(3, "0")}.SZ`,
    }));
    const calls: Array<{ sql: string; parameters: Readonly<Record<string, string>> }> = [];
    const readModel = new ClickHouseMarketCoverageReadModel({
      query: async (sql: string, parameters: Readonly<Record<string, string>>) => {
        calls.push({ sql, parameters });
        return values;
      },
    } as unknown as ClickHouseJsonClient);

    await expect(
      readModel.query(
        {
          dateFrom: "2026-09-01",
          dateTo: "2026-09-04",
          source: "tushare-pro",
          unifiedCode: "600519.SH",
        },
        "2026-09-05T00:00:00.000Z",
      ),
    ).resolves.toEqual({
      rows: [
        {
          unifiedCode: "600519.SH",
          source: "tushare-pro",
          observedBarDays: 2,
          firstDate: "2026-09-03",
          lastDate: "2026-09-04",
          latestEventTime: row.latest_event_time,
          latestAvailableTime: row.latest_available_time,
          latestProcessingTime: row.latest_processing_time,
        },
        ...values.slice(1, 100).map((value) => ({
          unifiedCode: value.unified_code,
          source: value.source,
          observedBarDays: 2,
          firstDate: value.first_date,
          lastDate: value.last_date,
          latestEventTime: value.latest_event_time,
          latestAvailableTime: value.latest_available_time,
          latestProcessingTime: value.latest_processing_time,
        })),
      ],
      truncated: true,
    });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.parameters).toEqual({
      dateFrom: "2026-09-01",
      dateTo: "2026-09-04",
      source: "tushare-pro",
      unifiedCode: "600519.SH",
      asOf: "2026-09-05T00:00:00.000Z",
      limit: "101",
    });
    expect(MARKET_COVERAGE_SQL).toContain("interval = 'DAILY'");
    expect(MARKET_COVERAGE_SQL).toContain("price_type = 'RAW'");
    expect(MARKET_COVERAGE_SQL).toContain("event_time <= cutoff");
    expect(MARKET_COVERAGE_SQL).toContain("available_time <= cutoff");
    expect(MARKET_COVERAGE_SQL).toContain("processing_time <= cutoff");
    expect(MARKET_COVERAGE_SQL).toContain("uniqExact");
    expect(MARKET_COVERAGE_SQL).toContain("LIMIT {limit:UInt32}");
    expect(MARKET_COVERAGE_SQL).not.toContain("FINAL");
    expect(MARKET_COVERAGE_SQL).not.toContain("argMax");
  });

  it("returns an empty result without fabricating rows", async () => {
    await expect(
      new ClickHouseMarketCoverageReadModel(client([])).query(
        { dateFrom: "2026-09-01", dateTo: "2026-09-04" },
        "2026-09-05T00:00:00.000Z",
      ),
    ).resolves.toEqual({ rows: [], truncated: false });
  });

  it("rejects malformed ClickHouse rows and propagates query failures", async () => {
    await expect(
      new ClickHouseMarketCoverageReadModel(
        client([{ ...row, observed_bar_days: "not-int" }]),
      ).query({ dateFrom: "2026-09-01", dateTo: "2026-09-04" }, "2026-09-05T00:00:00.000Z"),
    ).rejects.toThrow("observed_bar_days");
    await expect(
      new ClickHouseMarketCoverageReadModel(client([{ ...row, observed_bar_days: "367" }])).query(
        { dateFrom: "2026-09-01", dateTo: "2026-09-04" },
        "2026-09-05T00:00:00.000Z",
      ),
    ).rejects.toThrow("observed_bar_days");
    await expect(
      new ClickHouseMarketCoverageReadModel(client([{ ...row, observed_bar_days: "2" }])).query(
        { dateFrom: "2026-09-01", dateTo: "2026-09-04" },
        "2026-09-05T00:00:00.000Z",
      ),
    ).resolves.toMatchObject({ rows: [{ observedBarDays: 2 }] });
    await expect(
      new ClickHouseMarketCoverageReadModel({
        query: async () => {
          throw new Error("clickhouse unavailable");
        },
      } as unknown as ClickHouseJsonClient).query(
        { dateFrom: "2026-09-01", dateTo: "2026-09-04" },
        "2026-09-05T00:00:00.000Z",
      ),
    ).rejects.toThrow("clickhouse unavailable");
  });
});
