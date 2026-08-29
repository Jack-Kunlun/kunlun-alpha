import { describe, expect, it } from "vitest";
import type { ClickHouseJsonClient } from "./clickhouse-json-client";
import {
  ClickHouseInstrumentBarsRepository,
  INSTRUMENT_BARS_PIT_SQL,
} from "./clickhouse-bars.read-model";

const barRow = {
  date: "2026-08-25",
  event_time: "2026-08-25T07:00:00.000000Z",
  open: "10.0000",
  high: "11.0000",
  low: "9.0000",
  close: "10.5000",
  volume: "9007199254740993",
  amount: "9007199254740993.25",
  suspended: 0,
  data_version: "bars-v2",
  source: "tushare-pro",
  source_version: "tushare-v1",
  evidence_id: "evidence-1",
  available_time: "2026-08-25T07:01:00.000000Z",
  processing_time: "2026-08-25T07:02:00.000000Z",
};

function client(values: unknown[]): ClickHouseJsonClient {
  return { query: async () => values } as unknown as ClickHouseJsonClient;
}

describe("ClickHouse instrument daily bars read model", () => {
  it("filters all PIT clocks before winner selection and returns exact wire scalars", async () => {
    const repository = new ClickHouseInstrumentBarsRepository(client([barRow]));

    await expect(repository.load("600519.SH", "2026-08-25T08:00:00.000Z", 250)).resolves.toEqual([
      {
        date: "2026-08-25",
        eventTime: barRow.event_time,
        open: "10.0000",
        high: "11.0000",
        low: "9.0000",
        close: "10.5000",
        volume: barRow.volume,
        amount: barRow.amount,
        suspended: false,
        dataVersion: barRow.data_version,
        source: barRow.source,
        sourceVersion: barRow.source_version,
        evidenceId: barRow.evidence_id,
        availableTime: barRow.available_time,
        processingTime: barRow.processing_time,
      },
    ]);
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("FROM bars_daily_v2");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("interval = 'DAILY'");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("price_type = 'RAW'");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("event_time <=");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("available_time <=");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("processing_time <=");
    expect(INSTRUMENT_BARS_PIT_SQL).toContain(
      "source IN ('tushare-pro', 'akshare-tencent', 'akshare-sina', 'akshare-eastmoney')",
    );
    expect(INSTRUMENT_BARS_PIT_SQL).toContain("throwIf");
    expect(INSTRUMENT_BARS_PIT_SQL).not.toContain("FINAL");
  });

  it("rejects malformed rows instead of turning price data into numbers", async () => {
    const repository = new ClickHouseInstrumentBarsRepository(
      client([{ ...barRow, close: "not-a-decimal" }]),
    );
    await expect(repository.load("600519.SH", "2026-08-25T08:00:00.000Z", 250)).rejects.toThrow(
      "close",
    );
  });

  it("preserves ClickHouse failures, including conflict failures, for fail-closed handling", async () => {
    const repository = new ClickHouseInstrumentBarsRepository({
      query: async () => {
        throw new Error("revision_fingerprint conflict");
      },
    } as unknown as ClickHouseJsonClient);
    await expect(repository.load("600519.SH", "2026-08-25T08:00:00.000Z", 250)).rejects.toThrow(
      "revision_fingerprint conflict",
    );
  });
});
