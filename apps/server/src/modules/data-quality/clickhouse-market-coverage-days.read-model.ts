import type { MarketCoverageObservedDay } from "@kunlun/shared-types";

import type { ClickHouseJsonClient } from "../instrument-intelligence/clickhouse-json-client";
import {
  MARKET_COVERAGE_DAYS_QUERY_LIMIT,
  marketCoverageInstantNanos,
  parseMarketCoverageObservedDay,
  type MarketCoverageDaysReadModel,
  validateMarketCoverageDays,
} from "./market-coverage-days.read-model";
import type { MarketCoverageDaysQuery } from "./market-coverage-days.query";

/**
 * Read one observed day per date. The extra row requested by the SQL limit is
 * intentionally rejected rather than silently truncated, so a caller cannot
 * mistake an overlong result for a complete bounded response.
 */
const SQL = [
  "WITH",
  "  parseDateTime64BestEffort({asOf:String}, 9, 'UTC') AS cutoff",
  "SELECT",
  "  toString(date) AS observed_date,",
  "  formatDateTime(max(event_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_event_time,",
  "  formatDateTime(max(available_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_available_time,",
  "  formatDateTime(max(processing_time), '%Y-%m-%dT%H:%i:%S.%fZ', 'UTC') AS latest_processing_time",
  "FROM bars_daily_v2",
  "WHERE interval = 'DAILY'",
  "  AND price_type = 'RAW'",
  "  AND source = {source:String}",
  "  AND unified_code = {unifiedCode:String}",
  "  AND date >= toDate({dateFrom:String})",
  "  AND date <= toDate({dateTo:String})",
  "  AND event_time <= cutoff",
  "  AND available_time <= cutoff",
  "  AND processing_time <= cutoff",
  "GROUP BY date",
  "ORDER BY date ASC",
  "LIMIT {limit:UInt32}",
  "FORMAT JSONEachRow",
].join("\n");

export class ClickHouseMarketCoverageDaysReadModel implements MarketCoverageDaysReadModel {
  constructor(private readonly client: ClickHouseJsonClient) {}

  async query(
    filters: MarketCoverageDaysQuery,
    asOf: string,
  ): Promise<MarketCoverageObservedDay[]> {
    const values = await this.client.query(SQL, {
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      unifiedCode: filters.unifiedCode,
      source: filters.source,
      asOf,
      limit: String(MARKET_COVERAGE_DAYS_QUERY_LIMIT),
    });
    const asOfNanos = marketCoverageInstantNanos(asOf);
    const days = values.map((value) =>
      parseMarketCoverageObservedDay(value, asOfNanos, [
        "observed_date",
        "latest_event_time",
        "latest_available_time",
        "latest_processing_time",
      ]),
    );
    return validateMarketCoverageDays(days, filters, asOf);
  }
}

export const MARKET_COVERAGE_DAYS_SQL = SQL;
