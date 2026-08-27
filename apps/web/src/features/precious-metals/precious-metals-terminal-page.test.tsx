import type { PreciousMetalsTerminalSnapshot } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { PreciousMetalsTerminalView } from "./precious-metals-terminal-page";

describe("PreciousMetalsTerminalView", () => {
  it.each([
    ["loading", "正在加载贵金属基金终端"],
    ["empty", "该点时没有可见的场内贵金属基金"],
    ["error", "贵金属基金数据加载失败"],
    ["forbidden", "无权访问贵金属基金终端"],
  ] as const)("renders the %s state", (status, marker) => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreciousMetalsTerminalView
          result={{
            status,
            data: null,
            error: status === "error" || status === "forbidden" ? new Error("x") : null,
          }}
        />
      </MemoryRouter>,
    );
    expect(html).toContain(marker);
  });

  it("renders currencies, freshness, ranking, gaps, events and the non-executable notice", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreciousMetalsTerminalView result={{ status: "success", data: snapshot(), error: null }} />
      </MemoryRouter>,
    );

    expect(html).toContain("贵金属基金观察台");
    expect(html).toContain("518880.SH");
    expect(html).toContain("交易 CNY");
    expect(html).toContain("净值 CNY");
    expect(html).toContain("+200.00 bp");
    expect(html).toContain("数据断点已显式保留");
    expect(html).toContain("贵金属避险需求升温");
    expect(html).toContain("NAV 与 iNAV 只用于研究参考");
    expect(html).toContain("溢折价预警");
    expect(html).not.toMatch(/P6-N|Phase 6/);
  });

  it("renders the fail-closed source state", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PreciousMetalsTerminalView
          result={{
            status: "success",
            data: { ...snapshot(), status: "UNAVAILABLE", funds: [], events: [] },
            error: null,
          }}
        />
      </MemoryRouter>,
    );
    expect(html).toContain("身份数据源不可用");
  });
});

function snapshot(): PreciousMetalsTerminalSnapshot {
  return {
    schemaVersion: "precious-metals-terminal-v1",
    mode: "CURRENT",
    requestedAsOf: "2026-08-27T07:00:00.000Z",
    effectiveAsOf: "2026-08-27T07:00:00.000Z",
    generatedAt: "2026-08-27T07:00:01.000Z",
    status: "PARTIAL",
    executionCapability: "REFERENCE_ONLY",
    valuationPolicy: "NAV_INAV_NON_EXECUTABLE",
    rankingAlgorithmVersion: "precious-metals-turnover-ranking-v1",
    rankingMetric: "LATEST_EXCHANGE_TURNOVER_CNY",
    sampleSize: 1,
    gaps: [
      {
        scope: "INAV",
        severity: "INFO",
        code: "NO_VISIBLE_DATA",
        instrumentId: "518880.SH",
        message: "未提供可见 iNAV",
      },
    ],
    sourceVersions: ["provider@v1"],
    evidenceIds: ["evidence-1"],
    funds: [
      {
        unifiedCode: "518880.SH",
        displayName: "黄金 ETF",
        exchange: "SH",
        assetType: "ETF",
        underlyingCommodity: "GOLD",
        tradingCurrency: "CNY",
        navCurrency: "CNY",
        benchmarkOrTrackingIndex: "Au99.99",
        managementFeeRateBps: 50,
        metadataConfidenceBps: 9500,
        reviewStatus: "REVIEWED",
        metadataSource: "provider",
        metadataSourceVersion: "v1",
        metadataAvailableTime: "2026-08-27T06:00:00.000Z",
        metadataProcessingTime: "2026-08-27T06:01:00.000Z",
        market: {
          date: "2026-08-27",
          eventTime: "2026-08-27T06:57:00.000Z",
          close: "1.020000",
          volume: "1000000",
          turnoverCny: "900000000.00",
          suspended: false,
          freshness: "FRESH",
          source: "market-provider",
          sourceVersion: "v1",
          dataVersion: "bars-v2",
          availableTime: "2026-08-27T06:58:00.000Z",
          processingTime: "2026-08-27T06:59:00.000Z",
          evidenceId: "market-evidence",
        },
        valuation: {
          navValue: "1.000000",
          inavValue: "1.000000",
          referenceKind: "INAV",
          referenceValue: "1.000000",
          referenceDate: "2026-08-27",
          premiumDiscountBps: "200.00",
          freshness: "FRESH",
          staleAfterSeconds: 300,
          source: "nav-provider",
          sourceVersion: "v1",
          availableTime: "2026-08-27T06:58:00.000Z",
          processingTime: "2026-08-27T06:59:00.000Z",
          evidenceIds: ["nav-evidence"],
          referenceOnly: true,
        },
        features: [],
        ranking: {
          rank: 1,
          metric: "LATEST_EXCHANGE_TURNOVER_CNY",
          metricValue: "900000000.00",
          algorithmVersion: "precious-metals-turnover-ranking-v1",
          sampleSize: 1,
          confidenceBps: 9500,
        },
        alertContext: {
          instrumentId: "518880.SH",
          supportedFields: ["LAST_PRICE", "FEATURE_VALUE"],
          premiumFeatureName: "precious_metals_fund.premium_discount_bps",
        },
      },
    ],
    events: [
      {
        eventId: "event-1",
        instrumentIds: ["518880.SH"],
        eventType: "MACRO_POLICY",
        headline: "贵金属避险需求升温",
        summary: "公开信息显示避险主题热度上升。",
        publishTime: "2026-08-27T06:00:00.000Z",
        availableTime: "2026-08-27T06:01:00.000Z",
        confidenceBps: 8200,
        modelVersion: "event-model-v1",
        evidenceIds: ["event-evidence"],
      },
    ],
  };
}
