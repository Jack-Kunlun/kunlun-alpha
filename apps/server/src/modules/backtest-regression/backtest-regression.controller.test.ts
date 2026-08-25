import {
  BadRequestException,
  ForbiddenException,
  NotFoundException,
  ServiceUnavailableException,
} from "@nestjs/common";
import { describe, expect, it } from "vitest";
import { BacktestRegressionController } from "./backtest-regression.controller";
import { AllowAllBacktestRegressionAuthorizer } from "./backtest-regression.authorizer";
import { LOCAL_PREVIEW_ARTIFACT, LOCAL_PREVIEW_BASELINE } from "./backtest-regression.fixture";
import { InMemoryBacktestRegressionRepository } from "./in-memory-backtest-regression.repository";
import { BacktestRegressionService } from "./backtest-regression.service";

class DenyAuthorizer {
  canAccess(): boolean {
    return false;
  }
}

function controller(
  artifacts = [LOCAL_PREVIEW_ARTIFACT],
  baselines = new Map([["p5-core-chain", LOCAL_PREVIEW_BASELINE]]),
  authorizer = new AllowAllBacktestRegressionAuthorizer(),
): BacktestRegressionController {
  const repository = new InMemoryBacktestRegressionRepository(artifacts, baselines);
  return new BacktestRegressionController(new BacktestRegressionService(repository, authorizer));
}

describe("BacktestRegressionController", () => {
  it("serves list, artifact and comparison through read-only methods", async () => {
    const instance = controller();
    const summaries = await instance.list();
    const artifact = await instance.get("local-preview-run");
    const comparison = await instance.comparison("local-preview-run", {
      baselineId: "p5-core-chain",
    });

    expect(summaries).toHaveLength(1);
    expect(artifact.runId).toBe("local-preview-run");
    expect(comparison.status).toBe("MATCHED");
    expect(Object.getOwnPropertyNames(BacktestRegressionController.prototype)).toEqual(
      expect.arrayContaining(["list", "get", "comparison"]),
    );
    expect(Object.getOwnPropertyNames(BacktestRegressionController.prototype)).not.toEqual(
      expect.arrayContaining(["post", "put", "patch", "delete"]),
    );
  });

  it("maps invalid IDs to 400 before repository access", async () => {
    await expect(controller().get("../escape")).rejects.toBeInstanceOf(BadRequestException);
    await expect(
      controller().comparison("local-preview-run", { baselineId: "../escape" }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it("maps authorization, missing and corrupt content to explicit errors", async () => {
    await expect(
      controller([LOCAL_PREVIEW_ARTIFACT], new Map(), new DenyAuthorizer()).list(),
    ).rejects.toBeInstanceOf(ForbiddenException);
    await expect(controller().get("missing-run")).rejects.toBeInstanceOf(NotFoundException);

    const corrupt = { ...LOCAL_PREVIEW_ARTIFACT, artifactSha256: "0".repeat(64) };
    await expect(controller([corrupt]).list()).rejects.toBeInstanceOf(ServiceUnavailableException);
  });
});
