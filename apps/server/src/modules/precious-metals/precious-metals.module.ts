import { Module } from "@nestjs/common";
import { Pool } from "pg";
import {
  type ClickHouseIntelligenceConfig,
  ClickHouseJsonClient,
} from "../instrument-intelligence/clickhouse-json-client";
import {
  ClickHousePreciousMetalsFeatureRepository,
  ClickHousePreciousMetalsMarketRepository,
} from "./clickhouse-precious-metals.repository";
import { PostgresPreciousMetalsRepository } from "./postgres-precious-metals.repository";
import { PreciousMetalsController } from "./precious-metals.controller";
import { SystemPreciousMetalsClock } from "./precious-metals.query";
import { AllowAllPreciousMetalsAuthorizer, PreciousMetalsService } from "./precious-metals.service";
import {
  PRECIOUS_METALS_AUTHORIZER,
  PRECIOUS_METALS_CLOCK,
  PRECIOUS_METALS_FEATURES,
  PRECIOUS_METALS_MARKET,
  PRECIOUS_METALS_POSTGRES,
} from "./precious-metals.tokens";

function postgresRepository(): PostgresPreciousMetalsRepository {
  const dsn = process.env["PRECIOUS_METALS_POSTGRES_DSN"] ?? process.env["KUNLUN_POSTGRES_DSN"];
  if (!dsn) throw new Error("PRECIOUS_METALS_POSTGRES_DSN is required");
  return new PostgresPreciousMetalsRepository(new Pool({ connectionString: dsn }));
}

function timeout(value: string | undefined): number {
  if (value === undefined) return 5_000;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 30_000) {
    throw new Error("PRECIOUS_METALS_CLICKHOUSE_TIMEOUT_MS must be between 1 and 30000");
  }
  return parsed;
}

function clickhouseClient(): ClickHouseJsonClient {
  const url =
    process.env["PRECIOUS_METALS_CLICKHOUSE_URL"] ?? process.env["EMOTION_CLICKHOUSE_URL"];
  if (!url) throw new Error("PRECIOUS_METALS_CLICKHOUSE_URL is required");
  const config: ClickHouseIntelligenceConfig = {
    url,
    database:
      process.env["PRECIOUS_METALS_CLICKHOUSE_DATABASE"] ??
      process.env["EMOTION_CLICKHOUSE_DATABASE"] ??
      "kunlun",
    user:
      process.env["PRECIOUS_METALS_CLICKHOUSE_USER"] ??
      process.env["EMOTION_CLICKHOUSE_USER"] ??
      "default",
    timeoutMs: timeout(process.env["PRECIOUS_METALS_CLICKHOUSE_TIMEOUT_MS"]),
  };
  const password =
    process.env["PRECIOUS_METALS_CLICKHOUSE_PASSWORD"] ??
    process.env["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return new ClickHouseJsonClient(config);
}

@Module({
  controllers: [PreciousMetalsController],
  providers: [
    { provide: PRECIOUS_METALS_POSTGRES, useFactory: postgresRepository },
    {
      provide: PRECIOUS_METALS_MARKET,
      useFactory: () => new ClickHousePreciousMetalsMarketRepository(clickhouseClient()),
    },
    {
      provide: PRECIOUS_METALS_FEATURES,
      useFactory: () => new ClickHousePreciousMetalsFeatureRepository(clickhouseClient()),
    },
    { provide: PRECIOUS_METALS_AUTHORIZER, useClass: AllowAllPreciousMetalsAuthorizer },
    { provide: PRECIOUS_METALS_CLOCK, useClass: SystemPreciousMetalsClock },
    PreciousMetalsService,
  ],
})
export class PreciousMetalsModule {}
