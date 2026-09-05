import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";

import { migrations } from "./migrations";
import { migrations as marketDataSettingsMigrations } from "./migrations/011-market-data-settings";

export function migrationSetForMode(settingsOnly: boolean) {
  return settingsOnly ? marketDataSettingsMigrations : migrations;
}

export async function migratePostgres(dsn: string, migrationSet = migrations): Promise<number> {
  const driver = new PostgresSqlDriver({ connectionString: dsn });
  try {
    return await new MigrationRunner(driver).migrate(migrationSet);
  } finally {
    await driver.close();
  }
}

async function main(): Promise<void> {
  const settingsOnly = process.argv.includes("--market-data-settings");
  const dsn = settingsOnly
    ? process.env["MARKET_DATA_SETTINGS_POSTGRES_DSN"]
    : process.env["KUNLUN_POSTGRES_DSN"];
  if (!dsn) {
    throw new Error(
      settingsOnly
        ? "MARKET_DATA_SETTINGS_POSTGRES_DSN is required for market-data settings migrations"
        : "KUNLUN_POSTGRES_DSN is required for migrations",
    );
  }

  const count = await migratePostgres(dsn, migrationSetForMode(settingsOnly));
  console.log(`PostgreSQL migrations applied: ${count}`);
}

if (require.main === module) {
  void main().catch((error: unknown) => {
    if (process.argv.includes("--market-data-settings")) {
      console.error("Market-data settings migration failed");
    } else {
      console.error("PostgreSQL migration failed:", error);
    }
    process.exitCode = 1;
  });
}
