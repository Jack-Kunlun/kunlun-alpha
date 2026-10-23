import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { LOCAL_TERMINAL_STOCKS } from "../instrument/local-terminal-stock-samples";
import { instrumentBarsPath, instrumentBarsQuery } from "../instrument/use-instrument-bars";
import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import {
  buildDailyComparison,
  type DailyComparison,
  type DailyComparisonOutcome,
} from "./daily-comparison";

export const DAILY_COMPARISON_BAR_LIMIT = 2;

export async function loadDailyComparison(
  requestedAsOf: string,
  client: ApiClient = apiClient,
): Promise<DailyComparison> {
  const results = await Promise.allSettled(
    LOCAL_TERMINAL_STOCKS.map((stock) =>
      client.get<unknown>(
        instrumentBarsPath(stock.instrumentId),
        instrumentBarsQuery(requestedAsOf, DAILY_COMPARISON_BAR_LIMIT),
      ),
    ),
  );
  const outcomes: DailyComparisonOutcome[] = results.map((result, index) => {
    const stock = LOCAL_TERMINAL_STOCKS[index];
    if (stock === undefined) throw new Error("daily comparison sample order changed");
    if (result.status === "fulfilled") {
      return { stock, kind: "response", value: result.value };
    }
    return result.reason instanceof ApiError && result.reason.status === 403
      ? { stock, kind: "forbidden" }
      : { stock, kind: "error" };
  });
  return buildDailyComparison(requestedAsOf, outcomes);
}

export function useDailyComparison(
  requestedAsOf: string | null,
  referenceSnapshot: MarketOverviewSnapshot | null,
) {
  return useApiObjectQuery(
    () => {
      if (requestedAsOf === null) throw new Error("a fixed comparison point in time is required");
      return loadDailyComparison(requestedAsOf);
    },
    [requestedAsOf, referenceSnapshot],
    requestedAsOf !== null,
  );
}
