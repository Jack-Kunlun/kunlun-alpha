import { ApiError, apiClient, type ApiClient } from "@/lib/api-client";
import { useApiObjectQuery } from "@/lib/use-api-query";
import { LOCAL_TERMINAL_STOCKS } from "../instrument/local-terminal-stock-samples";
import { instrumentBarsPath, instrumentBarsQuery } from "../instrument/use-instrument-bars";
import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import {
  buildDailyComparison,
  type DailyComparison,
  type DailyComparisonOutcome,
  type DailyComparisonStock,
} from "./daily-comparison";

export const DAILY_COMPARISON_BAR_LIMIT = 2;

export async function loadDailyComparison(
  requestedAsOf: string,
  client: Pick<ApiClient, "get"> = apiClient,
  stocks: readonly DailyComparisonStock[] = LOCAL_TERMINAL_STOCKS,
  signal?: AbortSignal,
): Promise<DailyComparison> {
  if (
    stocks.length < 1 ||
    stocks.length > 20 ||
    new Set(stocks.map((stock) => stock.instrumentId)).size !== stocks.length ||
    stocks.some((stock) => !/^[0-9]{6}\.(SH|SZ|BJ)$/.test(stock.instrumentId))
  ) {
    throw new Error("日线对比需要 1 到 20 个唯一规范标的");
  }
  // Validate the captured cutoff before issuing any request.
  buildDailyComparison(requestedAsOf, [], stocks);
  const outcomes: DailyComparisonOutcome[] = [];
  let next = 0;
  async function worker() {
    while (!signal?.aborted && next < stocks.length) {
      const index = next++;
      const stock = stocks[index]!;
      try {
        const value = await client.get<unknown>(
          instrumentBarsPath(stock.instrumentId),
          instrumentBarsQuery(requestedAsOf, DAILY_COMPARISON_BAR_LIMIT),
        );
        outcomes[index] = { stock, kind: "response", value };
      } catch (cause) {
        outcomes[index] =
          cause instanceof ApiError && cause.status === 403
            ? { stock, kind: "forbidden" }
            : { stock, kind: "error" };
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(4, stocks.length) }, worker));
  if (signal?.aborted) throw new Error("日线对比已取消");
  return buildDailyComparison(requestedAsOf, outcomes, stocks);
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
