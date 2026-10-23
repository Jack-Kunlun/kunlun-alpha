import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarketCoverageHistoryPanel } from "./market-coverage-history-panel";
import { useMarketCoverageDays } from "./use-market-coverage-days";

vi.mock("./use-market-coverage-days", () => ({ useMarketCoverageDays: vi.fn() }));

const selection = {
  dateFrom: "2026-07-26",
  dateTo: "2026-10-23",
  unifiedCode: "600519.SH",
  source: "akshare-tencent" as const,
  selectionKey: "2026-10-23T12:00:00.000Z",
};

describe("MarketCoverageHistoryPanel", () => {
  beforeEach(() => {
    vi.mocked(useMarketCoverageDays).mockReturnValue({
      status: "loading",
      data: null,
      error: null,
    });
  });

  it("opens a bounded date form for the selected security and source", () => {
    const html = renderToStaticMarkup(<MarketCoverageHistoryPanel selection={selection} />);
    expect(html).toContain("600519.SH");
    expect(html).toContain("akshare-tencent");
    expect(html).toContain('for="dq-history-date-from"');
    expect(html).toContain('for="dq-history-date-to"');
    expect(html).toContain('value="2026-07-26"');
    expect(html).toContain('value="2026-10-23"');
    expect(html).toContain("最多 366 个自然日");
    expect(html).toContain("恢复汇总窗口");
    expect(html).toContain("gap-2");
  });

  it("shows loading and native busy button semantics during a query", () => {
    const html = renderToStaticMarkup(<MarketCoverageHistoryPanel selection={selection} />);
    expect(html).toContain("已观测日期加载中");
    expect(html).toContain('aria-busy="true"');
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>/);
    expect(html).toContain("cursor-progress");
    expect(html).toContain("2026-07-26 至 2026-10-23");
  });
});
