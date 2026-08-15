import { describe, expect, it } from "vitest";
import { MemorySqlDriver, MigrationRunner, type Migration } from "./index";

const migrations: Migration[] = [
  {
    version: 1,
    name: "create_providers",
    up: [
      {
        name: "providers",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "name", type: "TEXT", notNull: true },
        ],
      },
    ],
    down: ["providers"],
  },
  {
    version: 2,
    name: "create_tasks",
    up: [
      {
        name: "tasks",
        columns: [
          { name: "id", type: "TEXT", primaryKey: true, notNull: true },
          { name: "status", type: "TEXT", notNull: true },
        ],
      },
    ],
    down: ["tasks"],
  },
];

describe("MigrationRunner", () => {
  it("upgrades an empty database fully", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);

    const count = await runner.migrate(migrations);

    expect(count).toBe(2);
    const tables = await driver.listTables();
    expect(tables).toContain("providers");
    expect(tables).toContain("tasks");
  });

  it("is idempotent across repeated runs", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);

    await runner.migrate(migrations);
    const second = await runner.migrate(migrations);

    expect(second).toBe(0);
  });

  it("rolls back to a target version", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    await runner.migrate(migrations);

    await runner.rollback(migrations, 1);

    expect(await driver.hasTable("tasks")).toBe(false);
    expect(await driver.hasTable("providers")).toBe(true);
  });

  it("enforces primary-key constraints", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    await runner.migrate(migrations);

    await driver.insert("providers", { id: "p1", name: "provider-a" });
    await expect(driver.insert("providers", { id: "p1", name: "provider-b" })).rejects.toThrow(
      /duplicate primary key/,
    );
  });

  it("rolls back a failed migration including its metadata record", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    const failing: Migration = {
      version: 3,
      name: "failing_migration",
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

    await expect(runner.migrate([failing])).rejects.toThrow(/already exists/);

    expect(await driver.hasTable("temporary_table")).toBe(false);
    expect(await driver.hasTable("duplicate_table")).toBe(false);
    expect(await runner.appliedVersions()).not.toContain(3);
  });

  it("removes migration metadata when a migration is rolled back", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);

    await runner.migrate(migrations);
    await runner.rollback(migrations, 1);

    expect(await runner.appliedVersions()).toEqual(new Set([1]));
    await runner.migrate(migrations);
    expect(await runner.appliedVersions()).toEqual(new Set([1, 2]));
  });

  it("serializes concurrent migration runners behind the migration lock", async () => {
    const driver = new MemorySqlDriver();
    const first = new MigrationRunner(driver);
    const second = new MigrationRunner(driver);

    const counts = await Promise.all([first.migrate(migrations), second.migrate(migrations)]);

    expect(counts.reduce((sum, count) => sum + count, 0)).toBe(2);
    expect(await driver.query("schema_migrations")).toHaveLength(2);
  });
});
