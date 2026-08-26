import { Module } from "@nestjs/common";
import {
  ClickHouseLimitPoolRepository,
  type ClickHouseLimitPoolConfig,
} from "./clickhouse-limit-pool.repository";
import { EnvironmentLimitPoolAuthorizer } from "./limit-pool-authorizer";
import { LimitPoolController } from "./limit-pool.controller";
import type { LimitPoolRepository } from "./limit-pool.repository";
import { LimitPoolService } from "./limit-pool.service";
import { LIMIT_POOL_AUTHORIZER, LIMIT_POOL_REPOSITORY } from "./limit-pool.tokens";

type Environment = Readonly<Record<string, string | undefined>>;

export function resolveLimitPoolClickHouseConfig(
  environment: Environment = process.env,
): ClickHouseLimitPoolConfig {
  const url =
    environment["LIMIT_POOL_CLICKHOUSE_URL"] ??
    environment["DASHBOARD_CLICKHOUSE_URL"] ??
    environment["EMOTION_CLICKHOUSE_URL"];
  if (!url) throw new Error("LIMIT_POOL_CLICKHOUSE_URL is required");
  const config: ClickHouseLimitPoolConfig = {
    url,
    database:
      environment["LIMIT_POOL_CLICKHOUSE_DATABASE"] ??
      environment["DASHBOARD_CLICKHOUSE_DATABASE"] ??
      environment["EMOTION_CLICKHOUSE_DATABASE"] ??
      "kunlun",
    user:
      environment["LIMIT_POOL_CLICKHOUSE_USER"] ??
      environment["DASHBOARD_CLICKHOUSE_USER"] ??
      environment["EMOTION_CLICKHOUSE_USER"] ??
      "default",
  };
  const password =
    environment["LIMIT_POOL_CLICKHOUSE_PASSWORD"] ??
    environment["DASHBOARD_CLICKHOUSE_PASSWORD"] ??
    environment["EMOTION_CLICKHOUSE_PASSWORD"];
  if (password !== undefined) config.password = password;
  return config;
}

function repositoryFactory(): LimitPoolRepository {
  const config = resolveLimitPoolClickHouseConfig();
  return new ClickHouseLimitPoolRepository(config);
}

@Module({
  controllers: [LimitPoolController],
  providers: [
    { provide: LIMIT_POOL_REPOSITORY, useFactory: repositoryFactory },
    { provide: LIMIT_POOL_AUTHORIZER, useClass: EnvironmentLimitPoolAuthorizer },
    LimitPoolService,
  ],
  exports: [LimitPoolService],
})
export class LimitPoolModule {}
