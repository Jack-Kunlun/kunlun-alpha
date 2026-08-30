import { apiClient } from "@/lib/api-client";
import {
  useApiObjectQuery,
  useApiQuery,
  type ObjectQueryResult,
  type QueryResult,
} from "@/lib/use-api-query";
import type { RegressionArtifact, RegressionComparison, RegressionRunSummary } from "./types";

const API_PATH = "/v1/backtest/regressions";

export function useBacktestRegressionRuns(): QueryResult<RegressionRunSummary> {
  return useApiQuery(() => apiClient.get<RegressionRunSummary[]>(API_PATH), []);
}

export function useBacktestRegression(runId: string): ObjectQueryResult<RegressionArtifact> {
  return useApiObjectQuery(
    () => apiClient.get<RegressionArtifact>(`${API_PATH}/${encodeURIComponent(runId)}`),
    [runId],
    runId.length > 0,
  );
}

export function useBacktestRegressionComparison(
  runId: string,
  baselineId: string,
): ObjectQueryResult<RegressionComparison> {
  return useApiObjectQuery(
    () =>
      apiClient.get<RegressionComparison>(`${API_PATH}/${encodeURIComponent(runId)}/comparison`, {
        baselineId,
      }),
    [runId, baselineId],
    runId.length > 0 && baselineId.length > 0,
  );
}
