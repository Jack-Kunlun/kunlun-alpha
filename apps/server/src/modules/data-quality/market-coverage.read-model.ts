import type { MarketCoverageRow } from "@kunlun/shared-types";

import type { MarketCoverageQuery } from "./market-coverage.query";

export const MARKET_COVERAGE_QUERY_LIMIT = 101;

export interface MarketCoverageReadResult {
  rows: MarketCoverageRow[];
  truncated: boolean;
}

/** Independent ClickHouse read-model port for observed daily-bar coverage. */
export interface MarketCoverageReadModel {
  query(filters: MarketCoverageQuery, asOf: string): Promise<MarketCoverageReadResult>;
}

/** Used when ClickHouse is not configured; callers turn this into a controlled 503. */
export class UnavailableMarketCoverageReadModel implements MarketCoverageReadModel {
  async query(_filters: MarketCoverageQuery, _asOf: string): Promise<MarketCoverageReadResult> {
    throw new Error("market coverage read model is not configured");
  }
}
