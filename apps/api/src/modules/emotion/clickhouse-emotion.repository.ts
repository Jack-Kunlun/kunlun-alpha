import type { MarketEmotionSnapshot, SectorRotationEvent } from "./emotion-snapshot";
import type { EmotionReplayQuery, EmotionRepository } from "./emotion-repository";

export interface ClickHouseEmotionConfig {
  url: string;
  database: string;
  user: string;
  password?: string;
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

const SNAPSHOT_SQL = [
  "SELECT",
  "  toString(trading_date) AS date,",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%3fZ', 'UTC') AS timestamp,",
  "  toFloat64(score) AS score,",
  "  algorithm_version, ladder_json, freshness_seconds, sample_size,",
  "  toFloat64(confidence) AS confidence, source_versions, evidence_ids",
  "FROM emotion_snapshots_v1 FINAL",
  "WHERE trading_date = {date:Date}",
  "  AND ({version:String} = '' OR algorithm_version = {version:String})",
  "ORDER BY event_time, algorithm_version",
  "FORMAT JSONEachRow",
].join("\n");

const EVENT_SQL = [
  "SELECT event_id, toString(trading_date) AS date, event_type, from_sector, to_sector,",
  "  formatDateTime(event_time, '%Y-%m-%dT%H:%i:%S.%3fZ', 'UTC') AS timestamp,",
  "  toFloat64(confidence) AS confidence,",
  "  formatDateTime(evidence_start, '%Y-%m-%dT%H:%i:%S.%3fZ', 'UTC') AS evidence_start,",
  "  formatDateTime(evidence_end, '%Y-%m-%dT%H:%i:%S.%3fZ', 'UTC') AS evidence_end,",
  "  sample_size, algorithm_version, source_versions, evidence_ids",
  "FROM sector_rotation_events_v1 FINAL",
  "WHERE trading_date = {date:Date}",
  "  AND ({version:String} = '' OR algorithm_version = {version:String})",
  "  AND ({sector:String} = '' OR from_sector = {sector:String} OR to_sector = {sector:String})",
  "ORDER BY event_time, event_id",
  "FORMAT JSONEachRow",
].join("\n");

const VERSION_SQL = [
  "SELECT algorithm_version FROM (",
  "  SELECT algorithm_version FROM emotion_snapshots_v1",
  "  UNION DISTINCT",
  "  SELECT algorithm_version FROM sector_rotation_events_v1",
  ") GROUP BY algorithm_version ORDER BY algorithm_version",
  "FORMAT JSONEachRow",
].join("\n");

function recordOf(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse replay row");
  }
  return value as Record<string, unknown>;
}

function stringOf(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value === "") {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  return value;
}

function nullableStringOf(record: Record<string, unknown>, field: string): string | null {
  const value = record[field];
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  return value;
}

function numberOf(record: Record<string, unknown>, field: string): number {
  const raw = record[field];
  if (raw === "" || raw === null || raw === undefined || typeof raw === "boolean") {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  return value;
}

function integerOf(record: Record<string, unknown>, field: string): number {
  const value = numberOf(record, field);
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  return value;
}

function stringsOf(record: Record<string, unknown>, field: string): string[] {
  const value = record[field];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item === "")) {
    throw new Error("invalid ClickHouse replay field: " + field);
  }
  return [...value];
}

function parseLadder(value: unknown): MarketEmotionSnapshot["ladder"] {
  if (typeof value !== "string") {
    throw new Error("invalid ClickHouse replay field: ladder_json");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error("invalid ClickHouse replay field: ladder_json");
  }
  if (
    !Array.isArray(parsed) ||
    parsed.some(
      (entry) =>
        typeof entry !== "object" ||
        entry === null ||
        !Number.isSafeInteger((entry as Record<string, unknown>).board) ||
        !Number.isSafeInteger((entry as Record<string, unknown>).count),
    )
  ) {
    throw new Error("invalid ClickHouse replay field: ladder_json");
  }
  return parsed as MarketEmotionSnapshot["ladder"];
}

function snapshotOf(value: unknown): MarketEmotionSnapshot {
  const row = recordOf(value);
  const confidence = numberOf(row, "confidence");
  if (confidence < 0 || confidence > 1) {
    throw new Error("invalid ClickHouse replay field: confidence");
  }
  return {
    date: stringOf(row, "date"),
    timestamp: stringOf(row, "timestamp"),
    score: numberOf(row, "score"),
    algorithmVersion: stringOf(row, "algorithm_version"),
    ladder: parseLadder(row.ladder_json),
    freshnessSeconds: integerOf(row, "freshness_seconds"),
    sampleSize: integerOf(row, "sample_size"),
    confidence,
    sourceVersions: stringsOf(row, "source_versions"),
    evidenceIds: stringsOf(row, "evidence_ids"),
  };
}

function eventOf(value: unknown): SectorRotationEvent {
  const row = recordOf(value);
  const eventType = stringOf(row, "event_type");
  if (eventType !== "CROSSOVER" && eventType !== "DECAY") {
    throw new Error("invalid ClickHouse replay field: event_type");
  }
  const confidence = numberOf(row, "confidence");
  if (confidence < 0 || confidence > 1) {
    throw new Error("invalid ClickHouse replay field: confidence");
  }
  return {
    eventId: stringOf(row, "event_id"),
    date: stringOf(row, "date"),
    eventType,
    fromSector: nullableStringOf(row, "from_sector"),
    toSector: stringOf(row, "to_sector"),
    timestamp: stringOf(row, "timestamp"),
    confidence,
    evidenceStart: stringOf(row, "evidence_start"),
    evidenceEnd: stringOf(row, "evidence_end"),
    sampleSize: integerOf(row, "sample_size"),
    algorithmVersion: stringOf(row, "algorithm_version"),
    sourceVersions: stringsOf(row, "source_versions"),
    evidenceIds: stringsOf(row, "evidence_ids"),
  };
}

export class ClickHouseEmotionRepository implements EmotionRepository {
  constructor(
    private readonly config: ClickHouseEmotionConfig,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async querySnapshots(query: EmotionReplayQuery): Promise<MarketEmotionSnapshot[]> {
    return this.request(
      SNAPSHOT_SQL,
      { date: query.date, version: query.algorithmVersion ?? "" },
      snapshotOf,
    );
  }

  async queryRotationEvents(query: EmotionReplayQuery): Promise<SectorRotationEvent[]> {
    return this.request(
      EVENT_SQL,
      {
        date: query.date,
        version: query.algorithmVersion ?? "",
        sector: query.sectorId ?? "",
      },
      eventOf,
    );
  }

  async listVersions(): Promise<string[]> {
    const rows = await this.request(
      VERSION_SQL,
      {},
      (value) => stringOf(recordOf(value), "algorithm_version"),
    );
    return [...new Set(rows)].sort();
  }

  private async request<T>(
    sql: string,
    parameters: Record<string, string>,
    parser: (value: unknown) => T,
  ): Promise<T[]> {
    const url = new URL(this.config.url);
    url.searchParams.set("database", this.config.database);
    for (const [name, value] of Object.entries(parameters)) {
      url.searchParams.set("param_" + name, value);
    }
    const headers: Record<string, string> = {
      "content-type": "text/plain; charset=utf-8",
      "x-clickhouse-user": this.config.user,
    };
    if (this.config.password !== undefined && this.config.password !== "") {
      headers["x-clickhouse-key"] = this.config.password;
    }
    const response = await this.fetcher(url, {
      method: "POST",
      headers,
      body: sql,
    });
    if (!response.ok) {
      throw new Error("ClickHouse replay query failed (" + response.status + ")");
    }
    const body = await response.text();
    if (body.trim() === "") return [];
    return body
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        let value: unknown;
        try {
          value = JSON.parse(line);
        } catch {
          throw new Error("ClickHouse replay returned invalid JSON");
        }
        return parser(value);
      });
  }
}
