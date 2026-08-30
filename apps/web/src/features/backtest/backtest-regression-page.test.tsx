import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RegressionArtifact, RegressionComparison, RegressionRunSummary } from "./types";
import { BacktestRegressionPage } from "./backtest-regression-page";
import {
  useBacktestRegression,
  useBacktestRegressionComparison,
  useBacktestRegressionRuns,
} from "./use-backtest-regressions";

vi.mock("./use-backtest-regressions", () => ({
  useBacktestRegression: vi.fn(),
  useBacktestRegressionComparison: vi.fn(),
  useBacktestRegressionRuns: vi.fn(),
}));

const mockedRuns = vi.mocked(useBacktestRegressionRuns);
const mockedArtifact = vi.mocked(useBacktestRegression);
const mockedComparison = vi.mocked(useBacktestRegressionComparison);

const digest = "a".repeat(64);

const summary: RegressionRunSummary = {
  schemaVersion: "backtest-regression-summary-v1",
  suiteId: "p5-core-chain",
  runId: "local-preview-run",
  fixtureId: "local-preview-fixture",
  status: "MATCHED",
  candidateSha256: digest,
  baselineSha256: digest,
  dataStart: "2026-05-29T01:00:00.000000Z",
  dataEnd: "2026-06-03T01:00:00.000000Z",
  availability: "LOCAL_PREVIEW",
  evidenceIntegrityConfidence: "HIGH",
  preview: true,
};

const observation = {
  observationTime: "2026-05-29T01:00:00.000000Z",
  nav: "100000",
  provenanceDigest: digest,
};

const riskFreeObservation = {
  observationTime: "2026-05-29T01:00:00.000000Z",
  rate: "0.01",
  provenanceDigest: digest,
};

const artifact: RegressionArtifact = {
  schemaVersion: "backtest-regression-run-v1",
  canonicalizationVersion: "backtest-regression-c14n-v1",
  suiteId: "p5-core-chain",
  runId: "local-preview-run",
  fixtureId: "local-preview-fixture",
  trust: {
    mode: "FIXTURE_SELF_CONTAINED",
    evidenceIntegrityConfidence: "HIGH",
    evidenceRefs: [],
  },
  manifest: { json: {}, sha256: digest },
  inputs: {
    fixtureSha256: digest,
    executionInputDigests: [digest],
    portfolioHistoryRef: { tapeId: "tape", eventTapeDigest: digest, eventCount: 0 },
    valuationLineage: {
      valuationPolicyId: "policy",
      valuationPolicyVersion: "1",
      valuationPolicyDigest: digest,
      valuations: [],
    },
    navObservations: [observation, observation, observation, observation],
    riskFreeObservations: [
      riskFreeObservation,
      riskFreeObservation,
      riskFreeObservation,
      riskFreeObservation,
    ],
    tPlusOne: {
      buyOrderId: "buy",
      sellOrderId: "sell",
      buyExecutionInputDigest: digest,
      sameDaySellExecutionInputDigest: digest,
      nextDaySellExecutionInputDigest: digest,
      sameDaySellabilityDigest: digest,
      nextDaySellabilityDigest: digest,
      sameDayBatchDigest: digest,
      nextDayBatchDigest: digest,
    },
  },
  provenance: {
    code: { allowlist: [], treeSha256: digest },
    config: [],
    dependencies: [],
    toolchain: {
      python: "3.12.13",
      uv: "0.12.3",
      evidenceSha256: digest,
      hatchling: "1.27.0",
      rootPyprojectSha256: digest,
      servicePyprojectSha256: digest,
      uvLockSha256: digest,
    },
  },
  results: {
    counts: {
      events: 2,
      intents: 2,
      orders: 2,
      fills: 2,
      navObservations: 4,
      tPlusOneRejected: 1,
      nextDaySellFills: 1,
    },
    pnl: { realized: "600", unrealized: "0", total: "600", fees: "0" },
    finalNav: "100600",
    finalValuation: {
      cutoffTime: "2026-06-03T01:00:00.000000Z",
      nav: "100600",
      totalPnl: "600",
      stateDigest: digest,
      inputDigest: digest,
      sampleCount: 4,
    },
    metrics: {
      cumulativeChainedReturn: { status: "AVAILABLE", value: "0.006" },
      annualizedReturn: { status: "AVAILABLE", value: "0.006" },
      annualizedVolatility: { status: "AVAILABLE", value: "0.001" },
      maximumDrawdown: { status: "AVAILABLE", value: "0" },
      sharpe: { status: "AVAILABLE", value: "1" },
      sortino: { status: "AVAILABLE", value: "1" },
      calmar: { status: "AVAILABLE", value: "1" },
    },
    observations: [observation, observation, observation, observation],
    tPlusOne: {
      sameDay: {
        orderId: "sell",
        status: "REJECTED",
        rejectReason: "T_PLUS_ONE_NOT_SELLABLE",
        fillCount: 0,
        batchDigest: digest,
        resultDigest: digest,
        tradingDate: "2026-05-29",
        sellabilityDigest: digest,
      },
      nextDay: {
        orderId: "sell",
        status: "FILLED",
        rejectReason: null,
        fillCount: 1,
        batchDigest: digest,
        resultDigest: digest,
        tradingDate: "2026-06-01",
        sellabilityDigest: digest,
      },
    },
  },
  versions: {
    engine: "1.0.0",
    manifest: "1.0.0",
    eventOrder: "1.0.0",
    execution: "1.0.0",
    matching: "1.0.0",
    portfolio: "1.0.0",
    valuation: "1.0.0",
    metrics: "1.0.0",
    strategy: "1.0.0",
    policy: "1.0.0",
    fixture: "1.0.0",
  },
  artifactSha256: digest,
};

const matched: RegressionComparison = {
  baselineSha256: digest,
  candidateSha256: digest,
  status: "MATCHED",
  categoryCounts: {
    SCHEMA: 0,
    MANIFEST_INPUT: 0,
    ALGORITHM_CONFIG: 0,
    DEPENDENCY_TOOLCHAIN: 0,
    RESULT: 0,
  },
  diffs: [],
  diffLines: [],
};

const drifted: RegressionComparison = {
  ...matched,
  status: "DRIFTED",
  diffs: [
    {
      category: "DEPENDENCY_TOOLCHAIN",
      pointer: "/provenance/dependencies/0/version",
      status: "REPLACED",
      baselineValue: "1.0.0",
      candidateValue: "2.0.0",
    },
  ],
};

describe("BacktestRegressionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedRuns.mockReturnValue({ status: "success", data: [summary], error: null });
    mockedArtifact.mockReturnValue({ status: "success", data: artifact, error: null });
    mockedComparison.mockReturnValue({ status: "success", data: matched, error: null });
  });

  it("renders loading, empty, error and forbidden states", () => {
    mockedRuns.mockReturnValue({ status: "loading", data: null, error: null });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("正在读取");
    mockedRuns.mockReturnValue({ status: "empty", data: [], error: null });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("暂无已审核");
    mockedRuns.mockReturnValue({ status: "error", data: null, error: new Error("offline") });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("加载失败");
    mockedRuns.mockReturnValue({ status: "forbidden", data: null, error: new Error("denied") });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("无权访问");
  });

  it("renders matched and drifted evidence states without baseline controls", () => {
    const matchedHtml = renderToStaticMarkup(<BacktestRegressionPage />);
    expect(matchedHtml).toContain("证据账本");
    expect(matchedHtml).toContain("LOCAL_PREVIEW");
    expect(matchedHtml).toContain("没有差异");
    expect(matchedHtml).toContain("基线不会自动更新");
    expect(matchedHtml).toContain('<caption data-slot="table-caption"');
    expect(matchedHtml).not.toMatch(/accept|update|接受基线|更新基线/i);

    mockedComparison.mockReturnValue({ status: "success", data: drifted, error: null });
    const driftedHtml = renderToStaticMarkup(<BacktestRegressionPage />);
    expect(driftedHtml).toContain("DRIFTED");
    expect(driftedHtml).toContain("DEPENDENCY_TOOLCHAIN");
    expect(driftedHtml).toContain("/provenance/dependencies/0/version");
  });

  it("renders forbidden and error states for artifact/comparison queries", () => {
    mockedArtifact.mockReturnValue({ status: "forbidden", data: null, error: new Error("denied") });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("无权访问");
    mockedArtifact.mockReturnValue({ status: "error", data: null, error: new Error("corrupt") });
    expect(renderToStaticMarkup(<BacktestRegressionPage />)).toContain("不可用");
  });
});
