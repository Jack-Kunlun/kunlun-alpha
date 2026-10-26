import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ServerWatchlistItem } from "@kunlun/shared-types";
import { WatchlistDailyComparison, watchlistComparisonStocks } from "./watchlist-daily-comparison";

describe("watchlist daily comparison selection", () => {
  it("copies only canonical unique securities from the visible server page", () => {
    const items = [
      { code: "000001.SZ", name: "示例自选" },
      { code: "600519.SH", name: "示例自选二" },
      { code: "430047.BJ", name: "示例自选三" },
      { code: "HK:00700", name: "观察项" },
      { code: "NEEQ:430047", name: "观察项" },
      { code: "SGE:Au9999", name: "观察项" },
      { code: "000001.SZ", name: "重复" },
    ];
    const before = structuredClone(items);
    const stocks = watchlistComparisonStocks(items);
    expect(stocks.map((stock) => stock.instrumentId)).toEqual([
      "000001.SZ",
      "600519.SH",
      "430047.BJ",
    ]);
    expect(stocks[0]?.name).toBe("示例自选");
    items[0]!.name = "后续变化";
    expect(stocks[0]?.name).toBe(before[0]?.name);
    expect(stocks.every((stock) => stock.sector === "")).toBe(true);
  });
  it("keeps the action disabled for empty or unsupported pages, and the table absent until opened", () => {
    for (const items of [[], [{ code: "HK:00700", name: "观察项" }]]) {
      const html = renderToStaticMarkup(
        <WatchlistDailyComparison items={items as ServerWatchlistItem[]} />,
      );
      expect(html).toContain("对比本页日线");
      expect(html).toContain('disabled=""');
      expect(html).not.toContain("<table");
    }
    const html = renderToStaticMarkup(
      <WatchlistDailyComparison
        items={[{ code: "000001.SZ", name: "示例" }] as ServerWatchlistItem[]}
      />,
    );
    expect(html).not.toContain('disabled=""');
    expect(html).not.toContain("<table");
  });
  it("refuses to turn a larger list into an implicit full-watchlist query", () => {
    expect(() =>
      watchlistComparisonStocks(
        Array.from({ length: 21 }, (_, i) => ({ code: `${600000 + i}.SH`, name: "示例" })),
      ),
    ).toThrow("最多 20");
  });
});
