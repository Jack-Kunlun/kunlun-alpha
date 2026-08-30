import { MemorySqlDriver, MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { migrations } from "./index";

describe("in-app notification receipt migration", () => {
  it("adds an append-only read receipt table without replacing the outbox", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);

    const migration = migrations.find((item) => item.version === 10);
    expect(migration?.up.map((table) => table.name)).toEqual(["watchlist_notification_receipts"]);
    expect(await driver.listTables()).toEqual(
      expect.arrayContaining(["watchlist_notification_outbox", "watchlist_notification_receipts"]),
    );
  });

  it("binds each receipt to a durable notification and owner", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 0 });
    const driver = new PostgresSqlDriver({ query, connect: vi.fn() } as unknown as Pool);
    const migration = migrations.find((item) => item.version === 10);
    expect(migration).toBeDefined();

    for (const table of migration?.up ?? []) await driver.createTable(table);

    const statement = String(query.mock.calls[0]?.[0]);
    expect(statement).toContain("watchlist_notification_outbox(notification_id)");
    expect(statement).toContain("watchlist_notification_receipt_owner_ck");
  });
});
