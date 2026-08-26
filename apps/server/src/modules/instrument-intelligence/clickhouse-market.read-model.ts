import type { ClickHouseJsonClient } from "./clickhouse-json-client";
import type {
  InstrumentEmotionReadModel,
  InstrumentEmotionSnapshot,
  InstrumentMarketBar,
  InstrumentMarketReadModel,
} from "./read-model.types";

function row(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse instrument row");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate === "") {
    throw new Error("invalid ClickHouse instrument field: " + field);
  }
  return candidate;
}

function integer(value: Record<string, unknown>, field: string): number {
  const parsed = Number(value[field]);
  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    throw new Error("invalid ClickHouse instrument field: " + field);
  }
  return parsed;
}

function strings(value: Record<string, unknown>, field: string): string[] {
  const candidate = value[field];
  if (!Array.isArray(candidate) || candidate.some((item) => typeof item !== "string")) {
    throw new Error("invalid ClickHouse instrument field: " + field);
  }
  return [...candidate];
}

const MARKET_SQL = [
  "SELECT",
  "  toString(date) AS date,",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,",
  "  toString(open) AS open, toString(high) AS high, toString(low) AS low,",
  "  toString(close) AS close, toString(volume) AS volume, toString(amount) AS amount,",
  "  toUInt8(suspended) AS suspended, data_version, source, source_version,",
  "  toString(revision_fingerprint) AS evidence_id,",
  "  formatDateTime(available_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,",
  "  formatDateTime(processing_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time",
  "FROM bars_daily_v2 FINAL",
  "WHERE unified_code = {instrumentId:String}",
  "  AND interval = 'DAILY' AND price_type = 'RAW'",
  "  AND bars_daily_v2.event_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND bars_daily_v2.available_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND bars_daily_v2.processing_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "ORDER BY bars_daily_v2.event_time DESC, bars_daily_v2.available_time DESC,",
  "         bars_daily_v2.processing_time DESC, replacement_version DESC, revision_fingerprint DESC",
  "LIMIT 1",
  "FORMAT JSONEachRow",
].join("\n");

const EMOTION_SQL = [
  "SELECT",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,",
  "  toString(score) AS score, toString(confidence) AS confidence, sample_size,",
  "  algorithm_version, source_versions, evidence_ids,",
  "  formatDateTime(available_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,",
  "  formatDateTime(processing_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time",
  "FROM emotion_snapshots_v1 FINAL",
  "WHERE emotion_snapshots_v1.event_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND emotion_snapshots_v1.available_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND emotion_snapshots_v1.processing_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "ORDER BY emotion_snapshots_v1.event_time DESC, emotion_snapshots_v1.available_time DESC,",
  "         emotion_snapshots_v1.processing_time DESC, algorithm_version DESC",
  "LIMIT 1",
  "FORMAT JSONEachRow",
].join("\n");

export class ClickHouseInstrumentMarketRepository implements InstrumentMarketReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(instrumentId: string, asOf: string): Promise<InstrumentMarketBar | null> {
    const values = await this.client.query(MARKET_SQL, { instrumentId, asOf });
    const value = values[0];
    if (value === undefined) return null;
    const input = row(value);
    const suspended = integer(input, "suspended");
    if (suspended > 1) throw new Error("invalid ClickHouse instrument field: suspended");
    return {
      date: text(input, "date"),
      eventTime: text(input, "event_time"),
      open: text(input, "open"),
      high: text(input, "high"),
      low: text(input, "low"),
      close: text(input, "close"),
      volume: text(input, "volume"),
      amount: text(input, "amount"),
      suspended: suspended === 1,
      dataVersion: text(input, "data_version"),
      source: text(input, "source"),
      sourceVersion: text(input, "source_version"),
      evidenceId: text(input, "evidence_id"),
      availableTime: text(input, "available_time"),
      processingTime: text(input, "processing_time"),
    };
  }
}

export class ClickHouseInstrumentEmotionRepository implements InstrumentEmotionReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(asOf: string): Promise<InstrumentEmotionSnapshot | null> {
    const values = await this.client.query(EMOTION_SQL, { asOf });
    const value = values[0];
    if (value === undefined) return null;
    const input = row(value);
    const confidence = Number(text(input, "confidence"));
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) {
      throw new Error("invalid ClickHouse instrument field: confidence");
    }
    return {
      eventTime: text(input, "event_time"),
      score: text(input, "score"),
      confidenceBps: Math.round(confidence * 10_000),
      sampleSize: integer(input, "sample_size"),
      algorithmVersion: text(input, "algorithm_version"),
      sourceVersions: strings(input, "source_versions"),
      evidenceIds: strings(input, "evidence_ids"),
      availableTime: text(input, "available_time"),
      processingTime: text(input, "processing_time"),
    };
  }
}

export const INSTRUMENT_MARKET_PIT_SQL = MARKET_SQL;
export const INSTRUMENT_EMOTION_PIT_SQL = EMOTION_SQL;
