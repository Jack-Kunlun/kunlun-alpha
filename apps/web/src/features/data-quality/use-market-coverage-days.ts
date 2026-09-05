import type { MarketCoverageDaysResponse } from "@kunlun/shared-types";
import { apiClient } from "@/lib/api-client";
import { useApiObjectQuery, type ObjectQueryResult } from "@/lib/use-api-query";
import {
  buildMarketCoverageDaysQuery,
  parseMarketCoverageDaysResponse,
  type MarketCoverageDaysSelection,
} from "./market-coverage-days";

const API_PATH = "/v1/data-quality/market-coverage/days";

export function useMarketCoverageDays(
  selection: MarketCoverageDaysSelection | null,
): ObjectQueryResult<MarketCoverageDaysResponse> {
  const enabled = selection !== null;
  const identity = selection === null ? null : (selection.selectionKey ?? "default");
  return useApiObjectQuery(
    () =>
      apiClient
        .get<unknown>(API_PATH, buildMarketCoverageDaysQuery(selection!))
        .then(parseMarketCoverageDaysResponse),
    [selection?.dateFrom, selection?.dateTo, selection?.unifiedCode, selection?.source, identity],
    enabled,
  );
}
