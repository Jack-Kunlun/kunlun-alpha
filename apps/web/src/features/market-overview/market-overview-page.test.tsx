import type { MarketOverviewSnapshot } from "@kunlun/shared-types";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MarketOverviewView } from "./market-overview-page";

const snapshot: MarketOverviewSnapshot = {
  schemaVersion: "market-overview-v1",
  mode: "HISTORICAL",
  requestedAsOf: "2026-08-25T07:00:00.000Z",
  dataCutoffTime: "2026-08-25T06:59:30.000Z",
  completeness: "COMPLETE",
  freshness: {
    status: "HISTORICAL",
    ageSeconds: 30,
    delayedAfterSeconds: 90,
    staleAfterSeconds: 300,
  },
  indices: [
    {
      instrumentId: "000001.SH",
      name: "上证指数",
      dataTime: "2026-08-25T06:59:30.000Z",
      value: "3100.0000",
      previousClose: "3090.0000",
      changeBps: 32,
      sourceVersion: "bars-v2",
      evidenceId: "index-evidence",
    },
  ],
  breadth: {
    dataTime: "2026-08-25T06:59:30.000Z",
    advancingCount: 3000,
    decliningCount: 1500,
    unchangedCount: 100,
    suspendedCount: 20,
    sampleSize: 4620,
    advancingRatioBps: 6522,
    universeVersion: "ashare-code-pattern-v1",
    sourceVersions: ["bars-v2"],
    evidenceIds: ["breadth-evidence"],
  },
  turnover: {
    dataTime: "2026-08-25T06:59:30.000Z",
    amountCny: "9007199254740993.25",
    sampleSize: 4620,
    sourceVersions: ["bars-v2"],
    evidenceIds: ["turnover-evidence"],
  },
  emotion: {
    dataTime: "2026-08-25T06:59:30.000Z",
    scoreBps: 6800,
    confidenceBps: 8200,
    sampleSize: 200,
    algorithmVersion: "emotion-score-v1",
    sourceVersions: ["emotion-v1"],
    evidenceIds: ["emotion-evidence"],
  },
  risk: {
    state: "CALM",
    basisVersion: "market-risk-temperature-v1",
    explanation: "研究参考",
    dataMeaning: "RESEARCH_CONTEXT_NOT_ORDER_RISK",
  },
  sourceVersions: ["bars-v2", "emotion-v1"],
  evidenceIds: ["breadth-evidence", "emotion-evidence", "index-evidence"],
  dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
};

describe("MarketOverviewView", () => {
  it.each([
    ["loading", "正在加载"],
    ["empty", "暂无市场总览数据"],
    ["error", "数据流中断"],
    ["forbidden", "无权访问"],
  ] as const)("renders %s", (status, marker) => {
    const html = renderToStaticMarkup(
      <MarketOverviewView
        result={{
          status,
          data: null,
          error: status === "error" || status === "forbidden" ? new Error("x") : null,
        }}
      />,
    );
    expect(html).toContain(marker);
  });

  it("renders historical provenance and exact decimal turnover", () => {
    const html = renderToStaticMarkup(
      <MarketOverviewView result={{ status: "success", data: snapshot, error: null }} />,
    );
    expect(html).toContain("历史点时");
    expect(html).toContain("9,007,199,254,740,993.25");
    expect(html).toContain("上证指数");
    expect(html).toContain("Phase 0–6 无真实账户或真实下单路径");
  });

  it("renders missing regions explicitly instead of displaying zero", () => {
    const html = renderToStaticMarkup(
      <MarketOverviewView
        result={{
          status: "success",
          data: { ...snapshot, breadth: null, turnover: null, emotion: null },
          error: null,
        }}
      />,
    );
    expect(html.match(/不以零值代替/g)).toHaveLength(3);
  });
});
