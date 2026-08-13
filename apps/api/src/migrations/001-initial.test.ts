import { describe, expect, it } from "vitest";
import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { migrations } from "./001-initial";

describe("initial business model migration", () => {
  it("upgrades an empty database with all five tables", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);

    await runner.migrate(migrations);

    const tables = await driver.listTables();
    for (const name of ["providers", "tasks", "checkpoints", "data_versions", "quality_events"]) {
      expect(tables).toContain(name);
    }
  });

  it("is idempotent on repeat runs", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);

    await runner.migrate(migrations);
    const second = await runner.migrate(migrations);

    expect(second).toBe(0);
  });

  it("rolls back all business tables", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    await runner.migrate(migrations);

    await runner.rollback(migrations, 0);

    expect(await driver.hasTable("providers")).toBe(false);
    expect(await driver.hasTable("tasks")).toBe(false);
  });
});
