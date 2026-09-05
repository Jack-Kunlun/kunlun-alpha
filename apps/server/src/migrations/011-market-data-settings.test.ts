import { MemorySqlDriver, MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { migrations } from "./index";

describe("market-data settings migration", () => {
  it("creates singleton encrypted settings and secret-free audit tables", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);

    expect(await driver.listTables()).toEqual(
      expect.arrayContaining(["market_data_instance_settings", "market_data_settings_audit"]),
    );
    const migration = migrations.find((item) => item.version === 11);
    expect(migration?.up[0]?.constraints?.join(" ")).toContain("token_ciphertext");
    const auditColumns = migration?.up[1]?.columns.map((column) => column.name) ?? [];
    expect(auditColumns).not.toContain("token");
    expect(auditColumns).not.toContain("token_digest");
    expect(auditColumns).not.toContain("ciphertext");
  });

  it("keeps PostgreSQL DDL parameter-free and within the migration allowlist", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 0 });
    const driver = new PostgresSqlDriver({ query, connect: vi.fn() } as unknown as Pool);
    const migration = migrations.find((item) => item.version === 11);
    expect(migration).toBeDefined();

    for (const table of migration?.up ?? []) await driver.createTable(table);

    expect(query).toHaveBeenCalledTimes(5);
    expect(String(query.mock.calls[0]?.[0])).toContain("market_data_settings_envelope_ck");
    expect(String(query.mock.calls[1]?.[0])).toContain(
      "market_data_instance_settings_revision_idx",
    );
  });
});
