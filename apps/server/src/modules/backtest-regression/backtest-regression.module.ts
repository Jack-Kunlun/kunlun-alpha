import { Module } from "@nestjs/common";
import { env } from "../../env";
import { AllowAllBacktestRegressionAuthorizer } from "./backtest-regression.authorizer";
import { BacktestRegressionController } from "./backtest-regression.controller";
import { LOCAL_PREVIEW_ARTIFACT, LOCAL_PREVIEW_BASELINE } from "./backtest-regression.fixture";
import { FileBacktestRegressionRepository } from "./file-backtest-regression.repository";
import { InMemoryBacktestRegressionRepository } from "./in-memory-backtest-regression.repository";
import { BacktestRegressionService } from "./backtest-regression.service";
import { BACKTEST_REGRESSION_AUTHORIZER, BACKTEST_REGRESSION_REPOSITORY } from "./backtest-regression.tokens";
import type { BacktestRegressionRepository } from "./backtest-regression.types";

function buildRepository(): BacktestRegressionRepository {
  if (env.backtestRegressionArtifactRoot !== undefined) {
    return new FileBacktestRegressionRepository(env.backtestRegressionArtifactRoot);
  }
  return new InMemoryBacktestRegressionRepository(
    [LOCAL_PREVIEW_ARTIFACT],
    new Map([["p5-core-chain", LOCAL_PREVIEW_BASELINE]]),
  );
}

@Module({
  controllers: [BacktestRegressionController],
  providers: [
    { provide: BACKTEST_REGRESSION_REPOSITORY, useFactory: buildRepository },
    { provide: BACKTEST_REGRESSION_AUTHORIZER, useClass: AllowAllBacktestRegressionAuthorizer },
    BacktestRegressionService,
  ],
  exports: [BacktestRegressionService],
})
export class BacktestRegressionModule {}
