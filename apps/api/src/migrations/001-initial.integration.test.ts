import { randomUUID } from "node:crypto";

import { Pool } from "pg";
import { describe, expect, it } from "vitest";

import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import { migrations } from "./001-initial";

const dsn = process.env.KUNLUN_TEST_POSTGRES_DSN;
const run = dsn ? describe : describe.skip;

run("initial PostgreSQL migration integration", () => {
  it("creates and rolls back the complete control-plane schema", async () => {
    const schema = `api_test_${randomUUID().replaceAll("-", "")}`;
    await createSchema(schema);
    const driver = new PostgresSqlDriver({
      connectionString: dsn,
      options: `-c search_path="${schema}"`,
    });
    try {
      const runner = new MigrationRunner(driver);
      expect(await runner.migrate(migrations)).toBe(1);
      expect(await driver.listTables()).toEqual([
        "checkpoints",
        "data_versions",
        "providers",
        "quality_events",
        "schema_migrations",
        "tasks",
      ]);
      expect(await runner.migrate(migrations)).toBe(0);
      expect(await runner.rollback(migrations, 0)).toBe(1);
      expect(await driver.listTables()).toEqual(["schema_migrations"]);
    } finally {
      await driver.close();
      await dropSchema(schema);
    }
  });
});

async function createSchema(schema: string): Promise<void> {
  if (!dsn) {
    throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  }
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`CREATE SCHEMA "${schema}"`);
  } finally {
    await pool.end();
  }
}

async function dropSchema(schema: string): Promise<void> {
  if (!dsn) {
    throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  }
  const pool = new Pool({ connectionString: dsn });
  try {
    await pool.query(`DROP SCHEMA "${schema}" CASCADE`);
  } finally {
    await pool.end();
  }
}
