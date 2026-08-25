export const env = {
  port: parseInt(process.env["PORT"] ?? "3002", 10),
  nodeEnv: process.env["NODE_ENV"] ?? "development",
  backtestRegressionArtifactRoot: process.env["BACKTEST_REGRESSION_ARTIFACT_ROOT"],
  get isProduction() {
    return this.nodeEnv === "production";
  },
} as const;
