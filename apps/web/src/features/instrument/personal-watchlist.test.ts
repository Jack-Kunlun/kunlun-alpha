import { describe, expect, it } from "vitest";
import {
  completePersonalWatchlistMigration,
  getOrCreatePersonalWatchlistMigration,
  parseWatchlistText,
  personalWatchlistHref,
  readPersonalWatchlist,
  watchlistStorageKey,
} from "./personal-watchlist";

function storage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, next: string) => values.set(key, next),
    snapshot: (key: string) => values.get(key) ?? null,
  };
}

describe("personal watchlist import", () => {
  it("normalizes canonical codes, keeps funds and deduplicates by code", () => {
    expect(
      parseWatchlistText("000001.sz 平安银行\n512400.SH 示例基金\n000001.SZ 平安银行"),
    ).toEqual([
      { code: "000001.SZ", name: "平安银行" },
      { code: "512400.SH", name: "示例基金" },
    ]);
  });
  it.each(["", "600519 贵州茅台", "BAD.SH 错误", "600519.SH", "600519.SH <script>"])(
    "rejects invalid import without accepting part of it: %s",
    (text) => {
      expect(() => parseWatchlistText(text)).toThrow();
    },
  );
  it("reads and preserves the local migration backup", () => {
    const key = watchlistStorageKey("local-user");
    const backup = JSON.stringify({
      schemaVersion: "personal-watchlist-v1",
      items: parseWatchlistText("000001.SZ 原名称\n600519.SH 示例股票"),
    });
    const store = storage({ [key]: backup });
    const items = readPersonalWatchlist(store, key);
    expect(items).toHaveLength(2);
    const migration = getOrCreatePersonalWatchlistMigration(
      store,
      "local-user",
      items,
      () => "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1",
    );
    completePersonalWatchlistMigration(store, "local-user", migration);
    expect(store.snapshot(key)).toBe(backup);
  });
  it("does not overwrite corrupt or newer-version backup content", () => {
    for (const initial of ["{bad", '{"schemaVersion":"personal-watchlist-v2","items":[]}']) {
      const key = watchlistStorageKey("local-user");
      const store = storage({ [key]: initial });
      expect(() => readPersonalWatchlist(store, key)).toThrow();
      expect(store.snapshot(key)).toBe(initial);
    }
  });
  it("keeps owner storage separate", () => {
    expect(watchlistStorageKey("one")).not.toBe(watchlistStorageKey("two"));
  });
  it("reuses a pending command id for the same snapshot and creates a new one after completion", () => {
    const store = storage();
    const items = parseWatchlistText("000001.SZ 示例股票");
    const first = getOrCreatePersonalWatchlistMigration(
      store,
      "local-user",
      items,
      () => "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1",
    );
    const retry = getOrCreatePersonalWatchlistMigration(
      store,
      "local-user",
      items,
      () => "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    expect(retry).toEqual(first);
    completePersonalWatchlistMigration(store, "local-user", first);
    const later = getOrCreatePersonalWatchlistMigration(
      store,
      "local-user",
      items,
      () => "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    );
    expect(later.clientRequestId).toBe("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    expect(later.status).toBe("PENDING");
  });
  it("retains unsupported observations without exposing an instrument query path", () => {
    for (const item of parseWatchlistText(
      "HK:09618 观察项\nSGE:AU99.99 观察项\nNEEQ:831598 观察项",
    )) {
      expect(personalWatchlistHref(item)).toBeNull();
    }
    expect(personalWatchlistHref(parseWatchlistText("920885.BJ 示例股票")[0]!)).toBe(
      "/instruments/920885.BJ",
    );
  });
  it("limits imports and protects malformed stored entries", () => {
    expect(() =>
      parseWatchlistText(Array.from({ length: 2001 }, () => "000001.SZ 示例股票").join("\n")),
    ).toThrow();
    const key = watchlistStorageKey("local-user");
    const malformed =
      '{"schemaVersion":"personal-watchlist-v1","items":[{"code":"BAD","name":"x"}]}';
    const store = storage({ [key]: malformed });
    expect(() => readPersonalWatchlist(store, key)).toThrow();
    expect(store.snapshot(key)).toBe(malformed);
  });
});
