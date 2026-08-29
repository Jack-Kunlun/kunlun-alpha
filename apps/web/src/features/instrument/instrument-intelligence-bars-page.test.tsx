import type { InstrumentBarsResponse, InstrumentIntelligenceDetail } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { InstrumentIntelligenceView } from "./instrument-intelligence-page";

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
    kolClaims: { ...metadata, data: [] },
    features: { ...metadata, data: [] },
  },
  evidence: [],
} as unknown as InstrumentIntelligenceDetail;

const bars: InstrumentBarsResponse = {
  schemaVersion: "instrument-bars-v1",
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
  instrumentId: "600519.SH",
  mode: "HISTORICAL",
  requestedAsOf: "2026-08-25T08:00:00.000Z",
  effectiveAsOf: "2026-08-25T08:00:00.000Z",
  interval: "DAILY",
  priceType: "RAW",
  status: "AVAILABLE",
  barCount: 1,
  dataCutoffTime: "2026-08-25T07:00:00.000Z",
  freshnessSeconds: 3600,
  bars: [
    {
      date: "2026-08-25",
      eventTime: "2026-08-25T07:00:00.000Z",
      open: "10.0000",
      high: "11.0000",
      low: "9.0000",
      close: "10.5000",
      volume: "100",
      amount: "1000.00",
      suspended: false,
      dataVersion: "bars-v2",
      source: "tushare-pro",
      sourceVersion: "tushare-v1",
      evidenceId: "evidence-1",
      availableTime: "2026-08-25T07:01:00.000Z",
      processingTime: "2026-08-25T07:02:00.000Z",
    },
  ],
  sourceVersions: ["tushare-pro@tushare-v1"],
  evidenceIds: ["evidence-1"],
};

describe("InstrumentIntelligenceView daily bars region", () => {
  it("renders the chart metadata and research-only warning", () => {
    const html = renderToStaticMarkup(
      <InstrumentIntelligenceView
        instrumentId="600519.SH"
        result={{ status: "success", data: detail, error: null }}
        barsResult={{ status: "success", data: bars, error: null }}
      />,
    );
    expect(html).toContain("历史日 K 线");
    expect(html).toContain("tushare-pro@tushare-v1");
    expect(html).toContain("1 根");
    expect(html).toContain("不是实时或可成交价格");
  });

  it.each([
    ["loading", "正在加载日 K 线"],
    ["empty", "该点时没有可见的日 K 线"],
    ["error", "日 K 线加载失败"],
    ["forbidden", "无权访问日 K 线"],
  ] as const)("renders bars %s state", (status, marker) => {
    const html = renderToStaticMarkup(
      <InstrumentIntelligenceView
        instrumentId="600519.SH"
        result={{ status: "success", data: detail, error: null }}
        barsResult={{
          status,
          data: null,
          error: status === "error" || status === "forbidden" ? new Error("x") : null,
        }}
      />,
    );
    expect(html).toContain(marker);
  });
});
