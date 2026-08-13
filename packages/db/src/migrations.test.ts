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
});
