import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MarketCoverageDaysResponse } from "@kunlun/shared-types";
import { getMarketCoverageDaysPage, MarketCoverageDaysPanel } from "./market-coverage-days-panel";

const selection = {
  dateFrom: "2026-09-01",
  dateTo: "2026-09-04",
  unifiedCode: "600519.SH" as const,
  source: "tushare-pro" as const,
};

const response: MarketCoverageDaysResponse = {
  schemaVersion: "market-data-coverage-days-v1",
  scope: "DAILY_RAW_SINGLE_SUPPORTED_SOURCE",
  meaning: "OBSERVED_ONLY",
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.000Z",
  },
  unifiedCode: "600519.SH",
  source: "tushare-pro",
  days: [
    {
      date: "2026-09-03",
      latestEventTime: "2026-09-03T07:00:00.000Z",
      latestAvailableTime: "2026-09-03T07:01:00.000Z",
      latestProcessingTime: "2026-09-03T07:02:00.000Z",
    },
  ],
};

describe("MarketCoverageDaysPanel", () => {
  it("keeps independent loading, empty, error, and forbidden states", () => {
    expect(
      renderToStaticMarkup(
        <MarketCoverageDaysPanel
          result={{ status: "loading", data: null, error: null }}
          selection={selection}
        />,
      ),
    ).toContain("已观测日期加载中");
    expect(
      renderToStaticMarkup(
        <MarketCoverageDaysPanel
          result={{ status: "empty", data: response, error: null }}
          selection={selection}
        />,
      ),
    ).toContain("当前窗口暂无已观测日期");
    expect(
      renderToStaticMarkup(
        <MarketCoverageDaysPanel
          result={{ status: "error", data: null, error: new Error("secret") }}
          selection={selection}
        />,
      ),
    ).toContain("已观测日期暂不可用");
    expect(
      renderToStaticMarkup(
        <MarketCoverageDaysPanel
          result={{ status: "forbidden", data: null, error: new Error("secret") }}
          selection={selection}
        />,
      ),
    ).toContain("无权访问已观测日期");
  });

  it("shows independent asOf, observed-only semantics, and bounds large tables", () => {
    const manyDays: MarketCoverageDaysResponse = {
      ...response,
      window: {
        ...response.window,
        dateFrom: "2026-08-01",
        dateTo: "2026-09-29",
        asOf: "2026-10-01T02:00:00.000Z",
      },
      days: Array.from({ length: 60 }, (_, index) => ({
        date: new Date(Date.UTC(2026, 7, index + 1)).toISOString().slice(0, 10),
        latestEventTime: "2026-09-03T07:00:00.000Z",
        latestAvailableTime: "2026-09-03T07:01:00.000Z",
        latestProcessingTime: "2026-09-03T07:02:00.000Z",
      })),
    };
    const html = renderToStaticMarkup(
      <MarketCoverageDaysPanel
        result={{ status: "success", data: manyDays, error: null }}
        selection={{
          dateFrom: manyDays.window.dateFrom,
          dateTo: manyDays.window.dateTo,
          unifiedCode: manyDays.unifiedCode,
          source: manyDays.source,
        }}
      />,
    );
    expect(html).toContain("已观测日期");
    expect(html).toContain("独立查询 asOf");
    expect(html).toContain("可能与上方汇总不同");
    expect(html).toContain("仅表示已观测到的日期");
    expect(html).toContain("第 1/2 页");
    expect((html.match(/<tr/g) ?? []).length).toBe(51);
    expect(html).not.toContain("secret");
    expect(getMarketCoverageDaysPage(manyDays.days, 1).days).toHaveLength(10);
    expect(getMarketCoverageDaysPage(manyDays.days, 1).days[0]?.date).toBe("2026-09-20");
  });

  it("does not render a previous selection response after a quick switch", () => {
    const stale = { ...response, unifiedCode: "000001.SZ" };
    const html = renderToStaticMarkup(
      <MarketCoverageDaysPanel
        result={{ status: "success", data: stale, error: null }}
        selection={selection}
      />,
    );
    expect(html).toContain("已观测日期加载中");
    expect(html).not.toContain("000001.SZ");
  });

  it("keeps the selected window, identity and query time visible for zero observed dates", () => {
    const html = renderToStaticMarkup(
      <MarketCoverageDaysPanel
        result={{ status: "success", data: { ...response, days: [] }, error: null }}
        selection={selection}
      />,
    );
    expect(html).toContain("600519.SH");
    expect(html).toContain("tushare-pro");
    expect(html).toContain("2026-09-01 至 2026-09-04");
    expect(html).toContain("共 0 个已观测日期");
    expect(html).toContain("独立查询 asOf");
    expect(html).toContain("这不表示缺失");
  });
});
