import { MemoryRouter } from "react-router";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TerminalFilterProvider } from "@/app/filter-context";
import { LOCAL_TERMINAL_STOCKS } from "../instrument/local-terminal-stock-samples";
import { buildDailyComparison, type DailyComparisonOutcome } from "./daily-comparison";
import { DailyComparisonTable } from "./daily-comparison-table";

const AS_OF = "2026-10-16T16:00:00.000Z";

function emptyOutcomes(): DailyComparisonOutcome[] {
  return LOCAL_TERMINAL_STOCKS.map((stock) => ({
    stock,
    kind: "response",
    value: {
      schemaVersion: "instrument-bars-v1",
      dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
      instrumentId: stock.instrumentId,
      mode: "HISTORICAL",
      requestedAsOf: AS_OF,
      effectiveAsOf: AS_OF,
      interval: "DAILY",
      priceType: "RAW",
      status: "EMPTY",
      barCount: 0,
      dataCutoffTime: null,
      freshnessSeconds: null,
      bars: [],
      sourceVersions: [],
      evidenceIds: [],
    },
  }));
}

describe("DailyComparisonTable", () => {
  it("labels a watchlist-page scope and pins links to its captured cutoff", () => {
    const data = buildDailyComparison(AS_OF, emptyOutcomes());
    const html = renderToStaticMarkup(
      <MemoryRouter
        initialEntries={["/instruments?asOf=2026-08-01T08%3A00%3A00Z&instrument=600519.SH"]}
      >
        <TerminalFilterProvider>
          <DailyComparisonTable
            result={{ status: "success", data, error: null }}
            referenceStatus="success"
            scope="watchlist-page"
            detailAsOf={AS_OF}
          />
        </TerminalFilterProvider>
      </MemoryRouter>,
    );
    expect(html).toContain("本页自选日线对比");
    expect(html).toContain("下载本次对比 JSON");
    expect(html).toContain("排序仅针对本次样本");
    expect(html).not.toContain("仅含配置的八个");
    expect(html).toContain(`/instruments/000001.SZ?asOf=${encodeURIComponent(AS_OF)}`);
    expect(html).not.toContain("instrument=600519.SH");
    expect(html).toContain("本次本页自选在该点时均暂无日线数据");
  });
  it("renders empty rows, accessible sorting controls, and historical detail links", () => {
    const data = buildDailyComparison(AS_OF, emptyOutcomes());
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={[`/market-overview?asOf=${encodeURIComponent(AS_OF)}`]}>
        <TerminalFilterProvider>
          <DailyComparisonTable
            result={{ status: "success", data, error: null }}
            referenceStatus="success"
          />
        </TerminalFilterProvider>
      </MemoryRouter>,
    );

    expect(html).toContain("日线对比");
    expect(html).not.toContain("下载本次对比 JSON");
    expect(html).toContain("未复权");
    expect(html).toContain("暂无日线");
    expect(html).toContain("固定点时 2026-10-17 00:00:00 北京时间");
    expect(html).toContain('aria-sort="descending"');
    expect(html).toContain('aria-label="按收盘价升序排序"');
    expect(html).toContain(`/instruments/000001.SZ?asOf=${encodeURIComponent(AS_OF)}`);
    expect(html).toContain('class="relative w-full overflow-x-auto"');
  });

  it.each(["loading", "error", "forbidden", "empty"] as const)(
    "blocks snapshot downloads for a %s query even if stale data is supplied",
    (status) => {
      const data = buildDailyComparison(AS_OF, emptyOutcomes());
      const html = renderToStaticMarkup(
        <MemoryRouter>
          <DailyComparisonTable
            result={{ status, data, error: null }}
            referenceStatus="success"
            scope="watchlist-page"
            detailAsOf={AS_OF}
          />
        </MemoryRouter>,
      );
      expect(html).toMatch(
        /<button(?=[^>]*aria-label="下载本次对比 JSON")(?=[^>]*disabled="")[^>]*>/,
      );
      expect(html).not.toContain("已生成对比快照");
    },
  );

  it("shows the baseline data version when it differs from the latest bar", () => {
    const outcomes = emptyOutcomes();
    const stock = LOCAL_TERMINAL_STOCKS[0];
    if (stock === undefined) throw new Error("missing test sample");
    outcomes[0] = {
      stock,
      kind: "response",
      value: {
        schemaVersion: "instrument-bars-v1",
        dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
        instrumentId: stock.instrumentId,
        mode: "HISTORICAL",
        requestedAsOf: AS_OF,
        effectiveAsOf: AS_OF,
        interval: "DAILY",
        priceType: "RAW",
        status: "AVAILABLE",
        barCount: 2,
        dataCutoffTime: null,
        freshnessSeconds: null,
        bars: [
          {
            date: "2026-10-15",
            eventTime: "2026-10-15T07:00:00.000Z",
            close: "10.00",
            amount: "100",
            suspended: false,
            availableTime: "2026-10-15T08:00:00.000Z",
            processingTime: "2026-10-15T08:01:00.000Z",
            source: "akshare-eastmoney",
            sourceVersion: "2026.08.29",
            dataVersion: "daily-bars-v2",
          },
          {
            date: "2026-10-16",
            eventTime: "2026-10-16T07:00:00.000Z",
            close: "11.00",
            amount: "200",
            suspended: false,
            availableTime: "2026-10-16T08:00:00.000Z",
            processingTime: "2026-10-16T08:01:00.000Z",
            source: "akshare-eastmoney",
            sourceVersion: "2026.08.29",
            dataVersion: "daily-bars-v3",
          },
        ],
        sourceVersions: [],
        evidenceIds: [],
      },
    };
    const data = buildDailyComparison(AS_OF, outcomes);
    const html = renderToStaticMarkup(
      <MemoryRouter initialEntries={[`/market-overview?asOf=${encodeURIComponent(AS_OF)}`]}>
        <TerminalFilterProvider>
          <DailyComparisonTable
            result={{ status: "success", data, error: null }}
            referenceStatus="success"
          />
        </TerminalFilterProvider>
      </MemoryRouter>,
    );

    expect(html).toContain("数据版本 daily-bars-v3");
    expect(html).toContain("基准数据版本 daily-bars-v2");
    expect(html).toContain("数据版本不一致");
  });

  it.each([
    ["loading", "正在加载日线对比"],
    ["empty", "该点时暂无日线对比数据"],
    ["error", "日线对比加载失败"],
    ["forbidden", "无权访问日线对比"],
  ] as const)("shows the %s state", (status, marker) => {
    const html = renderToStaticMarkup(
      <DailyComparisonTable
        result={{
          status,
          data: null,
          error: status === "error" || status === "forbidden" ? new Error("x") : null,
        }}
        referenceStatus="success"
      />,
    );
    expect(html).toContain(marker);
  });
});
