import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";

const API_PATH = "/v1/dashboard/market-overview";
export const CURRENT_REFRESH_INTERVAL_MS = 30_000;

export function marketOverviewQuery(asOf: string | null): Record<string, string> | undefined {
  return asOf === null ? undefined : { asOf };
}

export function marketOverviewRefreshInterval(asOf: string | null): number {
  return asOf === null ? CURRENT_REFRESH_INTERVAL_MS : 0;
}

export function useMarketOverview(asOf: string | null): ObjectQueryResult<MarketOverviewSnapshot> {
  return useApiObjectQuery(
    () => apiClient.get<MarketOverviewSnapshot>(API_PATH, marketOverviewQuery(asOf)),
    [asOf],
    true,
    marketOverviewRefreshInterval(asOf),
  );
}
