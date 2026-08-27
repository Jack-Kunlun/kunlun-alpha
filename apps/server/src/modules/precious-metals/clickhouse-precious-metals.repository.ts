import type { ClickHouseJsonClient } from "../instrument-intelligence/clickhouse-json-client";
import type {
  PreciousMetalsFeatureReadModel,
  PreciousMetalsFeatureRecord,
  PreciousMetalsMarketReadModel,
  PreciousMetalsMarketRecord,
} from "./precious-metals.types";

function row(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse precious-metals row");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate === "") {
    throw new Error("invalid ClickHouse precious-metals field: " + field);
  }
  return candidate;
}

function integer(value: Record<string, unknown>, field: string): number {
  const parsed = Number(value[field]);
  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    throw new Error("invalid ClickHouse precious-metals field: " + field);
  }
  return parsed;
}

function featureValue(value: string, valueType: string): string {
  let parsed: unknown;
  try {
    parsed = JSON.parse(value) as unknown;
  } catch {
    throw new Error("invalid ClickHouse precious-metals feature JSON");
  }
  if (typeof parsed === "string" || typeof parsed === "boolean") return String(parsed);
  if (typeof parsed === "number" && Number.isSafeInteger(parsed) && valueType === "INTEGER") {
    return String(parsed);
  }
  throw new Error("precious-metals feature values must preserve exact wire scalars");
}

const MARKET_SQL = [
  "SELECT unified_code, toString(date) AS date,",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,",
  "  toString(close) AS close, toString(volume) AS volume, toString(amount) AS amount,",
  "  toUInt8(suspended) AS suspended, data_version, source, source_version,",
  "  toString(revision_fingerprint) AS evidence_id,",
  "  formatDateTime(available_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,",
  "  formatDateTime(processing_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time",
  "FROM bars_daily_v2 FINAL",
  "WHERE has(splitByChar(',', {instrumentIds:String}), unified_code)",
  "  AND interval = 'DAILY' AND price_type = 'RAW'",
  "  AND event_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND available_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "  AND processing_time <= parseDateTime64BestEffort({asOf:String}, 3, 'UTC')",
  "ORDER BY unified_code, event_time DESC, available_time DESC, processing_time DESC, replacement_version DESC, revision_fingerprint DESC",
  "LIMIT 1 BY unified_code",
  "FORMAT JSONEachRow",
].join("\n");

const FEATURE_SQL = [
  "SELECT entity_id, feature_name, feature_version, algorithm_version, value_type, value_json,",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS event_time,",
  "  formatDateTime(available_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS available_time,",
  "  formatDateTime(processing_time, '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS processing_time,",
  "  toString(lineage_checksum) AS evidence_id",
  "FROM feature_history_v1",
  "WHERE has(splitByChar(',', {instrumentIds:String}), entity_id)",
  "  AND startsWith(feature_name, 'precious_metals_fund.')",
  "  AND event_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  "  AND available_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  "  AND processing_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  "ORDER BY entity_id, feature_name, event_time DESC, available_time DESC, processing_time DESC, revision_id DESC",
  "LIMIT 1 BY entity_id, feature_name",
  "FORMAT JSONEachRow",
].join("\n");

export class ClickHousePreciousMetalsMarketRepository implements PreciousMetalsMarketReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(
    instrumentIds: readonly string[],
    asOf: string,
  ): Promise<PreciousMetalsMarketRecord[]> {
    if (instrumentIds.length === 0) return [];
    const values = await this.client.query(MARKET_SQL, {
      instrumentIds: instrumentIds.join(","),
      asOf,
    });
    return values.map((value) => {
      const input = row(value);
      const suspended = integer(input, "suspended");
      if (suspended > 1) throw new Error("invalid ClickHouse precious-metals suspended flag");
      return {
        instrumentId: text(input, "unified_code"),
        date: text(input, "date"),
        eventTime: text(input, "event_time"),
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
    });
  }
}

export class ClickHousePreciousMetalsFeatureRepository implements PreciousMetalsFeatureReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(
    instrumentIds: readonly string[],
    asOf: string,
  ): Promise<PreciousMetalsFeatureRecord[]> {
    if (instrumentIds.length === 0) return [];
    const values = await this.client.query(FEATURE_SQL, {
      instrumentIds: instrumentIds.join(","),
      asOf,
    });
    return values.map((value) => {
      const input = row(value);
      const valueType = text(input, "value_type");
      if (!new Set(["BOOLEAN", "INTEGER", "DECIMAL", "STRING", "CATEGORY"]).has(valueType)) {
        throw new Error("unsupported precious-metals feature value type");
      }
      return {
        instrumentId: text(input, "entity_id"),
        featureName: text(input, "feature_name"),
        featureVersion: text(input, "feature_version"),
        algorithmVersion: text(input, "algorithm_version"),
        valueType: valueType as PreciousMetalsFeatureRecord["valueType"],
        value: featureValue(text(input, "value_json"), valueType),
        eventTime: text(input, "event_time"),
        availableTime: text(input, "available_time"),
        processingTime: text(input, "processing_time"),
        evidenceId: text(input, "evidence_id"),
      };
    });
  }
}

export const PRECIOUS_METALS_MARKET_PIT_SQL = MARKET_SQL;
export const PRECIOUS_METALS_FEATURE_PIT_SQL = FEATURE_SQL;
