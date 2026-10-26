import { describe, expect, it } from "vitest";
import type { MarketCoverageResponse } from "@kunlun/shared-types";
import { selectMarketCoveragePage } from "./market-coverage-browser";

type Row = MarketCoverageResponse["rows"][number];
const rows: Row[] = Array.from({ length: 43 }, (_, index) => ({
  unifiedCode: `${600000 + index}.SH`,
  source: index % 2 === 0 ? "akshare-tencent" : "tushare-pro",
  observedBarDays: 2,
  firstDate: "2026-10-22",
  lastDate: "2026-10-23",
  latestEventTime: "2026-10-23T07:00:00Z",
  latestAvailableTime: "2026-10-23T07:01:00Z",
  latestProcessingTime: "2026-10-23T07:02:00Z",
}));

describe("selectMarketCoveragePage", () => {
  it("pages the returned groups as 20 + 20 + 3 without changing order or input", () => {
    const original = structuredClone(rows);
    expect(selectMarketCoveragePage(rows, "", 0)).toMatchObject({
      rows: rows.slice(0, 20),
      matchedCount: 43,
      currentPage: 0,
      pageCount: 3,
    });
    expect(selectMarketCoveragePage(rows, "", 1).rows).toEqual(rows.slice(20, 40));
    expect(selectMarketCoveragePage(rows, "", 2).rows).toEqual(rows.slice(40));
    expect(rows).toEqual(original);
  });

  it("searches the complete returned list before paging by trimmed case-insensitive code or source", () => {
    expect(selectMarketCoveragePage(rows, " 600042.sh ", 0).rows).toEqual([rows[42]]);
    const source = selectMarketCoveragePage(rows, " AKSHARE-TENCENT ", 0);
    expect(source.matchedCount).toBe(22);
    expect(source.rows).toEqual(
      rows.filter((row) => row.source === "akshare-tencent").slice(0, 20),
    );
    expect(selectMarketCoveragePage(rows, "600042.SH akshare", 0).rows).toEqual([rows[42]]);
  });

  it("retains separate groups for the same security with different sources", () => {
    const sameSecurity: Row[] = [
      { ...rows[0]!, source: "akshare-tencent" },
      { ...rows[0]!, source: "tushare-pro" },
    ];
    expect(selectMarketCoveragePage(sameSecurity, "600000", 0).matchedCount).toBe(2);
    expect(selectMarketCoveragePage(sameSecurity, "TUSHARE", 0).rows).toEqual([sameSecurity[1]]);
  });

  it("returns an honest one-page no-match result", () => {
    expect(selectMarketCoveragePage(rows, "not-present", 3)).toEqual({
      rows: [],
      matchedCount: 0,
      currentPage: 0,
      pageCount: 1,
    });
    expect(selectMarketCoveragePage([], "", 99)).toEqual({
      rows: [],
      matchedCount: 0,
      currentPage: 0,
      pageCount: 1,
    });
  });

  it.each([-1, Number.NaN, Number.POSITIVE_INFINITY, 1.5])(
    "starts at the first page for invalid index %s",
    (index) => {
      expect(selectMarketCoveragePage(rows, "", index).currentPage).toBe(0);
    },
  );

  it("clamps stale pages when filters or returned results shrink", () => {
    expect(selectMarketCoveragePage(rows, "", 99).currentPage).toBe(2);
    expect(selectMarketCoveragePage(rows, "600042", 2).rows).toEqual([rows[42]]);
    expect(selectMarketCoveragePage(rows.slice(0, 2), "", 2).currentPage).toBe(0);
  });
});
