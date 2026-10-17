import { createHash } from "node:crypto";
import type { Pool } from "pg";
import { describe, expect, it, vi } from "vitest";
import { PersonalWatchlistRepository } from "./personal-watchlist.repository";
import type { PersonalWatchlistImportRequest } from "@kunlun/shared-types";
const command: PersonalWatchlistImportRequest = {
  schemaVersion: "personal-watchlist-import-v1",
  clientRequestId: "00000000-0000-4000-8000-000000000001",
  items: [{ code: "600000.SH", name: "示例" }],
};
function setup(previous: string | null = null, full = false, insertFails = false) {
  const calls: { sql: string; params: unknown }[] = [];
  const query = vi.fn(async (sql: string, params?: unknown[]) => {
    calls.push({ sql, params });
    if (sql.includes("SELECT command_hash"))
      return { rows: previous === null ? [] : [{ command_hash: previous }] };
    if (sql === "SELECT code FROM personal_watchlist_items WHERE owner_id=$1")
      return { rows: full ? Array.from({ length: 2000 }, (_, i) => ({ code: String(i) })) : [] };
    if (insertFails && sql.includes("INSERT INTO personal_watchlist_items"))
      throw new Error("disk failure");
    return { rows: [] };
  });
  const client = { query, release: vi.fn() };
  const pool = {
    connect: vi.fn(async () => client),
    query: vi.fn(async (sql: string, params: unknown[]) => {
      calls.push({ sql, params });
      return { rows: [] };
    }),
    end: vi.fn(),
  };
  return { repo: new PersonalWatchlistRepository(pool as unknown as Pool), calls, client };
}
describe("owned transactional import", () => {
  it("locks the authenticated owner, merges atomically and scopes response to that owner", async () => {
    const { repo, calls, client } = setup();
    await repo.importItems("owner-a", command);
    expect(calls[0]?.sql).toBe("BEGIN");
    expect(calls[1]?.params).toEqual(["personal-watchlist:owner-a"]);
    expect(calls.find((x) => x.sql.includes("ON CONFLICT"))?.params).toEqual([
      "owner-a",
      JSON.stringify(command.items),
    ]);
    expect(calls.at(-2)?.sql).toBe("COMMIT");
    expect(calls.at(-1)?.params).toEqual(["owner-a"]);
    expect(client.release).toHaveBeenCalledOnce();
  });
  it("replays the same command without writes and rejects changed content", async () => {
    const hash = createHash("sha256").update(JSON.stringify(command.items)).digest("hex");
    const retry = setup(hash);
    await retry.repo.importItems("owner-a", command);
    expect(retry.calls.some((x) => x.sql.includes("INSERT"))).toBe(false);
    const conflict = setup("different");
    await expect(conflict.repo.importItems("owner-a", command)).rejects.toThrow("导入请求");
    expect(conflict.calls.at(-1)?.sql).toBe("ROLLBACK");
  });
  it("rolls back both cap overflow and storage failure without acknowledging a command", async () => {
    for (const env of [setup(null, true), setup(null, false, true)]) {
      await expect(env.repo.importItems("owner-a", command)).rejects.toThrow();
      expect(env.calls.at(-1)?.sql).toBe("ROLLBACK");
      expect(env.calls.some((x) => x.sql.includes("INSERT INTO personal_watchlist_imports"))).toBe(
        false,
      );
    }
  });
});
