import { ServiceUnavailableException } from "@nestjs/common";
import { describe, expect, it } from "vitest";

import { LOCAL_PREVIEW_ARTIFACT, LOCAL_PREVIEW_BASELINE } from "./backtest-regression.fixture";
import { BacktestRegressionService } from "./backtest-regression.service";
import { InMemoryBacktestRegressionRepository } from "./in-memory-backtest-regression.repository";
import { parseBacktestRegressionArtifact, sha256Json } from "./backtest-regression.validation";

function clone<T>(value: T): T {
  return structuredClone(value);
}

describe("P5-N13 audit regressions", () => {
  it("derives a drifted summary from the approved baseline instead of forcing MATCHED", async () => {
    const artifact = clone(LOCAL_PREVIEW_ARTIFACT);
    artifact.results.metrics.sharpe.value = "0.5";
    const { artifactSha256: _oldDigest, ...digestPayload } = artifact;
    artifact.artifactSha256 = sha256Json(digestPayload);
    expect(() => parseBacktestRegressionArtifact(artifact)).not.toThrow();
    const service = new BacktestRegressionService(
      new InMemoryBacktestRegressionRepository(
        [artifact],
        new Map([[LOCAL_PREVIEW_BASELINE.baselineId, clone(LOCAL_PREVIEW_BASELINE)]]),
      ),
      { canAccess: async () => true },
    );

    const [summary] = await service.list();

    expect(summary?.status).toBe("DRIFTED");
  });

  it("fails closed with 503 when the approved baseline is unavailable", async () => {
    const service = new BacktestRegressionService(
      new InMemoryBacktestRegressionRepository(
        [clone(LOCAL_PREVIEW_ARTIFACT)],
        new Map(),
      ),
      { canAccess: async () => true },
    );

    await expect(service.list()).rejects.toBeInstanceOf(ServiceUnavailableException);
  });
});
