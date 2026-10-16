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
    expect(html).toContain("当前系统没有真实账户或真实下单路径");
    expect(html).toContain("仅代表当前入库样本，不代表全市场");
    expect(html).not.toContain("完整度 COMPLETE");
    expect(html).not.toContain("市场情绪");
    expect(html).not.toContain("研究型风险温度");
  });

  it("labels current daily data by its historical date instead of minute freshness thresholds", () => {
    const daily = {
      ...snapshot,
      mode: "CURRENT" as const,
      freshness: {
        status: "STALE" as const,
        ageSeconds: 86_400,
        delayedAfterSeconds: 90,
        staleAfterSeconds: 300,
      },
    };
    const html = renderToStaticMarkup(
      <MarketOverviewView result={{ status: "success", data: daily, error: null }} />,
    );

    expect(html).toContain("历史日线");
    expect(html).toContain("数据截止");
    expect(html).toContain("bars-v2");
    expect(html).toContain("可比较样本 4620");
    expect(html).not.toContain("数据过期");
    expect(html).not.toContain("完整度 COMPLETE");
  });

  it("labels a missing daily sample without turning it into a freshness error", () => {
    const empty = {
      ...snapshot,
      mode: "CURRENT" as const,
      dataCutoffTime: null,
      freshness: {
        status: "NO_DATA" as const,
        ageSeconds: null,
        delayedAfterSeconds: 90,
        staleAfterSeconds: 300,
      },
      indices: [],
      breadth: null,
      turnover: null,
      emotion: null,
      sourceVersions: [],
      evidenceIds: [],
    };
    const html = renderToStaticMarkup(
      <MarketOverviewView result={{ status: "success", data: empty, error: null }} />,
    );

    expect(html).toContain("无数据");
    expect(html).toContain("当前点时无可用数据");
    expect(html).not.toContain("数据过期");
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
    expect(html.match(/不以零值代替/g)).toHaveLength(2);
  });
});
