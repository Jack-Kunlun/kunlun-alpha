import { Logger, Module } from "@nestjs/common";
import { Pool } from "pg";
import { DisabledMasterKeyProvider, createMasterKeyProvider } from "./market-data-settings.crypto";
import {
  MarketDataSettingsInternalController,
  MarketDataSettingsController,
} from "./market-data-settings.controller";
import { PostgresMarketDataSettingsRepository } from "./market-data-settings.repository";
import { MarketDataSettingsService } from "./market-data-settings.service";
import {
  MARKET_DATA_SETTINGS_KEY_PROVIDER,
  MARKET_DATA_SETTINGS_REPOSITORY,
} from "./market-data-settings.tokens";
import type { MarketDataSettingsRepository } from "./market-data-settings.types";

const marketDataSettingsLogger = new Logger("MarketDataSettings");

export function marketDataSettingsPoolOptions(connectionString: string) {
  return {
    connectionString,
    max: 4,
    connectionTimeoutMillis: 1_000,
    statement_timeout: 4_000,
    lock_timeout: 1_000,
    idle_in_transaction_session_timeout: 4_500,
  };
}

export function attachMarketDataSettingsPoolError(pool: Pool): void {
  pool.on("error", () => {
    marketDataSettingsLogger.error("market-data settings storage unavailable");
  });
}

export function createMarketDataSettingsPool(connectionString: string): Pool {
  const pool = new Pool(marketDataSettingsPoolOptions(connectionString));
  attachMarketDataSettingsPoolError(pool);
  return pool;
}

@Module({
  controllers: [MarketDataSettingsController, MarketDataSettingsInternalController],
  providers: [
    {
      provide: MARKET_DATA_SETTINGS_REPOSITORY,
      useFactory: (): MarketDataSettingsRepository => {
        const dsn = process.env["MARKET_DATA_SETTINGS_POSTGRES_DSN"]?.trim();
        const masterKey = nonBlank(process.env["MARKET_DATA_SETTINGS_MASTER_KEY"]);
        const masterKeyFile = nonBlank(process.env["MARKET_DATA_SETTINGS_MASTER_KEY_FILE"]);
        if (!dsn || (masterKey === undefined && masterKeyFile === undefined)) {
          return new DisabledMarketDataSettingsRepository();
        }
        return new PostgresMarketDataSettingsRepository(createMarketDataSettingsPool(dsn));
      },
    },
    {
      provide: MARKET_DATA_SETTINGS_KEY_PROVIDER,
      useFactory: () => {
        const dsn = process.env["MARKET_DATA_SETTINGS_POSTGRES_DSN"]?.trim();
        const masterKey = nonBlank(process.env["MARKET_DATA_SETTINGS_MASTER_KEY"]);
        const masterKeyFile = nonBlank(process.env["MARKET_DATA_SETTINGS_MASTER_KEY_FILE"]);
        if (!dsn || (masterKey === undefined && masterKeyFile === undefined)) {
          return new DisabledMasterKeyProvider();
        }
        return createMasterKeyProvider(process.env);
      },
    },
    MarketDataSettingsService,
  ],
})
export class MarketDataSettingsModule {}

class DisabledMarketDataSettingsRepository implements MarketDataSettingsRepository {
  async get(): Promise<never> {
    throw new Error("market-data settings feature is not configured");
  }

  async compareAndSet(
    _input: Parameters<MarketDataSettingsRepository["compareAndSet"]>[0],
  ): Promise<never> {
    throw new Error("market-data settings feature is not configured");
  }
}

function nonBlank(value: string | undefined): string | undefined {
  return value !== undefined && value.trim() !== "" ? value : undefined;
}
