import type { InstrumentIntelligenceDetail } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import {
  InstrumentDirectoryPage,
  InstrumentIntelligenceView,
} from "./instrument-intelligence-page";

const metadata = {
  status: "EMPTY",
  requestedAsOf: "2026-08-25T08:00:00.000Z",
  effectiveAsOf: "2026-08-25T08:00:00.000Z",
  dataCutoffTime: null,
  availableTime: null,
  processingTime: null,
  freshnessSeconds: null,
  unavailableReason: null,
  sourceVersions: [],
  evidenceIds: [],
} as const;

const detail = {
  schemaVersion: "instrument-intelligence-detail-v1",
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
  instrumentId: "600519.SH",
  mode: "HISTORICAL",
  requestedAsOf: "2026-08-25T08:00:00.000Z",
  effectiveAsOf: "2026-08-25T08:00:00.000Z",
  generatedAt: "2026-08-26T08:00:00.000Z",
  snapshotBoundary: {
    consistency: "BEST_EFFORT_CROSS_STORE",
    postgresIsolation: "REPEATABLE_READ",
    effectiveAsOf: "2026-08-25T08:00:00.000Z",
    stores: ["POSTGRESQL", "CLICKHOUSE"],
  },
  sections: {
    identity: { ...metadata, data: null },
    market: { ...metadata, data: null },
    emotion: { ...metadata, data: null },
    sector: { ...metadata, data: [] },
    events: { ...metadata, data: [] },
    seats: { ...metadata, data: [] },
    kolClaims: {
      ...metadata,
      status: "AVAILABLE",
      dataCutoffTime: "2026-08-25T07:00:00.000Z",
      availableTime: "2026-08-25T07:00:00.000Z",
      processingTime: "2026-08-25T06:59:00.000Z",
      freshnessSeconds: 3600,
      evidenceIds: ["evidence-1"],
      data: [
        {
          claimId: "claim-1",
          revisionId: "claim-r1",
          kolId: "kol-1",
          statement: "公开表述样例",
          direction: "BULLISH",
          reviewStatus: "APPROVED",
          confidenceBps: 8000,
          publishTime: "2026-08-25T06:50:00.000Z",
          availableTime: "2026-08-25T07:00:00.000Z",
          evidenceIds: ["evidence-1"],
          claimMeaning: "PUBLIC_WORDING_CLAIM_NOT_BROKER_TRADE",
        },
      ],
    },
    features: {
      ...metadata,
      status: "UNAVAILABLE",
      unavailableReason: "CLICKHOUSE_FEATURE_QUERY_FAILED",
      data: [],
    },
  },
  evidence: [
    {
      evidenceId: "evidence-1",
      source: "public-source",
      sourceVersion: "v1",
      availableTime: "2026-08-25T07:00:00.000Z",
      excerpt: "公开证据节选",
      locator: "https://example.test/evidence/1",
      access: "DIRECT_URL",
    },
  ],
} as unknown as InstrumentIntelligenceDetail;

describe("InstrumentIntelligenceView", () => {
  it("renders point-in-time semantics, section failures and Claim warnings", () => {
    const html = renderToStaticMarkup(
      <InstrumentIntelligenceView
        instrumentId="600519.SH"
        result={{ status: "success", data: detail, error: null }}
      />,
    );
    expect(html).toContain("BEST_EFFORT_CROSS_STORE");
    expect(html).toContain("公开表述 Claim");
    expect(html).toContain("CLICKHOUSE_FEATURE_QUERY_FAILED");
    expect(html).toContain("不代表真实成交");
    expect(html).toContain("https://example.test/evidence/1");
  });

  it.each([
    ["loading", "正在装配个股 Intelligence"],
    ["forbidden", "无权访问个股 Intelligence"],
    ["error", "个股 Intelligence 加载失败"],
  ] as const)("renders the %s state", (status, expected) => {
    const result =
      status === "loading"
        ? ({ status, data: null, error: null } as const)
        : ({
            status,
            data: null,
            error: new Error("state-message"),
          } as const);
    const html = renderToStaticMarkup(
      <InstrumentIntelligenceView instrumentId="600519.SH" result={result} />,
    );
    expect(html).toContain(expected);
  });

  it("rejects vendor or malformed symbols before issuing a useful view", () => {
    const html = renderToStaticMarkup(
      <InstrumentIntelligenceView
        instrumentId="SH600519"
        result={{ status: "empty", data: null, error: null }}
      />,
    );
    expect(html).toContain("600519.SH");
  });

  it("lists the curated local stocks with canonical identifiers", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <InstrumentDirectoryPage />
      </MemoryRouter>,
    );
    expect(html).toContain("本地已载入股票");
    for (const marker of [
      "平安银行",
      "比亚迪",
      "宁德时代",
      "软通动力",
      "浦发银行",
      "贵州茅台",
      "中国平安",
      "中芯国际",
      "艾融软件",
    ]) {
      expect(html).toContain(marker);
    }
    for (const marker of [
      "000001.SZ",
      "002594.SZ",
      "300750.SZ",
      "301236.SZ",
      "600000.SH",
      "600519.SH",
      "601318.SH",
      "688981.SH",
      "920799.BJ",
    ]) {
      expect(html).toContain(marker);
    }
  });
});
