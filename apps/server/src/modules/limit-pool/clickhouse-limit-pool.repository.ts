import { createHash } from "node:crypto";
import type {
  LimitPoolRepository,
  LimitPoolRepositoryQuery,
  StoredLimitPoolEntry,
  StoredLimitPoolLadderLevel,
  StoredLimitPoolPayload,
  StoredLimitPoolSnapshot,
} from "./limit-pool.repository";

export interface ClickHouseLimitPoolConfig {
  url: string;
  database: string;
  user: string;
  password?: string;
  timeoutMs?: number;
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

const QUERY_SQL = [
  "WITH",
  "  parseDateTime64BestEffort({as_of:String}, 3, 'UTC') AS cutoff,",
  "  candidates AS (",
  "    SELECT * FROM limit_pool_terminal_snapshots_v2",
  "    WHERE event_time <= cutoff",
  "      AND available_time <= parseDateTime64BestEffort({as_of:String}, 3, 'UTC')",
  "      AND ({algorithm_version:String} = '' OR algorithm_version = {algorithm_version:String})",
  "      AND ({ladder_algorithm_version:String} = '' OR ladder_algorithm_version = {ladder_algorithm_version:String})",
  "      AND ({limit_rule_version:String} = '' OR limit_rule_version = {limit_rule_version:String})",
  "      AND ({materializer_version:String} = '' OR materializer_version = {materializer_version:String})",
  "  ),",
  "  latest_event AS (SELECT max(event_time) AS value FROM candidates),",
  "  latest_revision AS (",
  "    SELECT algorithm_version, ladder_algorithm_version, limit_rule_version, materializer_version, max(revision) AS value",
  "    FROM candidates WHERE event_time = (SELECT value FROM latest_event)",
  "    GROUP BY algorithm_version, ladder_algorithm_version, limit_rule_version, materializer_version",
  "  )",
  "SELECT",
  "  toString(any(c.trading_date)) AS trading_date,",
  "  toUnixTimestamp64Milli(c.event_time) AS event_time_ms,",
  "  toUnixTimestamp64Milli(any(c.available_time)) AS available_time_ms,",
  "  c.revision, c.algorithm_version, c.ladder_algorithm_version, c.limit_rule_version, c.materializer_version,",
  "  any(c.source_versions) AS source_versions,",
  "  any(c.evidence_ids) AS evidence_ids,",
  "  any(c.payload_json) AS payload_json,",
  "  any(c.payload_digest) AS payload_digest,",
  "  throwIf(uniqExact(tuple(c.trading_date, c.payload_digest, c.available_time, c.source_versions, c.evidence_ids, c.payload_json)) > 1, 'conflicting limit-pool immutable snapshot') AS conflict_guard",
  "FROM candidates c",
  "INNER JOIN latest_revision r",
  "  ON c.algorithm_version = r.algorithm_version",
  " AND c.ladder_algorithm_version = r.ladder_algorithm_version",
  " AND c.limit_rule_version = r.limit_rule_version",
  " AND c.materializer_version = r.materializer_version",
  " AND c.revision = r.value",
  "WHERE c.event_time = (SELECT value FROM latest_event)",
  "GROUP BY c.event_time, c.revision, c.algorithm_version, c.ladder_algorithm_version, c.limit_rule_version, c.materializer_version",
  "ORDER BY c.algorithm_version, c.ladder_algorithm_version, c.limit_rule_version, c.materializer_version",
  "FORMAT JSONEachRow",
].join("\n");

const ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const POSITIVE_DECIMAL = /^(?:0\.\d*[1-9]\d*|[1-9]\d*(?:\.\d+)?)$/;
const SHA256 = /^[0-9a-f]{64}$/;
const INSTRUMENT = /^\d{6}\.(?:SH|SZ|BJ)$/;

function fail(field: string): never {
  throw new Error(`invalid ClickHouse limit-pool row: ${field}`);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) return fail("payload_json");
  return encoded;
}

function recordOf(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return fail(field);
  return value as Record<string, unknown>;
}

function stringOf(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value.trim() === "") return fail(field);
  return value;
}

function nullableStringOf(record: Record<string, unknown>, field: string): string | null {
  const value = record[field];
  if (value === null) return null;
  if (typeof value !== "string") return fail(field);
  return value;
}

function integerOf(record: Record<string, unknown>, field: string): number {
  const raw = record[field];
  if (raw === "" || raw === null || raw === undefined || typeof raw === "boolean")
    return fail(field);
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 0) return fail(field);
  return value;
}

function booleanOf(record: Record<string, unknown>, field: string): boolean {
  const value = record[field];
  if (typeof value !== "boolean") return fail(field);
  return value;
}

function stringsOf(record: Record<string, unknown>, field: string): string[] {
  const value = record[field];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item === "")) {
    return fail(field);
  }
  return [...new Set(value)];
}

function instantOf(record: Record<string, unknown>, field: string): string {
  const value = stringOf(record, field);
  if (!ISO_INSTANT.test(value) || Number.isNaN(Date.parse(value))) return fail(field);
  return value;
}

function nullableInstantOf(record: Record<string, unknown>, field: string): string | null {
  const value = nullableStringOf(record, field);
  if (value === null) return null;
  if (!ISO_INSTANT.test(value) || Number.isNaN(Date.parse(value))) return fail(field);
  return value;
}

function decimalOf(record: Record<string, unknown>, field: string): string {
  const value = stringOf(record, field);
  if (!POSITIVE_DECIMAL.test(value)) return fail(field);
  return value;
}

function enumOf<T extends string>(
  record: Record<string, unknown>,
  field: string,
  allowed: readonly T[],
): T {
  const value = stringOf(record, field);
  if (!allowed.includes(value as T)) return fail(field);
  return value as T;
}

function entryOf(value: unknown): StoredLimitPoolEntry {
  const row = recordOf(value, "payload.entries[]");
  const instrumentId = stringOf(row, "instrumentId");
  const exchange = enumOf(row, "exchange", ["SH", "SZ", "BJ"] as const);
  if (!INSTRUMENT.test(instrumentId) || !instrumentId.endsWith(`.${exchange}`)) {
    return fail("instrumentId");
  }
  const side = enumOf(row, "side", ["LIMIT_UP", "LIMIT_DOWN"] as const);
  const state = enumOf(row, "state", ["SEALED", "OPENED", "LIMIT_DOWN"] as const);
  if ((side === "LIMIT_DOWN") !== (state === "LIMIT_DOWN")) return fail("state");
  const streakDays = integerOf(row, "streakDays");
  if (side === "LIMIT_UP" && streakDays < 1) return fail("streakDays");
  const eventTime = instantOf(row, "eventTime");
  const availableTime = instantOf(row, "availableTime");
  if (Date.parse(eventTime) > Date.parse(availableTime)) return fail("availableTime");
  return {
    instrumentId,
    name: stringOf(row, "name"),
    exchange,
    listingBoard: enumOf(row, "listingBoard", ["MAIN", "CHINEXT", "STAR", "BSE"] as const),
    isSt: booleanOf(row, "isSt"),
    side,
    state,
    streakDays,
    previousStreakDays: integerOf(row, "previousStreakDays"),
    openCount: integerOf(row, "openCount"),
    priceCny: decimalOf(row, "priceCny"),
    previousCloseCny: decimalOf(row, "previousCloseCny"),
    firstSealTime: nullableInstantOf(row, "firstSealTime"),
    lastSealTime: nullableInstantOf(row, "lastSealTime"),
    eventTime,
    availableTime,
    revision: integerOf(row, "revision"),
    sourceVersion: stringOf(row, "sourceVersion"),
    evidenceId: stringOf(row, "evidenceId"),
  };
}

function ladderOf(value: unknown): StoredLimitPoolLadderLevel {
  const row = recordOf(value, "payload.ladder[]");
  const streakDays = integerOf(row, "streakDays");
  if (streakDays < 1) return fail("payload.ladder[].streakDays");
  return {
    streakDays,
    count: integerOf(row, "count"),
    previousDayEligibleCount: integerOf(row, "previousDayEligibleCount"),
    promotedCount: integerOf(row, "promotedCount"),
  };
}

function payloadOf(value: unknown): StoredLimitPoolPayload {
  const row = recordOf(value, "payload");
  const tradingDate = stringOf(row, "tradingDate");
  if (!DATE.test(tradingDate)) return fail("payload.tradingDate");
  const previousTradingDate = nullableStringOf(row, "previousTradingDate");
  if (previousTradingDate !== null && !DATE.test(previousTradingDate)) {
    return fail("payload.previousTradingDate");
  }
  const rawLadder = row.ladder;
  const rawEntries = row.entries;
  if (!Array.isArray(rawLadder) || !Array.isArray(rawEntries)) return fail("payload arrays");
  return {
    tradingDate,
    previousTradingDate,
    completeness: enumOf(row, "completeness", ["COMPLETE", "PARTIAL"] as const),
    missingReasons: stringsOf(row, "missingReasons"),
    limitUpCount: integerOf(row, "limitUpCount"),
    limitDownCount: integerOf(row, "limitDownCount"),
    sealedCount: integerOf(row, "sealedCount"),
    totalOpenCount: integerOf(row, "totalOpenCount"),
    ladder: rawLadder.map(ladderOf),
    entries: rawEntries.map(entryOf),
  };
}

function snapshotOf(value: unknown): StoredLimitPoolSnapshot {
  const row = recordOf(value, "root");
  const tradingDate = stringOf(row, "trading_date");
  if (!DATE.test(tradingDate)) return fail("trading_date");
  const eventTimeMs = integerOf(row, "event_time_ms");
  const availableTimeMs = integerOf(row, "available_time_ms");
  const eventTime = new Date(eventTimeMs).toISOString();
  const availableTime = new Date(availableTimeMs).toISOString();
  const revision = integerOf(row, "revision");
  const algorithmVersion = stringOf(row, "algorithm_version");
  const ladderAlgorithmVersion = stringOf(row, "ladder_algorithm_version");
  const limitRuleVersion = stringOf(row, "limit_rule_version");
  const materializerVersion = stringOf(row, "materializer_version");
  const sourceVersions = stringsOf(row, "source_versions");
  const evidenceIds = stringsOf(row, "evidence_ids");
  const payloadRaw = stringOf(row, "payload_json");
  let payloadValue: unknown;
  try {
    payloadValue = JSON.parse(payloadRaw);
  } catch {
    return fail("payload_json");
  }
  const payload = payloadOf(payloadValue);
  if (payload.tradingDate !== tradingDate) return fail("payload trading date mismatch");
  const payloadDigest = stringOf(row, "payload_digest");
  const expectedDigest = createHash("sha256")
    .update(
      canonicalJson({
        tradingDate,
        eventTime,
        availableTime,
        revision,
        algorithmVersion,
        ladderAlgorithmVersion,
        limitRuleVersion,
        materializerVersion,
        sourceVersions,
        evidenceIds,
        payload,
      }),
      "utf8",
    )
    .digest("hex");
  if (!SHA256.test(payloadDigest) || payloadDigest !== expectedDigest) {
    return fail("payload_digest");
  }
  return {
    tradingDate,
    eventTime,
    availableTime,
    revision,
    algorithmVersion,
    ladderAlgorithmVersion,
    limitRuleVersion,
    materializerVersion,
    sourceVersions,
    evidenceIds,
    payload,
  };
}

export class ClickHouseLimitPoolRepository implements LimitPoolRepository {
  constructor(
    private readonly config: ClickHouseLimitPoolConfig,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async findSnapshot(query: LimitPoolRepositoryQuery): Promise<StoredLimitPoolSnapshot | null> {
    const url = new URL(this.config.url);
    url.searchParams.set("database", this.config.database);
    url.searchParams.set("param_as_of", query.asOf);
    url.searchParams.set("param_algorithm_version", query.algorithmVersion ?? "");
    url.searchParams.set("param_ladder_algorithm_version", query.ladderAlgorithmVersion ?? "");
    url.searchParams.set("param_limit_rule_version", query.limitRuleVersion ?? "");
    url.searchParams.set("param_materializer_version", query.materializerVersion ?? "");
    const headers: Record<string, string> = {
      "content-type": "text/plain; charset=utf-8",
      "x-clickhouse-user": this.config.user,
    };
    if (this.config.password) headers["x-clickhouse-key"] = this.config.password;

    const response = await this.fetcher(url, {
      method: "POST",
      headers,
      body: QUERY_SQL,
      signal: AbortSignal.timeout(this.config.timeoutMs ?? 4_000),
    });
    if (!response.ok) {
      throw new Error(`ClickHouse limit-pool query failed (${response.status})`);
    }
    const body = await response.text();
    if (body.trim() === "") return null;
    const snapshots = body
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        let value: unknown;
        try {
          value = JSON.parse(line);
        } catch {
          return fail("JSON");
        }
        return snapshotOf(value);
      });
    if (snapshots.length > 1) {
      throw new Error("ambiguous limit-pool algorithm version vector; select one explicitly");
    }
    return snapshots[0] ?? null;
  }
}
