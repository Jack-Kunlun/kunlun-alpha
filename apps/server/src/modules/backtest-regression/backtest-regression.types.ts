import type {
  BacktestRegressionArtifact,
  BacktestRegressionBaseline,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";

export interface BacktestRegressionRepository {
  list(): Promise<BacktestRegressionArtifact[]>;
  get(runId: string): Promise<BacktestRegressionArtifact>;
  getBaseline(baselineId: string): Promise<BacktestRegressionBaseline>;
  source(): Pick<BacktestRegressionRunSummary, "availability" | "preview">;
}

export interface BacktestRegressionAuthorizer {
  canAccess(): boolean | Promise<boolean>;
}

export interface BacktestRegressionQuery {
  baselineId: string;
}
