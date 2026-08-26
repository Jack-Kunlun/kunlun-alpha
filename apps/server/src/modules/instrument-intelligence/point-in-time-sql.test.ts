import { describe, expect, it } from "vitest";
import { INSTRUMENT_FEATURE_PIT_SQL } from "./clickhouse-feature.read-model";
import {
  INSTRUMENT_EMOTION_PIT_SQL,
  INSTRUMENT_MARKET_PIT_SQL,
} from "./clickhouse-market.read-model";
import { MARKET_EVENT_INSTRUMENT_PIT_SQL } from "./postgres-event.read-model";
import { INSTRUMENT_MASTER_PIT_SQL } from "./postgres-instrument-master.read-model";
import {
  KOL_CLAIM_PIT_SQL,
  SEAT_TRADE_PIT_SQL,
} from "./postgres-seat-kol.read-model";
import { SECTOR_CONTEXT_PIT_SQL } from "./postgres-sector.read-model";

describe("instrument point-in-time SQL", () => {
  it.each([
    INSTRUMENT_FEATURE_PIT_SQL,
    INSTRUMENT_EMOTION_PIT_SQL,
    INSTRUMENT_MARKET_PIT_SQL,
  ])("constrains ClickHouse event, availability and processing time", (sql) => {
    expect(sql).toContain("event_time <=");
    expect(sql).toContain("available_time <=");
    expect(sql).toContain("processing_time <=");
  });

  it("uses one bulk feature query rather than per-feature reads", () => {
    expect(INSTRUMENT_FEATURE_PIT_SQL).toContain("PARTITION BY");
    expect(INSTRUMENT_FEATURE_PIT_SQL).toContain("visible_rank = 1");
    expect(INSTRUMENT_FEATURE_PIT_SQL).not.toContain("{featureName");
  });

  it.each([
    INSTRUMENT_MASTER_PIT_SQL,
    SECTOR_CONTEXT_PIT_SQL,
    MARKET_EVENT_INSTRUMENT_PIT_SQL,
    SEAT_TRADE_PIT_SQL,
    KOL_CLAIM_PIT_SQL,
  ])("constrains persisted material by the shared asOf", (sql) => {
    expect(sql).toContain("$2::timestamptz");
    expect(sql).toContain("available_time");
    expect(sql).toMatch(/processing_time|processingTime/);
  });

  it("does not reject a visible Claim solely because its eventTime is future-dated", () => {
    expect(KOL_CLAIM_PIT_SQL).not.toContain("event_time <= $2");
  });
});
