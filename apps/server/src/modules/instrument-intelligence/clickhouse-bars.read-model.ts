import { isRfc3339Instant } from "../../common/rfc3339";
import type { ClickHouseJsonClient } from "./clickhouse-json-client";
import type { InstrumentBarsReadModel, InstrumentDailyBar } from "./read-model.types";

/**
 * The PIT predicates deliberately live in the first relation. A ReplacingMergeTree
 * merge (or FINAL) cannot express which revision was visible at an earlier asOf.
 */
const BARS_SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 3, 'UTC') AS cutoff,",
  "  revision_groups AS (",
  "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version,",
  "      any(date) AS revision_date, any(event_time) AS revision_event_time,",
  "      any(open) AS revision_open, any(high) AS revision_high, any(low) AS revision_low,",
  "      any(close) AS revision_close, any(volume) AS revision_volume, any(amount) AS revision_amount,",
  "      any(suspended) AS revision_suspended, any(available_time) AS revision_available_time,",
  "      any(processing_time) AS revision_processing_time, any(revision_fingerprint) AS revision_evidence_id,",
  "      uniqExact(revision_fingerprint) AS revision_count",
  "    FROM bars_daily_v2",
  "    WHERE unified_code = {instrumentId:String}",
  "      AND interval = 'DAILY' AND price_type = 'RAW'",
  "      AND event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
  "      AND source IN ('tushare-pro', 'akshare-tencent', 'akshare-sina', 'akshare-eastmoney')",
  "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version",
  "    HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0",
  "  ),",
  "  identity_rows AS (",
  "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version,",
  "      argMax(tuple(revision_date, revision_event_time, revision_open, revision_high, revision_low, revision_close, revision_volume, revision_amount, revision_suspended, revision_available_time, revision_processing_time, revision_evidence_id, data_version, source, source_version, interval, session), replacement_version) AS identity_values,",
  "      max(replacement_version) AS identity_replacement_version,",
  "      argMax(revision_evidence_id, replacement_version) AS identity_revision_fingerprint",
  "    FROM revision_groups",
  "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version",
  "    HAVING max(revision_count) = 1",
  "  ),",
  "  source_rows AS (",
  "    SELECT *, identity_values.1 AS identity_date, multiIf(source = 'tushare-pro', 3, source IN ('akshare-tencent', 'akshare-sina'), 2, source = 'akshare-eastmoney', 1, 0) AS source_priority",
  "    FROM identity_rows",
  "  ),",
  "  date_rows AS (",
  "    SELECT unified_code, identity_date AS date,",
  "      argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type, identity_values.1, identity_values.2, identity_values.3, identity_values.4, identity_values.5, identity_values.6, identity_values.7, identity_values.8, identity_values.9, identity_values.10, identity_values.11, identity_values.12, identity_values.13, identity_values.14, identity_values.15, identity_values.16, identity_values.17, identity_revision_fingerprint)) AS selected_values",
  "    FROM source_rows",
  "    GROUP BY unified_code, identity_date",
  "  ),",
  "  limited_rows AS (",
  "    SELECT unified_code, date, selected_values",
  "    FROM date_rows",
  "    ORDER BY date DESC",
  "    LIMIT {limit:UInt32}",
  "  )",
  "SELECT toString(date) AS date,",
  "  formatDateTime(selected_values.2, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,",
  "  toString(selected_values.3) AS open, toString(selected_values.4) AS high,",
  "  toString(selected_values.5) AS low, toString(selected_values.6) AS close,",
  "  toString(selected_values.7) AS volume, toString(selected_values.8) AS amount,",
  "  toUInt8(selected_values.9) AS suspended,",
  "  selected_values.13 AS data_version, selected_values.14 AS source, selected_values.15 AS source_version, toString(selected_values.12) AS evidence_id,",
  "  formatDateTime(selected_values.10, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,",
  "  formatDateTime(selected_values.11, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time",
  "FROM limited_rows",
  "ORDER BY date ASC",
  "FORMAT JSONEachRow",
].join("\n");

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse instrument bars row");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate.length === 0) {
    throw new Error("invalid ClickHouse instrument bars field: " + field);
  }
  return candidate;
}

function date(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(candidate) || !Number.isFinite(Date.parse(candidate))) {
    throw new Error("invalid ClickHouse instrument bars field: " + field);
  }
  return candidate;
}

function instant(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!isRfc3339Instant(candidate)) {
    throw new Error("invalid ClickHouse instrument bars field: " + field);
  }
  return candidate;
}

function decimal(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!/^(0|[1-9][0-9]*)(\.[0-9]+)?$/.test(candidate)) {
    throw new Error("invalid ClickHouse instrument bars field: " + field);
  }
  return candidate;
}

function suspended(value: Record<string, unknown>): boolean {
  const raw = value["suspended"];
  if (raw === "0" || raw === 0) return false;
  if (raw === "1" || raw === 1) return true;
  throw new Error("invalid ClickHouse instrument bars field: suspended");
}

function bar(value: unknown): InstrumentDailyBar {
  const input = record(value);
  return {
    date: date(input, "date"),
    eventTime: instant(input, "event_time"),
    open: decimal(input, "open"),
    high: decimal(input, "high"),
    low: decimal(input, "low"),
    close: decimal(input, "close"),
    volume: decimal(input, "volume"),
    amount: decimal(input, "amount"),
    suspended: suspended(input),
    availableTime: instant(input, "available_time"),
    processingTime: instant(input, "processing_time"),
    source: text(input, "source"),
    sourceVersion: text(input, "source_version"),
    dataVersion: text(input, "data_version"),
    evidenceId: text(input, "evidence_id"),
  };
}

export class ClickHouseInstrumentBarsRepository implements InstrumentBarsReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(instrumentId: string, asOf: string, limit: number): Promise<InstrumentDailyBar[]> {
    const values = await this.client.query(BARS_SQL, { instrumentId, asOf, limit: String(limit) });
    return values.map(bar);
  }
}

export const INSTRUMENT_BARS_PIT_SQL = BARS_SQL;
