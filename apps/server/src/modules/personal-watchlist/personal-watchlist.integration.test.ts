import type { PersonalWatchlistImportRequest } from "@kunlun/shared-types";
import { randomUUID } from "node:crypto";
import { MigrationRunner, PostgresSqlDriver } from "@kunlun/db";
import { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { migrations } from "../../migrations/012-personal-watchlist";
import { PersonalWatchlistRepository } from "./personal-watchlist.repository";
const dsn = process.env.PERSONAL_WATCHLIST_TEST_DSN;
describe.skipIf(!dsn)("isolated PostgreSQL watchlist persistence", () => {
  it("migrates idempotently, isolates users, survives reconnect and merges concurrent imports", async () => {
    const schema = "watchlist_test_" + randomUUID().replaceAll("-", "");
    const admin = new Pool({ connectionString: dsn });
    await admin.query(`CREATE SCHEMA ${schema}`);
    const config = { connectionString: dsn, options: `-csearch_path=${schema},public` };
    const pool = new Pool(config);
    const driver = new PostgresSqlDriver(pool);
    const repository = new PersonalWatchlistRepository(pool);
    try {
      await pool.query("CREATE TABLE auth_users(user_id UUID PRIMARY KEY)");
      const ownerA = randomUUID(),
        ownerB = randomUUID();
      await pool.query("INSERT INTO auth_users VALUES($1),($2)", [ownerA, ownerB]);
      expect(await new MigrationRunner(driver).migrate(migrations)).toBe(1);
      expect(await new MigrationRunner(driver).migrate(migrations)).toBe(0);
      const first: PersonalWatchlistImportRequest = {
        schemaVersion: "personal-watchlist-import-v1" as const,
        clientRequestId: randomUUID(),
        items: [
          { code: "600000.SH", name: "first" },
          { code: "HK:09618", name: "观察" },
        ],
      };
      await Promise.all([
        repository.importItems(ownerA, first),
        repository.importItems(ownerA, {
          ...first,
          clientRequestId: randomUUID(),
          items: [{ code: "600001.SH", name: "second" }],
        }),
      ]);
      await repository.importItems(ownerA, first);
      expect((await repository.list(ownerA)).items.map((x) => x.code)).toHaveLength(3);
      expect((await repository.list(ownerB)).items).toEqual([]);
      await expect(
        repository.importItems(ownerA, {
          ...first,
          items: [{ code: "600000.SH", name: "changed" }],
        }),
      ).rejects.toThrow("导入请求");
      await repository.importItems(ownerB, {
        ...first,
        clientRequestId: randomUUID(),
        items: [{ code: "600000.SH", name: "other owner" }],
      });
      const reconnect = new PersonalWatchlistRepository(new Pool(config));
      try {
        expect((await reconnect.list(ownerA)).items.find((x) => x.code === "600000.SH")?.name).toBe(
          "first",
        );
        expect((await reconnect.list(ownerB)).items[0]?.name).toBe("other owner");
      } finally {
        await reconnect.onModuleDestroy();
      }
    } finally {
      await pool.end();
      await admin.query(`DROP SCHEMA ${schema} CASCADE`);
      await admin.end();
    }
  }, 20000);
});
