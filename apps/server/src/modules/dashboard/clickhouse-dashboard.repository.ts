import type {
  MarketOverviewBreadthMetric,
  MarketOverviewEmotionMetric,
  MarketOverviewIndexMetric,
  MarketOverviewTurnoverMetric,
} from "@kunlun/shared-types";
import type { DashboardRepository, MarketOverviewRepositoryData } from "./dashboard-repository";

export interface ClickHouseDashboardConfig {
  url: string;
  database: string;
  user: string;
  emotionAlgorithmVersion: string;
  timeoutMs: number;
  password?: string;
}

type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

const MARKET_SOURCE_FILTER =
  "source IN ('tushare-pro', 'akshare-tencent', 'akshare-sina', 'akshare-eastmoney')";
const MARKET_SOURCE_PRIORITY =
  "multiIf(source = 'tushare-pro', 3, source IN ('akshare-tencent', 'akshare-sina'), 2, source = 'akshare-eastmoney', 1, 0)";
const MINUTE_SOURCE_RANK =
  "tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)";
const DAILY_SOURCE_RANK =
  "tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type, toString(event_time))";

function minuteBarCtes(filter: string): string[] {
  return [
    "  minute_revision_groups AS (",
    "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version,",
    "      any(close) AS revision_close, any(amount) AS revision_amount,",
    "      any(suspended) AS revision_suspended, any(revision_fingerprint) AS revision_evidence_id,",
    "      uniqExact(revision_fingerprint) AS revision_count",
    "    FROM bars_minute_v2",
    `    WHERE ${filter}`,
    "      AND interval = 'MINUTE_1' AND price_type = 'RAW' AND date = trading_date",
    "      AND event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
    `      AND ${MARKET_SOURCE_FILTER}`,
    "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version",
    "    HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0",
    "  ),",
    "  minute_identities AS (",
    "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version,",
    "      argMax(tuple(revision_close, revision_amount, revision_suspended, source_version, revision_evidence_id), replacement_version) AS identity_values,",
    "      max(replacement_version) AS identity_replacement_version,",
    `      ${MARKET_SOURCE_PRIORITY} AS source_priority`,
    "    FROM minute_revision_groups",
    "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version",
    "    HAVING max(revision_count) = 1",
    "  ),",
    "  minute_events AS (",
    "    SELECT unified_code, event_time,",
    `      argMax(identity_values, ${MINUTE_SOURCE_RANK}).1 AS event_close,`,
    `      argMax(identity_values, ${MINUTE_SOURCE_RANK}).2 AS event_amount,`,
    `      argMax(identity_values, ${MINUTE_SOURCE_RANK}).3 AS event_suspended,`,
    `      argMax(identity_values, ${MINUTE_SOURCE_RANK}).4 AS event_source_version,`,
    `      argMax(identity_values, ${MINUTE_SOURCE_RANK}).5 AS event_evidence_id`,
    "    FROM minute_identities GROUP BY unified_code, event_time",
    "  ),",
  ];
}

function dailyBarCtes(filter: string): string[] {
  return [
    "  daily_revision_groups AS (",
    "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version, date,",
    "      any(close) AS revision_close, any(revision_fingerprint) AS revision_evidence_id,",
    "      uniqExact(revision_fingerprint) AS revision_count",
    "    FROM bars_daily_v2",
    `    WHERE ${filter}`,
    "      AND interval = 'DAILY' AND price_type = 'RAW' AND date < trading_date",
    "      AND event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
    `      AND ${MARKET_SOURCE_FILTER}`,
    "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version, date",
    "    HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0",
    "  ),",
    "  daily_identities AS (",
    "    SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, date,",
    "      argMax(tuple(revision_close, source_version, revision_evidence_id), replacement_version) AS identity_values,",
    "      max(replacement_version) AS identity_replacement_version,",
    `      ${MARKET_SOURCE_PRIORITY} AS source_priority`,
    "    FROM daily_revision_groups",
    "    GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, date",
    "    HAVING max(revision_count) = 1",
    "  ),",
    "  daily_events AS (",
    "    SELECT unified_code, date,",
    `      argMax(identity_values, ${DAILY_SOURCE_RANK}).1 AS event_close,`,
    `      argMax(identity_values, ${DAILY_SOURCE_RANK}).2 AS event_source_version,`,
    `      argMax(identity_values, ${DAILY_SOURCE_RANK}).3 AS event_evidence_id`,
    "    FROM daily_identities GROUP BY unified_code, date",
    "  ),",
  ];
}

const INDEX_FILTER = "unified_code IN ('000001.SH', '399001.SZ', '399006.SZ')";

const INDEX_SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 3, 'UTC') AS cutoff,",
  "  toDate(toTimeZone(cutoff, 'Asia/Shanghai')) AS trading_date,",
  ...minuteBarCtes(INDEX_FILTER),
  ...dailyBarCtes(INDEX_FILTER),
  "  current_values AS (",
  "    SELECT unified_code, argMax(event_close, event_time) AS value, max(event_time) AS data_time,",
  "      argMax(event_source_version, event_time) AS selected_source_version,",
  "      argMax(event_evidence_id, event_time) AS selected_evidence_id",
  "    FROM minute_events GROUP BY unified_code",
  "  ),",
  "  previous_values AS (",
  "    SELECT unified_code, argMax(event_close, date) AS previous_close",
  "    FROM daily_events GROUP BY unified_code",
  "  )",
  "SELECT current_values.unified_code AS instrument_id, toString(value) AS value,",
  "  toString(previous_close) AS previous_close,",
  "  concat(replaceOne(toString(data_time), ' ', 'T'), 'Z') AS data_time,",
  "  selected_source_version AS source_version, selected_evidence_id AS evidence_id",
  "FROM current_values INNER JOIN previous_values USING (unified_code)",
  "ORDER BY instrument_id",
  "FORMAT JSONEachRow",
].join("\n");

const EQUITY_PATTERN =
  "^(?:60[0135]|68[89])[0-9]{3}\\.SH$|^(?:00[0-3]|30[01])[0-9]{3}\\.SZ$|^[489][0-9]{5}\\.BJ$";

const MARKET_SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 3, 'UTC') AS cutoff,",
  "  toDate(toTimeZone(cutoff, 'Asia/Shanghai')) AS trading_date,",
  ...minuteBarCtes(`match(unified_code, '${EQUITY_PATTERN}')`),
  ...dailyBarCtes(`match(unified_code, '${EQUITY_PATTERN}')`),
  "  current_values AS (",
  "    SELECT unified_code, argMax(event_close, event_time) AS value,",
  "      argMax(event_suspended, event_time) AS suspended, max(event_time) AS data_time,",
  "      sum(event_amount) AS day_turnover,",
  "      argMax(event_source_version, event_time) AS selected_source_version,",
  "      argMax(event_evidence_id, event_time) AS selected_evidence_id",
  "    FROM minute_events GROUP BY unified_code",
  "  ),",
  "  previous_values AS (",
  "    SELECT unified_code, argMax(event_close, date) AS previous_close",
  "    FROM daily_events GROUP BY unified_code",
  "  ),",
  "  compared AS (",
  "    SELECT * FROM current_values INNER JOIN previous_values USING (unified_code)",
  "  )",
  "SELECT countIf(suspended = 0 AND value > previous_close) AS advancing_count,",
  "  countIf(suspended = 0 AND value < previous_close) AS declining_count,",
  "  countIf(suspended = 0 AND value = previous_close) AS unchanged_count,",
  "  countIf(suspended = 1) AS suspended_count, count() AS sample_size,",
  "  toString(sum(day_turnover)) AS turnover_cny,",
  "  concat(replaceOne(toString(min(data_time)), ' ', 'T'), 'Z') AS data_time,",
  "  arraySort(groupUniqArray(selected_source_version)) AS source_versions,",
  "  [lower(hex(SHA256(arrayStringConcat(arraySort(groupArray(selected_evidence_id)), '|'))))] AS evidence_ids",
  "FROM compared HAVING sample_size > 0",
  "FORMAT JSONEachRow",
].join("\n");

const EMOTION_SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 3, 'UTC') AS cutoff,",
  "  toDate(toTimeZone(cutoff, 'Asia/Shanghai')) AS requested_date,",
  "  emotion_revision_groups AS (",
  "    SELECT trading_date, event_time, algorithm_version, replacement_version,",
  "      any(score) AS revision_score, any(confidence) AS revision_confidence,",
  "      any(sample_size) AS revision_sample_size,",
  "      any(source_versions) AS revision_source_versions, any(evidence_ids) AS revision_evidence_ids,",
  "      uniqExact(payload_digest) AS revision_count",
  "    FROM emotion_snapshots_v1",
  "    WHERE trading_date = requested_date AND algorithm_version = {emotionVersion:String}",
  "      AND event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
  "    GROUP BY trading_date, event_time, algorithm_version, replacement_version",
  "    HAVING throwIf(uniqExact(payload_digest) > 1, 'emotion payload conflict') = 0",
  "  ),",
  "  emotion_identities AS (",
  "    SELECT trading_date, event_time, algorithm_version,",
  "      argMax(revision_score, replacement_version) AS identity_score,",
  "      argMax(revision_confidence, replacement_version) AS identity_confidence,",
  "      argMax(revision_sample_size, replacement_version) AS identity_sample_size,",
  "      argMax(revision_source_versions, replacement_version) AS identity_source_versions,",
  "      argMax(revision_evidence_ids, replacement_version) AS identity_evidence_ids",
  "    FROM emotion_revision_groups",
  "    GROUP BY trading_date, event_time, algorithm_version",
  "    HAVING max(revision_count) = 1",
  "  )",
  "SELECT concat(replaceOne(toString(event_time), ' ', 'T'), 'Z') AS data_time,",
  "  toInt32(round(toFloat64(identity_score) * 10000)) AS score_bps,",
  "  toInt32(round(toFloat64(identity_confidence) * 10000)) AS confidence_bps,",
  "  identity_sample_size AS sample_size, algorithm_version,",
  "  identity_source_versions AS source_versions, identity_evidence_ids AS evidence_ids",
  "FROM emotion_identities",
  "ORDER BY event_time DESC, algorithm_version DESC LIMIT 1",
  "FORMAT JSONEachRow",
].join("\n");

const INDEX_NAMES: Readonly<Record<string, string>> = {
  "000001.SH": "上证指数",
  "399001.SZ": "深证成指",
  "399006.SZ": "创业板指",
};

function recordOf(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse dashboard row");
  }
  return value as Record<string, unknown>;
}

function stringOf(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== "string" || value === "") {
    throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  }
  return value;
}

function integerOf(record: Record<string, unknown>, field: string): number {
  const raw = record[field];
  if (raw === "" || raw === null || raw === undefined || typeof raw === "boolean") {
    throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  }
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  }
  return value;
}

function bpsOf(record: Record<string, unknown>, field: string): number {
  const value = integerOf(record, field);
  if (value > 10_000) throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  return value;
}

function stringsOf(record: Record<string, unknown>, field: string): string[] {
  const value = record[field];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item === "")) {
    throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  }
  return [...value];
}

function decimalOf(record: Record<string, unknown>, field: string): string {
  const value = stringOf(record, field);
  if (!/^\d+(?:\.\d+)?$/.test(value)) {
    throw new Error(`invalid ClickHouse dashboard field: ${field}`);
  }
  return value;
}

function decimalParts(value: string): { integer: bigint; scale: number } {
  const [whole = "0", fraction = ""] = value.split(".");
  return { integer: BigInt(whole + fraction), scale: fraction.length };
}

function changeBps(value: string, previous: string): number {
  const current = decimalParts(value);
  const baseline = decimalParts(previous);
  const scale = Math.max(current.scale, baseline.scale);
  const currentInteger = current.integer * 10n ** BigInt(scale - current.scale);
  const baselineInteger = baseline.integer * 10n ** BigInt(scale - baseline.scale);
  if (baselineInteger <= 0n) throw new Error("invalid ClickHouse dashboard previous close");
  const numerator = (currentInteger - baselineInteger) * 10_000n;
  const sign = numerator < 0n ? -1n : 1n;
  const rounded = sign * ((numerator * sign + baselineInteger / 2n) / baselineInteger);
  const result = Number(rounded);
  if (!Number.isSafeInteger(result)) throw new Error("invalid ClickHouse dashboard change");
  return result;
}

function indexOf(value: unknown): MarketOverviewIndexMetric {
  const row = recordOf(value);
  const instrumentId = stringOf(row, "instrument_id");
  const name = INDEX_NAMES[instrumentId];
  if (name === undefined) throw new Error("invalid ClickHouse dashboard index");
  const current = decimalOf(row, "value");
  const previousClose = decimalOf(row, "previous_close");
  return {
    instrumentId,
    name,
    dataTime: stringOf(row, "data_time"),
    value: current,
    previousClose,
    changeBps: changeBps(current, previousClose),
    sourceVersion: stringOf(row, "source_version"),
    evidenceId: stringOf(row, "evidence_id"),
  };
}

function marketOf(value: unknown): {
  breadth: MarketOverviewBreadthMetric;
  turnover: MarketOverviewTurnoverMetric;
} {
  const row = recordOf(value);
  const advancingCount = integerOf(row, "advancing_count");
  const decliningCount = integerOf(row, "declining_count");
  const unchangedCount = integerOf(row, "unchanged_count");
  const suspendedCount = integerOf(row, "suspended_count");
  const sampleSize = integerOf(row, "sample_size");
  if (advancingCount + decliningCount + unchangedCount + suspendedCount !== sampleSize) {
    throw new Error("invalid ClickHouse dashboard breadth total");
  }
  const dataTime = stringOf(row, "data_time");
  const sourceVersions = stringsOf(row, "source_versions");
  const evidenceIds = stringsOf(row, "evidence_ids");
  const comparable = advancingCount + decliningCount + unchangedCount;
  const advancingRatioBps =
    comparable === 0 ? 0 : Math.round((advancingCount * 10_000) / comparable);
  return {
    breadth: {
      dataTime,
      advancingCount,
      decliningCount,
      unchangedCount,
      suspendedCount,
      sampleSize,
      advancingRatioBps,
      universeVersion: "ashare-code-pattern-v1",
      sourceVersions,
      evidenceIds,
    },
    turnover: {
      dataTime,
      amountCny: decimalOf(row, "turnover_cny"),
      sampleSize,
      sourceVersions,
      evidenceIds,
    },
  };
}

function emotionOf(value: unknown): MarketOverviewEmotionMetric {
  const row = recordOf(value);
  return {
    dataTime: stringOf(row, "data_time"),
    scoreBps: bpsOf(row, "score_bps"),
    confidenceBps: bpsOf(row, "confidence_bps"),
    sampleSize: integerOf(row, "sample_size"),
    algorithmVersion: stringOf(row, "algorithm_version"),
    sourceVersions: stringsOf(row, "source_versions"),
    evidenceIds: stringsOf(row, "evidence_ids"),
  };
}

export class ClickHouseDashboardRepository implements DashboardRepository {
  constructor(
    private readonly config: ClickHouseDashboardConfig,
    private readonly fetcher: FetchLike = fetch,
  ) {}

  async loadMarketOverview(asOf: string): Promise<MarketOverviewRepositoryData> {
    const [indices, marketRows, emotions] = await Promise.all([
      this.request(INDEX_SQL, { asOf }, indexOf),
      this.request(MARKET_SQL, { asOf }, marketOf),
      this.request(
        EMOTION_SQL,
        { asOf, emotionVersion: this.config.emotionAlgorithmVersion },
        emotionOf,
      ),
    ]);
    const market = marketRows[0] ?? null;
    const emotion = emotions[0] ?? null;
    const sourceVersions = [
      ...indices.map((item) => item.sourceVersion),
      ...(market?.breadth.sourceVersions ?? []),
      ...(emotion?.sourceVersions ?? []),
    ];
    const evidenceIds = [
      ...indices.map((item) => item.evidenceId),
      ...(market?.breadth.evidenceIds ?? []),
      ...(emotion?.evidenceIds ?? []),
    ];
    return {
      indices,
      breadth: market?.breadth ?? null,
      turnover: market?.turnover ?? null,
      emotion,
      sourceVersions: [...new Set(sourceVersions)].sort(),
      evidenceIds: [...new Set(evidenceIds)].sort(),
    };
  }

  private async request<T>(
    sql: string,
    parameters: Record<string, string>,
    parser: (value: unknown) => T,
  ): Promise<T[]> {
    const url = new URL(this.config.url);
    url.searchParams.set("database", this.config.database);
    for (const [name, value] of Object.entries(parameters)) {
      url.searchParams.set(`param_${name}`, value);
    }
    const headers: Record<string, string> = {
      "content-type": "text/plain; charset=utf-8",
      "x-clickhouse-user": this.config.user,
    };
    if (this.config.password !== undefined && this.config.password !== "") {
      headers["x-clickhouse-key"] = this.config.password;
    }
    const abortController = new AbortController();
    const timeout = setTimeout(() => abortController.abort(), this.config.timeoutMs);
    let body: string;
    try {
      const response = await this.fetcher(url, {
        method: "POST",
        headers,
        body: sql,
        signal: abortController.signal,
      });
      if (!response.ok) {
        throw new Error(`ClickHouse dashboard query failed (${response.status})`);
      }
      body = await response.text();
    } catch (error) {
      if (abortController.signal.aborted) {
        throw new Error(`ClickHouse dashboard query timed out after ${this.config.timeoutMs}ms`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
    if (body.trim() === "") return [];
    return body
      .split(/\r?\n/)
      .filter(Boolean)
      .map((line) => {
        let value: unknown;
        try {
          value = JSON.parse(line);
        } catch {
          throw new Error("ClickHouse dashboard returned invalid JSON");
        }
        return parser(value);
      });
  }
}
