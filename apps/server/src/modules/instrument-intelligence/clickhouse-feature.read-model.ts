import type { ClickHouseJsonClient } from "./clickhouse-json-client";
import type {
  InstrumentFeatureReadModel,
  InstrumentFeatureValue,
} from "./read-model.types";

const SQL = [
  "SELECT feature_name, feature_version, feature_fingerprint, algorithm_version,",
  "       value_type, value_json,",
  "       formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%6fZ', 'UTC') AS event_time,",
  "       formatDateTime(available_time, '%Y-%m-%dT%H:%i:%S.%6fZ', 'UTC') AS available_time,",
  "       formatDateTime(processing_time, '%Y-%m-%dT%H:%i:%S.%6fZ', 'UTC') AS processing_time,",
  "       lineage_checksum, source_kind, source_snapshot_version, revision_id",
  "FROM (",
  "  SELECT *, row_number() OVER (",
  "    PARTITION BY registry_namespace_id, feature_name, feature_version, feature_fingerprint",
  "    ORDER BY event_time DESC, available_time DESC, processing_time DESC, revision_id DESC",
  "  ) AS visible_rank",
  "  FROM feature_history_v1",
  "  WHERE entity_id = {instrumentId:String}",
  "    AND event_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  "    AND available_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  "    AND processing_time <= parseDateTime64BestEffort({asOf:String}, 6, 'UTC')",
  ")",
  "WHERE visible_rank = 1",
  "ORDER BY feature_name, feature_version, feature_fingerprint",
  "LIMIT 256",
  "FORMAT JSONEachRow",
].join("\n");

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse feature row");
  }
  return value as Record<string, unknown>;
}

function text(input: Record<string, unknown>, field: string): string {
  const value = input[field];
  if (typeof value !== "string" || value === "") {
    throw new Error("invalid ClickHouse feature field: " + field);
  }
  return value;
}

function feature(value: unknown): InstrumentFeatureValue {
  const input = record(value);
  let decoded: unknown;
  try {
    decoded = JSON.parse(text(input, "value_json")) as unknown;
  } catch {
    throw new Error("invalid ClickHouse feature value_json");
  }
  return {
    featureName: text(input, "feature_name"),
    featureVersion: text(input, "feature_version"),
    featureFingerprint: text(input, "feature_fingerprint"),
    algorithmVersion: text(input, "algorithm_version"),
    valueType: text(input, "value_type"),
    value: decoded,
    eventTime: text(input, "event_time"),
    availableTime: text(input, "available_time"),
    processingTime: text(input, "processing_time"),
    lineageChecksum: text(input, "lineage_checksum"),
    sourceKind: text(input, "source_kind"),
    sourceSnapshotVersion: text(input, "source_snapshot_version"),
    revisionId: text(input, "revision_id"),
  };
}

export class ClickHouseInstrumentFeatureRepository implements InstrumentFeatureReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async load(instrumentId: string, asOf: string): Promise<InstrumentFeatureValue[]> {
    const values = await this.client.query(SQL, { instrumentId, asOf });
    return values.map(feature);
  }
}

export const INSTRUMENT_FEATURE_PIT_SQL = SQL;
