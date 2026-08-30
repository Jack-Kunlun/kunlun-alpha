import { BacktestRegressionUnavailableError } from "./backtest-regression.validation";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionBaseline,
  BacktestRegressionRunSummary,
} from "@kunlun/shared-types";
import type { BacktestRegressionRepository } from "./backtest-regression.types";

export class InMemoryBacktestRegressionRepository implements BacktestRegressionRepository {
  constructor(
    private readonly artifacts: BacktestRegressionArtifact[],
    private readonly baselines: Map<string, BacktestRegressionBaseline>,
  ) {}

  async list(): Promise<BacktestRegressionArtifact[]> {
    return this.artifacts.map((artifact) => structuredClone(artifact));
  }

  async get(runId: string): Promise<BacktestRegressionArtifact> {
    const artifact = this.artifacts.find((candidate) => candidate["runId"] === runId);
    if (artifact === undefined)
      throw new BacktestRegressionUnavailableError("regression run is missing");
    return structuredClone(artifact);
  }

  async getBaseline(baselineId: string): Promise<BacktestRegressionBaseline> {
    const baseline = this.baselines.get(baselineId);
    if (baseline === undefined)
      throw new BacktestRegressionUnavailableError("regression baseline is missing");
    return structuredClone(baseline);
  }

  source(): Pick<BacktestRegressionRunSummary, "availability" | "preview"> {
    return { availability: "LOCAL_PREVIEW", preview: true };
  }
}
