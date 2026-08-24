import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("event feedback migration", () => {
  it("adds an append-only feedback table after the initial schema", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    expect(await runner.migrate(migrations.slice(0, 2))).toBe(2);
    expect(await driver.hasTable("event_feedback")).toBe(true);
    const table = migrations[1]?.up[0];
    expect(table?.columns.map((column) => column.name)).toEqual(
      expect.arrayContaining([
        "event_id",
        "model_configuration_fingerprint",
        "reviewer_ref",
        "submission_fingerprint",
        "available_at",
      ]),
    );
  });

  it("rolls back feedback without rewriting the initial migration", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    await runner.migrate(migrations);
    await runner.rollback(migrations, 1);
    expect(await driver.hasTable("event_feedback")).toBe(false);
    expect(await driver.hasTable("providers")).toBe(true);
  });
});
