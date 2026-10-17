import { describe, expect, it } from "vitest";
import {
  parseWatchlistText,
  personalWatchlistHref,
  readPersonalWatchlist,
  savePersonalWatchlist,
  watchlistStorageKey,
} from "./personal-watchlist";

function storage(initial: string | null = null) {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_key: string, next: string) => {
      value = next;
    },
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
  it("merges without replacing existing names and survives a fresh read", () => {
    const store = storage();
    const key = watchlistStorageKey("local-user");
    expect(savePersonalWatchlist(store, key, parseWatchlistText("000001.SZ 原名称"))).toHaveLength(
      1,
    );
    expect(
      savePersonalWatchlist(store, key, parseWatchlistText("000001.SZ 新名称\n600519.SH 示例股票")),
    ).toHaveLength(2);
    expect(readPersonalWatchlist(store, key)[0]?.name).toBe("原名称");
  });
  it("does not overwrite corrupt or newer-version stored content", () => {
    for (const initial of ["{bad", '{"schemaVersion":"personal-watchlist-v2","items":[]}']) {
      const store = storage(initial);
      expect(() =>
        savePersonalWatchlist(store, "key", parseWatchlistText("600519.SH 示例股票")),
      ).toThrow();
      expect(store.getItem()).toBe(initial);
    }
  });
  it("reports unavailable storage without losing the existing list", () => {
    const store = storage();
    savePersonalWatchlist(store, "key", parseWatchlistText("000001.SZ 示例股票"));
    const previous = store.getItem();
    expect(() =>
      savePersonalWatchlist(
        {
          ...store,
          setItem: () => {
            throw new Error("QuotaExceeded");
          },
        },
        "key",
        parseWatchlistText("600519.SH 新增股票"),
      ),
    ).toThrow();
    expect(store.getItem()).toBe(previous);
  });
  it("keeps owner storage separate", () => {
    expect(watchlistStorageKey("one")).not.toBe(watchlistStorageKey("two"));
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
    const store = storage(
      '{"schemaVersion":"personal-watchlist-v1","items":[{"code":"BAD","name":"x"}]}',
    );
    expect(() =>
      savePersonalWatchlist(store, "key", parseWatchlistText("600519.SH 示例股票")),
    ).toThrow();
    expect(store.getItem()).toContain("BAD");
  });
});
