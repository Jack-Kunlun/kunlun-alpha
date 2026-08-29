import { MemorySqlDriver, MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { migrations } from "./index";

describe("local administrator authentication migration", () => {
  it("creates durable users, sessions and login-attempt history", async () => {
    const driver = new MemorySqlDriver();
    await new MigrationRunner(driver).migrate(migrations);

    const migration = migrations.find((item) => item.version === 9);
    expect(migration?.up.map((table) => table.name)).toEqual([
      "auth_users",
      "auth_sessions",
      "auth_login_attempts",
    ]);
    expect(await driver.listTables()).toEqual(
      expect.arrayContaining([
        "auth_users",
        "auth_sessions",
        "auth_login_attempts",
        "schema_migrations",
      ]),
    );
    expect(migration?.up.flatMap((table) => table.constraints ?? []).join(" ")).toContain(
      "platform_admin",
    );
  });

  it("keeps every authentication constraint inside the PostgreSQL migration allowlist", async () => {
    const query = vi.fn().mockResolvedValue({ rows: [], rowCount: 0 });
    const driver = new PostgresSqlDriver({ query, connect: vi.fn() } as unknown as Pool);
    const migration = migrations.find((item) => item.version === 9);
    expect(migration).toBeDefined();

    for (const table of migration?.up ?? []) await driver.createTable(table);

    expect(query).toHaveBeenCalledTimes(8);
    expect(query.mock.calls[0]?.[0]).toContain("auth_user_username_ck");
    expect(query.mock.calls[0]?.[0]).toContain("jsonb_array_length");
  });
});
