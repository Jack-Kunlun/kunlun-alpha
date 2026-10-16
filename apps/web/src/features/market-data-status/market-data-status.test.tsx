import type { MarketDataSyncStatus } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketDataStatusView } from "./market-data-status";

const succeeded: MarketDataSyncStatus = {
  schemaVersion: "market-data-sync-status-v1",
  status: "SUCCEEDED",
  provider: "akshare",
  symbols: ["600519.SH"],
  lastAttemptAt: "2026-10-16T10:20:00Z",
  lastFinishedAt: "2026-10-16T10:20:05Z",
  lastSuccessAt: "2026-10-16T10:20:05Z",
  lastSuccessResult: { requests: 1, receivedBars: 100, writtenBars: 100, dailyRefreshed: true },
  errorCode: null,
};

function render(data: MarketDataSyncStatus, historical = false, instrumentId?: string) {
  return renderToStaticMarkup(
    <MarketDataStatusView
      result={{ status: "success", data, error: null }}
      historical={historical}
      instrumentId={instrumentId}
    />,
  );
}

describe("MarketDataStatusView", () => {
  it.each([
    ["loading", "正在查询采集状态"],
    ["empty", "暂无采集任务记录"],
    ["error", "采集状态暂时不可用"],
    ["forbidden", "无权查看采集状态"],
  ] as const)("renders %s safely", (status, marker) => {
    const html = renderToStaticMarkup(
      <MarketDataStatusView result={{ status, data: null, error: new Error("private-marker") }} />,
    );
    expect(html).toContain(marker);
    expect(html).not.toContain("private-marker");
  });

  it("separates task timestamps from the market data date", () => {
    const html = render(succeeded);
    expect(html).toContain("任务成功");
    expect(html).toContain("最近尝试");
    expect(html).toContain("最近任务成功");
    expect(html).toContain('dateTime="2026-10-16T10:20:05Z"');
    expect(html).toContain("18:20:05");
    expect(html).toContain("行情日期以数据区域的“数据截止”为准");
    expect(html).not.toContain("实时行情");
  });

  it("keeps the preceding success visible after a failed attempt", () => {
    const html = render({
      ...succeeded,
      status: "FAILED",
      lastAttemptAt: "2026-10-16T10:25:00Z",
      lastFinishedAt: "2026-10-16T10:25:02Z",
      errorCode: "SOURCE_ERROR",
    });
    expect(html).toContain("本次失败");
    expect(html).toContain("数据源请求失败");
    expect(html).toContain("已入库行情保留");
    expect(html).toContain('dateTime="2026-10-16T10:20:05Z"');
  });

  it("does not claim new market data after a successful no-op", () => {
    const html = render({
      ...succeeded,
      lastSuccessResult: { requests: 0, receivedBars: 0, writtenBars: 0, dailyRefreshed: false },
    });
    expect(html).toContain("本次检查没有新增写入");
    expect(html).toContain("请求 0 · 接收 0 · 写入 0");
  });

  it("reports unknown when no attempt exists", () => {
    const html = render({
      ...succeeded,
      status: "UNKNOWN",
      lastAttemptAt: null,
      lastFinishedAt: null,
      lastSuccessAt: null,
      lastSuccessResult: null,
      errorCode: "NO_RUN",
    });
    expect(html).toContain("状态未知");
    expect(html).toContain("暂无采集任务记录");
    expect(html).not.toContain("<time");
  });

  it("labels unconfirmed running records without treating them as a confirmed failure", () => {
    const html = render({ ...succeeded, status: "UNKNOWN", errorCode: "RUN_STATUS_EXPIRED" });
    expect(html).toContain("上次任务未结束，当前状态待确认");
    expect(html).not.toContain("本次失败");
  });

  it("keeps current task metadata explicit in historical views", () => {
    expect(render(succeeded, true)).toContain("当前采集状态，不随历史点时变化");
  });

  it("does not attribute a global task result to an instrument outside its scope", () => {
    const html = render(succeeded, false, "000001.SZ");
    expect(html).toContain("此标的不在当前采集清单");
    expect(html).not.toContain('dateTime="2026-10-16T10:20:05Z"');
  });
});
