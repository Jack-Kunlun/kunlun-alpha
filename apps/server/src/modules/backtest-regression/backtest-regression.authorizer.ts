import type { BacktestRegressionAuthorizer } from "./backtest-regression.types";

export class AllowAllBacktestRegressionAuthorizer implements BacktestRegressionAuthorizer {
  canAccess(): boolean {
    return true;
  }
}
