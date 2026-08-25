import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("event intelligence read-model migration", () => {
  it("adds immutable event and topic snapshot tables", async () => {
    const driver = new MemorySqlDriver();
    const runner = new MigrationRunner(driver);
    expect(await runner.migrate(migrations)).toBe(4);
    expect(await driver.hasTable("market_events")).toBe(true);
    expect(await driver.hasTable("hot_topic_snapshots")).toBe(true);
    const topic = migrations[2]?.up.find((table) => table.name === "hot_topic_snapshots");
    expect(topic?.columns.map((column) => column.name)).toEqual(
      expect.arrayContaining([
        "decision_time",
        "algorithm_version",
        "policy_fingerprint",
        "payload",
      ]),
    );
  });
});
