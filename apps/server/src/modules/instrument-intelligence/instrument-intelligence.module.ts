import { Module } from "@nestjs/common";
import { Pool } from "pg";
import {
  type ClickHouseIntelligenceConfig,
  ClickHouseJsonClient,
} from "./clickhouse-json-client";
import { ClickHouseInstrumentFeatureRepository } from "./clickhouse-feature.read-model";
import {
  ClickHouseInstrumentEmotionRepository,
  ClickHouseInstrumentMarketRepository,
} from "./clickhouse-market.read-model";
import { InstrumentIntelligenceController } from "./instrument-intelligence.controller";
import { SystemInstrumentIntelligenceClock } from "./instrument-intelligence.query";
import {
  AllowAllInstrumentIntelligenceAuthorizer,
  InstrumentIntelligenceService,
} from "./instrument-intelligence.service";
import {
  INSTRUMENT_INTELLIGENCE_AUTHORIZER,
  INSTRUMENT_INTELLIGENCE_CLOCK,
  INSTRUMENT_INTELLIGENCE_EMOTION,
  INSTRUMENT_INTELLIGENCE_FEATURES,
  INSTRUMENT_INTELLIGENCE_MARKET,
  INSTRUMENT_INTELLIGENCE_POSTGRES,
} from "./instrument-intelligence.tokens";
import { PostgresInstrumentContextRepository } from "./postgres-context.repository";

function postgresRepository(): PostgresInstrumentContextRepository {
  const dsn =
    process.env["INSTRUMENT_INTELLIGENCE_POSTGRES_DSN"] ??
    process.env["EVENT_INTELLIGENCE_POSTGRES_DSN"] ??
    process.env["KUNLUN_POSTGRES_DSN"];
  if (!dsn) throw new Error("INSTRUMENT_INTELLIGENCE_POSTGRES_DSN is required");
  return new PostgresInstrumentContextRepository(new Pool({ connectionString: dsn }));
}

function timeout(value: string | undefined): number {
  if (value === undefined) return 5_000;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 30_000) {
    throw new Error(
      "INSTRUMENT_INTELLIGENCE_CLICKHOUSE_TIMEOUT_MS must be between 1 and 30000",
    );
  }
  return parsed;
}

function clickhouseConfig(): ClickHouseIntelligenceConfig {
  const url =
    process.env["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_URL"] ??
    process.env["EMOTION_CLICKHOUSE_URL"];
  if (!url) throw new Error("INSTRUMENT_INTELLIGENCE_CLICKHOUSE_URL is required");
  const config: ClickHouseIntelligenceConfig = {
    url,
    database:
      process.env["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_DATABASE"] ??
      process.env["EMOTION_CLICKHOUSE_DATABASE"] ??
      "kunlun",
    user:
      process.env["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_USER"] ??
      process.env["EMOTION_CLICKHOUSE_USER"] ??
      "default",
    timeoutMs: timeout(process.env["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_TIMEOUT_MS"]),
  };
  const password =
    process.env["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_PASSWORD"] ??
    process.env["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return config;
}

function clickhouseClient(): ClickHouseJsonClient {
  return new ClickHouseJsonClient(clickhouseConfig());
}

@Module({
  controllers: [InstrumentIntelligenceController],
  providers: [
    { provide: INSTRUMENT_INTELLIGENCE_POSTGRES, useFactory: postgresRepository },
    {
      provide: INSTRUMENT_INTELLIGENCE_MARKET,
      useFactory: () => new ClickHouseInstrumentMarketRepository(clickhouseClient()),
    },
    {
      provide: INSTRUMENT_INTELLIGENCE_EMOTION,
      useFactory: () => new ClickHouseInstrumentEmotionRepository(clickhouseClient()),
    },
    {
      provide: INSTRUMENT_INTELLIGENCE_FEATURES,
      useFactory: () => new ClickHouseInstrumentFeatureRepository(clickhouseClient()),
    },
    {
      provide: INSTRUMENT_INTELLIGENCE_AUTHORIZER,
      useClass: AllowAllInstrumentIntelligenceAuthorizer,
    },
    {
      provide: INSTRUMENT_INTELLIGENCE_CLOCK,
      useClass: SystemInstrumentIntelligenceClock,
    },
    InstrumentIntelligenceService,
  ],
})
export class InstrumentIntelligenceModule {}
