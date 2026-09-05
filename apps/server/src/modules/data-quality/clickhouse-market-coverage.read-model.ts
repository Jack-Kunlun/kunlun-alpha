import type { MarketCoverageRow } from "@kunlun/shared-types";

import { isRfc3339Instant } from "../../common/rfc3339";
import type { ClickHouseJsonClient } from "../instrument-intelligence/clickhouse-json-client";
import type { MarketCoverageQuery } from "./market-coverage.query";
import {
  MARKET_COVERAGE_QUERY_LIMIT,
  type MarketCoverageReadModel,
  type MarketCoverageReadResult,
} from "./market-coverage.read-model";

export const MARKET_COVERAGE_SUPPORTED_SOURCES = [
  "tushare-pro",
  "akshare-tencent",
  "akshare-sina",
  "akshare-eastmoney",
] as const;

/**
 * Observed-only coverage query. It counts distinct trading dates and never
 * chooses a price winner, uses FINAL, or treats physical rows as coverage.
 */
const SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 6, 'UTC') AS cutoff",
  "SELECT",
  "  unified_code,",
  "  source,",
  "  uniqExact(date) AS observed_bar_days,",
  "  toString(min(date)) AS first_date,",
  "  toString(max(date)) AS last_date,",
  "  formatDateTime(max(event_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_event_time,",
  "  formatDateTime(max(available_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_available_time,",
  "  formatDateTime(max(processing_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_processing_time",
  "FROM bars_daily_v2",
  "WHERE interval = 'DAILY'",
  "  AND price_type = 'RAW'",
  "  AND source IN ('tushare-pro', 'akshare-tencent', 'akshare-sina', 'akshare-eastmoney')",
  "  AND date >= toDate({dateFrom:String})",
  "  AND date <= toDate({dateTo:String})",
  "  AND ({source:String} = '' OR source = {source:String})",
  "  AND ({unifiedCode:String} = '' OR unified_code = {unifiedCode:String})",
  "  AND event_time <= cutoff",
  "  AND available_time <= cutoff",
  "  AND processing_time <= cutoff",
  "GROUP BY unified_code, source",
  "ORDER BY unified_code ASC, source ASC",
  "LIMIT {limit:UInt32}",
  "FORMAT JSONEachRow",
].join("\n");

const UNIFIED_CODE_PATTERN = /^\d{6}\.(SH|SZ|BJ)$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("invalid ClickHouse market coverage row");
  }
  return value as Record<string, unknown>;
}

function text(value: Record<string, unknown>, field: string): string {
  const candidate = value[field];
  if (typeof candidate !== "string" || candidate.length === 0) {
    throw new Error("invalid ClickHouse market coverage field: " + field);
  }
  return candidate;
}

function date(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!DATE_PATTERN.test(candidate)) {
    throw new Error("invalid ClickHouse market coverage field: " + field);
  }
  const parsed = new Date(`${candidate}T00:00:00.000Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== candidate) {
    throw new Error("invalid ClickHouse market coverage field: " + field);
  }
  return candidate;
}

function instant(value: Record<string, unknown>, field: string): string {
  const candidate = text(value, field);
  if (!isRfc3339Instant(candidate)) {
    throw new Error("invalid ClickHouse market coverage field: " + field);
  }
  return candidate;
}

function observedDays(value: Record<string, unknown>): number {
  const candidate = value["observed_bar_days"];
  const parsed =
    typeof candidate === "number"
      ? candidate
      : typeof candidate === "string" && /^(0|[1-9][0-9]*)$/.test(candidate)
        ? Number(candidate)
        : Number.NaN;
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 366) {
    throw new Error("invalid ClickHouse market coverage field: observed_bar_days");
  }
  return parsed;
}

function coverageRow(value: unknown): MarketCoverageRow {
  const input = record(value);
  const unifiedCode = text(input, "unified_code");
  if (!UNIFIED_CODE_PATTERN.test(unifiedCode)) {
    throw new Error("invalid ClickHouse market coverage field: unified_code");
  }
  const source = text(input, "source");
  if (
    !MARKET_COVERAGE_SUPPORTED_SOURCES.includes(
      source as (typeof MARKET_COVERAGE_SUPPORTED_SOURCES)[number],
    )
  ) {
    throw new Error("invalid ClickHouse market coverage field: source");
  }
  const supportedSource = source as MarketCoverageRow["source"];
  return {
    unifiedCode,
    source: supportedSource,
    observedBarDays: observedDays(input),
    firstDate: date(input, "first_date"),
    lastDate: date(input, "last_date"),
    latestEventTime: instant(input, "latest_event_time"),
    latestAvailableTime: instant(input, "latest_available_time"),
    latestProcessingTime: instant(input, "latest_processing_time"),
  };
}

export class ClickHouseMarketCoverageReadModel implements MarketCoverageReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async query(filters: MarketCoverageQuery, asOf: string): Promise<MarketCoverageReadResult> {
    const values = await this.client.query(SQL, {
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      source: filters.source ?? "",
      unifiedCode: filters.unifiedCode ?? "",
      asOf,
      limit: String(MARKET_COVERAGE_QUERY_LIMIT),
    });
    const truncated = values.length >= MARKET_COVERAGE_QUERY_LIMIT;
    const parsedRows = values.map(coverageRow);
    const rows = parsedRows.slice(0, MARKET_COVERAGE_QUERY_LIMIT - 1);
    return { rows, truncated };
  }
}

export const MARKET_COVERAGE_SQL = SQL;
