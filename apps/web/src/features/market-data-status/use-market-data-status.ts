import type { MarketDataSyncStatus } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";

export function useMarketDataStatus(): ObjectQueryResult<MarketDataSyncStatus> {
  return useApiObjectQuery(
    () => apiClient.get<MarketDataSyncStatus>("/v1/market-data/status"),
    [],
    true,
    30_000,
  );
}
