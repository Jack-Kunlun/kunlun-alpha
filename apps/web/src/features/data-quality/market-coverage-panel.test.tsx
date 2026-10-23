import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketCoveragePanel } from "./market-coverage-panel";
import type { MarketCoverageResponse } from "@kunlun/shared-types";

const response: MarketCoverageResponse = {
  schemaVersion: "market-data-coverage-v1",
  scope: "DAILY_RAW_SUPPORTED_SOURCES",
  meaning: "OBSERVED_ONLY",
  window: {
    dateFrom: "2026-09-01",
    dateTo: "2026-09-04",
    asOf: "2026-09-05T02:00:00.000Z",
  },
  rows: [
    {
      unifiedCode: "600519.SH",
      source: "tushare-pro",
      observedBarDays: 2,
      firstDate: "2026-09-03",
      lastDate: "2026-09-04",
      latestEventTime: "2026-09-04T07:00:00.000Z",
      latestAvailableTime: "2026-09-04T07:01:00.000Z",
      latestProcessingTime: "2026-09-04T07:02:00.000Z",
    },
    {
      unifiedCode: "000001.SZ",
      source: "akshare-sina",
      observedBarDays: 1,
      firstDate: "2026-09-03",
      lastDate: "2026-09-03",
      latestEventTime: "2026-09-03T07:00:00.000Z",
      latestAvailableTime: "2026-09-03T07:01:00.000Z",
      latestProcessingTime: "2026-09-03T07:02:00.000Z",
    },
  ],
  truncated: true,
};

describe("MarketCoveragePanel", () => {
  it("labels observed-only scope and all three clock meanings", () => {
    const html = renderToStaticMarkup(<MarketCoveragePanel response={response} />);
    expect(html).toContain("仅表示已观测到的行情日");
    expect(html).toContain("可能来自不同记录");
    expect(html).toContain("观测日数");
    expect(html).toContain("event_time");
    expect(html).toContain("available_time");
    expect(html).toContain("processing_time");
    expect(html).toContain("结果超过 100 个证券/来源组，仅显示前 100 组");
    expect(html).toContain("本次返回最晚行情日：2026-09-04");
    expect(html).toContain("证券/来源组数：2");
    expect(html).toContain("缺口判断：未知（缺少应有交易日依据）");
    expect(html).toContain("早于前 100 组中的最晚日（仅作相对提示，不代表缺失）");
    expect(html).toContain("仅统计本次返回的前 100 组，最晚日与组数均为局部结果");
    expect(html).toContain("2026-09-04 15:00:00（上海）");
    expect(html).toContain("查看已入库日期");
    expect(html).toContain("查看已入库日期 600519.SH tushare-pro");
  });

  it("keeps rows horizontally accessible", () => {
    const html = renderToStaticMarkup(<MarketCoveragePanel response={response} />);
    expect(html).toContain("overflow-x-auto");
  });

  it("keeps the window metadata visible for an empty result", () => {
    const html = renderToStaticMarkup(
      <MarketCoveragePanel response={{ ...response, rows: [], truncated: false }} />,
    );
    expect(html).toContain("2026-09-01 至 2026-09-04");
    expect(html).toContain("当前条件下暂无已观测到的日线行情");
    expect(html).toContain("缺口判断：未知（缺少应有交易日依据）");
  });

  it("marks earlier returned groups without claiming missing dates", () => {
    const html = renderToStaticMarkup(
      <MarketCoveragePanel response={{ ...response, truncated: false }} />,
    );
    expect(html).toContain("早于本次返回最晚日");
    expect(html).toContain("不代表缺失");
    expect(html).not.toContain("仅统计本次返回的前 100 组");
  });
});
