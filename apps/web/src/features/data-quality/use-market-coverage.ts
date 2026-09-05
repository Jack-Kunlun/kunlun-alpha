import type { MarketCoverageResponse } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";
import type { DataQualityFilters } from "./use-data-quality";
import { parseMarketCoverageResponse } from "./market-coverage";

const API_PATH = "/v1/data-quality/market-coverage";

export function useMarketCoverage(
  filters: DataQualityFilters,
): ObjectQueryResult<MarketCoverageResponse> {
  const query: Record<string, string> = {};
  if (filters.date !== undefined && filters.date !== "") query.date = filters.date;
  if (filters.source !== undefined && filters.source !== "") query.source = filters.source;
  if (filters.unifiedCode !== undefined && filters.unifiedCode !== "") {
    query.unifiedCode = filters.unifiedCode;
  }

  return useApiObjectQuery(
    () => apiClient.get<unknown>(API_PATH, query).then(parseMarketCoverageResponse),
    [filters.date, filters.source, filters.unifiedCode],
  );
}
