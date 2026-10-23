import type { ServerWatchlistItem } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { selectPersonalWatchlistPage } from "./personal-watchlist-filters";

function item(
  code: string,
  name: string,
  status: ServerWatchlistItem["market"]["status"] = "SUCCEEDED",
): ServerWatchlistItem {
  return {
    code,
    name,
    addedAt: "2026-10-23T00:00:00.000Z",
    market: { status, lastAttemptAt: null, lastSuccessAt: null, errorCode: null },
  };
}

const items = [
  item("600519.SH", "示例沪股"),
  item("000001.SZ", "示例深股"),
  item("430047.BJ", "示例北股", "FAILED"),
  item("HK:00700", "港股观察项", "UNSUPPORTED"),
  item("NEEQ:430001", "新三板观察项", "PENDING"),
  item("SGE:AU99.99", "黄金观察项", "UNSUPPORTED"),
];

describe("personal watchlist filters", () => {
  it("preserves original objects and server order for all markets", () => {
    const snapshot = structuredClone(items);
    const view = selectPersonalWatchlistPage(items, { market: "ALL", query: "" }, 0);
    expect(view.items).toEqual(items);
    expect(view.items[0]).toBe(items[0]);
    expect(view.matchedCount).toBe(6);
    expect(items).toEqual(snapshot);
  });

  it.each([
    ["SH", ["600519.SH"]],
    ["SZ", ["000001.SZ"]],
    ["BJ", ["430047.BJ"]],
    ["OBSERVATION", ["HK:00700", "NEEQ:430001", "SGE:AU99.99"]],
  ] as const)(
    "filters %s by existing code classification, independently of collection status",
    (market, expected) => {
      const view = selectPersonalWatchlistPage(items, { market, query: "" }, 0);
      expect(view.items.map((value) => value.code)).toEqual(expected);
      expect(view.matchedCount).toBe(expected.length);
    },
  );

  it("combines a trimmed, case-insensitive code or name search with market", () => {
    expect(
      selectPersonalWatchlistPage(items, { market: "SH", query: " 600519.sh " }, 0).items,
    ).toEqual([items[0]]);
    expect(
      selectPersonalWatchlistPage(items, { market: "OBSERVATION", query: "新三板" }, 0).items,
    ).toEqual([items[4]]);
    expect(
      selectPersonalWatchlistPage(items, { market: "SZ", query: "600519" }, 0).matchedCount,
    ).toBe(0);
  });

  it("filters the entire list before counting and paging, including items beyond the first page", () => {
    const many = [
      ...Array.from({ length: 25 }, (_, index) => item(`${600000 + index}.SH`, `示例 ${index}`)),
      items[2]!,
    ];
    const view = selectPersonalWatchlistPage(many, { market: "BJ", query: "" }, 0);
    expect(view).toEqual({ items: [items[2]], matchedCount: 1, currentPage: 0, pageCount: 1 });
    expect(selectPersonalWatchlistPage(many, { market: "ALL", query: "" }, 0).items).toHaveLength(
      20,
    );
    expect(selectPersonalWatchlistPage(many, { market: "ALL", query: "" }, 99).items).toHaveLength(
      6,
    );
  });

  it("clamps stale pages and represents both an empty list and no matches as page one", () => {
    for (const list of [[], items]) {
      expect(
        selectPersonalWatchlistPage(list, { market: "ALL", query: "不存在的代码" }, 99),
      ).toEqual({
        items: [],
        matchedCount: 0,
        currentPage: 0,
        pageCount: 1,
      });
    }
    expect(selectPersonalWatchlistPage(items, { market: "ALL", query: "" }, -1).currentPage).toBe(
      0,
    );
  });

  it("does not label unknown identifiers as unconnected observation items", () => {
    const unknown = item("INVALID", "无效标识", "UNSUPPORTED");
    expect(
      selectPersonalWatchlistPage([unknown], { market: "OBSERVATION", query: "" }, 0).matchedCount,
    ).toBe(0);
  });
});
