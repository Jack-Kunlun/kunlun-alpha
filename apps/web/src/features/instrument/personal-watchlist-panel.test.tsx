import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalWatchlist } from "./personal-watchlist-panel";
import { usePersonalWatchlist } from "./use-personal-watchlist";

vi.mock("./use-personal-watchlist", () => ({
  usePersonalWatchlist: vi.fn(),
  usePersonalWatchlistQuote: vi.fn(() => ({ status: "empty", data: null, error: null })),
}));
vi.mock("@/app/filter-context", () => ({
  useTerminalFilters: () => ({
    hrefForRoute: (path: string) => path,
    value: { version: "v1", asOf: null, instrumentIds: [] },
  }),
}));

function render() {
  return renderToStaticMarkup(
    <MemoryRouter>
      <PersonalWatchlist ownerId="isolated-test-owner" />
    </MemoryRouter>,
  );
}

describe("PersonalWatchlist filters", () => {
  beforeEach(() => {
    vi.mocked(usePersonalWatchlist).mockReturnValue({
      ownerId: "isolated-test-owner",
      status: "success",
      data: { schemaVersion: "personal-watchlist-response-v1", items: [] },
      error: null,
      refreshing: false,
      isImporting: false,
      migrationStatus: "idle",
      migrationError: null,
      migrationNameConflicts: [],
      refresh: vi.fn(),
      retryMigration: vi.fn(),
      importItems: vi.fn(),
    });
  });

  it("provides labelled market/search controls, a reset button and support semantics", () => {
    const html = render();
    expect(html).toContain('for="personal-watchlist-market"');
    expect(html).toContain('for="personal-watchlist-search"');
    expect(html).toContain('for="personal-watchlist-task-status"');
    for (const label of [
      "全部市场",
      "上海（.SH）",
      "深圳（.SZ）",
      "北京（.BJ）",
      "未接入观察项",
      "重置筛选",
    ])
      expect(html).toContain(label);
    expect(html).toContain("未接入观察项按代码分类，不等同于采集失败或行情缺失");
    expect(html).toContain("显示 0 / 0 项自选");
    expect(html).toContain("对比本页日线");
    expect(html).toContain("采集完成不代表行情最新");
    expect(html).toContain("全部任务（0）");
    expect(html).toContain("服务端尚未保存自选");
    expect(html).not.toContain("没有匹配的自选");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>重置筛选<\/button>/);
  });

  it("keeps filters absent when the server list cannot be read", () => {
    const previous = vi.mocked(usePersonalWatchlist).getMockImplementation()!(
      "isolated-test-owner",
    );
    vi.mocked(usePersonalWatchlist).mockReturnValue({
      ...previous,
      status: "forbidden",
      data: null,
    });
    const html = render();
    expect(html).toContain("当前账号无权读取服务端自选");
    expect(html).not.toContain('id="personal-watchlist-market"');
    expect(html).not.toContain('id="personal-watchlist-task-status"');
  });

  it("labels counts as task states across the whole list, without claiming full or fresh market coverage", () => {
    const previous = vi.mocked(usePersonalWatchlist).getMockImplementation()!(
      "isolated-test-owner",
    );
    const items = [
      { code: "600519.SH", name: "样例沪股", status: "SUCCEEDED" },
      { code: "000001.SZ", name: "样例深股", status: "FAILED" },
      { code: "HK:00700", name: "观察项", status: "UNSUPPORTED" },
    ] as const;
    vi.mocked(usePersonalWatchlist).mockReturnValue({
      ...previous,
      data: {
        schemaVersion: "personal-watchlist-response-v1",
        items: items.map((x) => ({
          code: x.code,
          name: x.name,
          addedAt: "2026-10-26T00:00:00Z",
          market: { status: x.status, lastAttemptAt: null, lastSuccessAt: null, errorCode: null },
        })),
      },
    });
    const html = render();
    for (const label of [
      "全部任务（3）",
      "采集完成（1）",
      "采集失败（1）",
      "未接入（1）",
      "等待采集（0）",
      "采集中（0）",
      "行情源暂无日线（0）",
    ])
      expect(html).toContain(label);
    expect(html).toContain("完整清单，不随筛选变化");
    expect(html).toContain("日期和来源为准");
    expect(html).not.toContain("全市场覆盖");
  });
});
