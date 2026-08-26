import { MemorySqlDriver, MigrationRunner } from "@kunlun/db";
import { describe, expect, it } from "vitest";
import { migrations } from "./index";

describe("watchlist alerts migration", () => {
  it("creates immutable rule and history ledgers plus a delivery outbox", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);
    const migration = migrations.find((item) => item.version === 8);

    expect(migration?.up.map((table) => table.name)).toEqual([
      "watchlist_alert_rule_revisions",
      "watchlist_alert_history",
      "watchlist_notification_outbox",
    ]);
    expect(
      migration?.up
        .find((table) => table.name === "watchlist_alert_history")
        ?.indexes?.find((index) => index.name === "watchlist_history_event_uq")?.unique,
    ).toBe(true);
    expect(
      migration?.up
        .find((table) => table.name === "watchlist_notification_outbox")
        ?.columns.map((column) => column.name),
    ).toEqual(expect.arrayContaining(["status", "attempts", "last_error"]));
  });
});
