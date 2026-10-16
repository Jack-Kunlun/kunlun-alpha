import { Module } from "@nestjs/common";
import {
  ClickHouseDashboardRepository,
  type ClickHouseDashboardConfig,
} from "./clickhouse-dashboard.repository";
import {
  DenyAllDashboardAuthorizer,
  PublicReadDashboardAuthorizer,
  type DashboardAuthorizer,
} from "./dashboard-authorizer";
import { DashboardController } from "./dashboard.controller";
import type { DashboardRepository } from "./dashboard-repository";
import { DashboardService } from "./dashboard.service";
import { DASHBOARD_AUTHORIZER, DASHBOARD_REPOSITORY } from "./dashboard.tokens";

function buildRepository(): DashboardRepository {
  const dailySymbols = dashboardDailySymbolsFor(process.env["DASHBOARD_DAILY_SYMBOLS"]);
  const url = process.env["EMOTION_CLICKHOUSE_URL"];
  if (!url) throw new Error("EMOTION_CLICKHOUSE_URL is required for market overview");
  const config: ClickHouseDashboardConfig = {
    url,
    database: process.env["EMOTION_CLICKHOUSE_DATABASE"] ?? "kunlun",
    user: process.env["EMOTION_CLICKHOUSE_USER"] ?? "default",
    emotionAlgorithmVersion:
      process.env["DASHBOARD_EMOTION_ALGORITHM_VERSION"] ?? "emotion_score_v1",
    timeoutMs: dashboardTimeout(process.env["DASHBOARD_CLICKHOUSE_TIMEOUT_MS"]),
  };
  if (dailySymbols !== undefined) config.dailySymbols = dailySymbols;
  const password = process.env["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return new ClickHouseDashboardRepository(config);
}

export function dashboardDailySymbolsFor(raw: string | undefined): string[] | undefined {
  if (raw === undefined) return undefined;
  const symbols = raw.split(",");
  if (
    symbols.length < 1 ||
    symbols.length > 100 ||
    symbols.some((symbol) => !/^[0-9]{6}\.(SH|SZ)$/.test(symbol)) ||
    new Set(symbols).size !== symbols.length
  ) {
    throw new Error("DASHBOARD_DAILY_SYMBOLS must contain 1 to 100 unique canonical SH/SZ symbols");
  }
  return symbols;
}

function dashboardTimeout(raw: string | undefined): number {
  if (raw === undefined) return 5_000;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > 30_000) {
    throw new Error("DASHBOARD_CLICKHOUSE_TIMEOUT_MS must be an integer between 1 and 30000");
  }
  return value;
}

export function dashboardAuthorizerFor(policy: string | undefined): DashboardAuthorizer {
  if (policy === undefined || policy === "deny") return new DenyAllDashboardAuthorizer();
  if (policy === "public") return new PublicReadDashboardAuthorizer();
  throw new Error("DASHBOARD_TERMINAL_READ_POLICY must be deny or public");
}

@Module({
  controllers: [DashboardController],
  providers: [
    { provide: DASHBOARD_REPOSITORY, useFactory: buildRepository },
    {
      provide: DASHBOARD_AUTHORIZER,
      useFactory: () => dashboardAuthorizerFor(process.env["DASHBOARD_TERMINAL_READ_POLICY"]),
    },
    DashboardService,
  ],
})
export class DashboardModule {}
