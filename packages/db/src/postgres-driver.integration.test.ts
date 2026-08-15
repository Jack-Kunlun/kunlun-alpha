import { randomUUID } from "node:crypto";

import { Pool } from "pg";
import { describe, expect, it } from "vitest";

import { MigrationRunner, PostgresSqlDriver, type Migration } from "./index";

const dsn = process.env.KUNLUN_TEST_POSTGRES_DSN;
const run = dsn ? describe : describe.skip;

const migrations: Migration[] = [
  {
    version: 1,
    name: "create_first",
    up: [
      {
        name: "first_table",
        columns: [{ name: "id", type: "TEXT", primaryKey: true, notNull: true }],
      },
    ],
    down: ["first_table"],
  },
  {
    version: 2,
    name: "create_second",
    up: [
      {
        name: "second_table",
        columns: [{ name: "id", type: "TEXT", primaryKey: true, notNull: true }],
      },
    ],
    down: ["second_table"],
  },
];

run("PostgresSqlDriver integration", () => {
  it("migrates, rolls back metadata, and can re-migrate in an isolated schema", async () => {
    const context = await openSchema();
    try {
      const runner = new MigrationRunner(context.driver);
      expect(await runner.migrate(migrations)).toBe(2);
      expect(await runner.migrate(migrations)).toBe(0);
      expect(await runner.rollback(migrations, 1)).toBe(1);
      expect(await runner.appliedVersions()).toEqual(new Set([1]));
      expect(await runner.migrate(migrations)).toBe(1);
      expect(await context.driver.listTables()).toEqual([
        "first_table",
        "schema_migrations",
        "second_table",
      ]);
    } finally {
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });

  it("rolls back failed migration DDL and metadata atomically", async () => {
    const context = await openSchema();
    try {
      const runner = new MigrationRunner(context.driver);
      await runner.migrate(migrations);
      const failing: Migration = {
        version: 3,
        name: "failing",
        up: [
          {
            name: "temporary_table",
            columns: [{ name: "id", type: "TEXT", primaryKey: true, notNull: true }],
          },
          {
            name: "duplicate_table",
            columns: [{ name: "id", type: "TEXT", primaryKey: true, notNull: true }],
          },
          {
            name: "duplicate_table",
            columns: [{ name: "id", type: "TEXT", primaryKey: true, notNull: true }],
          },
        ],
        down: ["duplicate_table", "temporary_table"],
      };
      await expect(runner.migrate([...migrations, failing])).rejects.toThrow(/already exists/);
      expect(await context.driver.hasTable("temporary_table")).toBe(false);
      expect(await context.driver.hasTable("duplicate_table")).toBe(false);
      expect(await runner.appliedVersions()).toEqual(new Set([1, 2]));
    } finally {
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });

  it("serializes concurrent migration runners with the database advisory lock", async () => {
    const schema = `test_${randomUUID().replaceAll("-", "")}`;
    await createSchema(schema);
    const first = await openDriver(schema);
    const second = await openDriver(schema);
    try {
      const [firstCount, secondCount] = await Promise.all([
        new MigrationRunner(first).migrate(migrations),
        new MigrationRunner(second).migrate(migrations),
      ]);
      expect(firstCount + secondCount).toBe(2);
      expect(await first.listTables()).toContain("second_table");
    } finally {
      await first.close();
      await second.close();
      await dropSchema(schema);
    }
  });

  it("runs migrations with a max-one pool without waiting for a second client", async () => {
    const schema = `test_${randomUUID().replaceAll("-", "")}`;
    await createSchema(schema);
    const driver = new PostgresSqlDriver({
      connectionString: dsn,
      max: 1,
      connectionTimeoutMillis: 1000,
      options: `-c search_path="${schema}"`,
    });
    try {
      const result = await Promise.race([
        new MigrationRunner(driver).migrate(migrations),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("migration lock timed out")), 900),
        ),
      ]);
      expect(result).toBe(2);
    } finally {
      await driver.close();
      await dropSchema(schema);
    }
  });

  it("rejects unsafe migration identifiers and SQL types", async () => {
    const context = await openSchema();
    try {
      await expect(
        context.driver.createTable({
          name: "unsafe;drop",
          columns: [{ name: "id", type: "TEXT" }],
        }),
      ).rejects.toThrow(/unsafe SQL identifier/);
      await expect(
        context.driver.createTable({
          name: "unsafe_type",
          columns: [{ name: "id", type: "TEXT; DROP TABLE tasks" }],
        }),
      ).rejects.toThrow(/unsupported SQL type/);
    } finally {
      await context.driver.close();
      await dropSchema(context.schema);
    }
  });
});

async function openSchema(): Promise<{ driver: PostgresSqlDriver; schema: string }> {
  const schema = `test_${randomUUID().replaceAll("-", "")}`;
  await createSchema(schema);
  return { driver: await openDriver(schema), schema };
}

async function openDriver(schema: string): Promise<PostgresSqlDriver> {
  if (!dsn) {
    throw new Error("KUNLUN_TEST_POSTGRES_DSN is required");
  }
  return new PostgresSqlDriver({
    connectionString: dsn,
    options: `-c search_path="${schema}"`,
  });
}

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
