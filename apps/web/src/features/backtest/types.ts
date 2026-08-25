import type {
  BacktestRegressionArtifact,
  BacktestRegressionComparison,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";

export type RegressionRunSummary = BacktestRegressionRunSummary;
export type RegressionArtifact = BacktestRegressionArtifact;
export type RegressionComparison = BacktestRegressionComparison;

export interface RegressionMetric {
  status: string;
  value: string | null;
}
