import {
  MarketCoverageValidationError,
  parseMarketCoverageQuery,
  type MarketCoverageQuery,
} from "./market-coverage.query";
import type { MarketCoverageDaysSource } from "@kunlun/shared-types";

export interface MarketCoverageDaysQuery extends MarketCoverageQuery {
  source: MarketCoverageDaysSource;
  unifiedCode: string;
}

/** Parse the strict observed-days query and require its single instrument/source scope. */
export function parseMarketCoverageDaysQuery(input: unknown, now: Date): MarketCoverageDaysQuery {
  const parsed = parseMarketCoverageQuery(input, now);
  if (parsed.unifiedCode === undefined || parsed.source === undefined) {
    throw new MarketCoverageValidationError("unifiedCode and source are required");
  }
  return {
    ...parsed,
    source: parsed.source as MarketCoverageDaysSource,
    unifiedCode: parsed.unifiedCode,
  };
}

export { MarketCoverageValidationError };
