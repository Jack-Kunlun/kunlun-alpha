import { Module } from "@nestjs/common";
import { Pool } from "pg";
import {
  type ClickHouseIntelligenceConfig,
  ClickHouseJsonClient,
} from "../instrument-intelligence/clickhouse-json-client";
import { ClickHouseMarketCoverageReadModel } from "./clickhouse-market-coverage.read-model";
import { DataQualityController } from "./data-quality.controller";
import { DataQualityService } from "./data-quality.service";
import { PostgresQualityRepository } from "./postgres-quality.repository";
import { AllowAllAuthorizer } from "./data-quality.authorizer";
import {
  MARKET_COVERAGE_CLOCK,
  MARKET_COVERAGE_READ_MODEL,
  QUALITY_AUTHORIZER,
  QUALITY_REPOSITORY,
} from "./data-quality.tokens";
import type { QualityRepository } from "./quality-repository";
import { SystemMarketCoverageClock } from "./market-coverage.query";
import type { MarketCoverageReadModel } from "./market-coverage.read-model";
import { UnavailableMarketCoverageReadModel } from "./market-coverage.read-model";
import {
  FileMarketQualityEvidenceReadModel,
  UnavailableMarketQualityEvidenceReadModel,
  type MarketQualityEvidenceReadModel,
} from "./market-quality-evidence.read-model";
import {
  FileMarketQualityEvidenceSnapshotReader,
} from "./market-quality-evidence.reader";
import { MARKET_QUALITY_EVIDENCE_READ_MODEL } from "./data-quality.tokens";

function buildRepository(): QualityRepository {
  const dsn = process.env["DATA_QUALITY_POSTGRES_DSN"];
  if (!dsn) {
    throw new Error("DATA_QUALITY_POSTGRES_DSN is required for the data-quality repository");
  }
  return new PostgresQualityRepository(new Pool({ connectionString: dsn }));
}

function timeout(value: string | undefined): number {
  if (value === undefined) return 5_000;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 30_000) {
    throw new Error("INSTRUMENT_INTELLIGENCE_CLICKHOUSE_TIMEOUT_MS must be between 1 and 30000");
  }
  return parsed;
}

function buildMarketCoverageReadModel(): MarketCoverageReadModel {
  const environment = process.env;
  const url =
    environment["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_URL"] ?? environment["EMOTION_CLICKHOUSE_URL"];
  if (!url) return new UnavailableMarketCoverageReadModel();
  const config: ClickHouseIntelligenceConfig = {
    url,
    database:
      environment["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_DATABASE"] ??
      environment["EMOTION_CLICKHOUSE_DATABASE"] ??
      "kunlun",
    user:
      environment["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_USER"] ??
      environment["EMOTION_CLICKHOUSE_USER"] ??
      "default",
    timeoutMs: timeout(environment["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_TIMEOUT_MS"]),
  };
  const password =
    environment["INSTRUMENT_INTELLIGENCE_CLICKHOUSE_PASSWORD"] ??
    environment["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return new ClickHouseMarketCoverageReadModel(new ClickHouseJsonClient(config));
}

function buildMarketQualityEvidenceReadModel(): MarketQualityEvidenceReadModel {
  const root = process.env["MARKET_DATA_QUALITY_PUBLIC_ROOT"]?.trim();
  if (!root) return new UnavailableMarketQualityEvidenceReadModel();
  return new FileMarketQualityEvidenceReadModel(
    new FileMarketQualityEvidenceSnapshotReader(root),
  );
}

@Module({
  controllers: [DataQualityController],
  providers: [
    { provide: QUALITY_REPOSITORY, useFactory: buildRepository },
    { provide: MARKET_COVERAGE_READ_MODEL, useFactory: buildMarketCoverageReadModel },
    {
      provide: MARKET_QUALITY_EVIDENCE_READ_MODEL,
      useFactory: buildMarketQualityEvidenceReadModel,
    },
    {
      provide: MARKET_COVERAGE_CLOCK,
      useClass: SystemMarketCoverageClock,
    },
    { provide: QUALITY_AUTHORIZER, useClass: AllowAllAuthorizer },
    DataQualityService,
  ],
  exports: [DataQualityService],
})
export class DataQualityModule {}
