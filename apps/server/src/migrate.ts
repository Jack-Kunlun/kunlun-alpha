import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";

import { migrations } from "./migrations";

export async function migratePostgres(dsn: string): Promise<number> {
  const driver = new PostgresSqlDriver({ connectionString: dsn });
  try {
    return await new MigrationRunner(driver).migrate(migrations);
  } finally {
    await driver.close();
  }
}

async function main(): Promise<void> {
  const dsn = process.env["KUNLUN_POSTGRES_DSN"];
  if (!dsn) {
    throw new Error("KUNLUN_POSTGRES_DSN is required for migrations");
  }

  const count = await migratePostgres(dsn);
  console.log(`PostgreSQL migrations applied: ${count}`);
}

if (require.main === module) {
  void main().catch((error: unknown) => {
    console.error("PostgreSQL migration failed:", error);
    process.exitCode = 1;
  });
}
