import type { BacktestRegressionArtifact, BacktestRegressionBaseline } from "@kunlun/shared-types";
import { toolchainEvidenceSha256 } from "@kunlun/contracts/backtest-regression";
import { sha256Json } from "./backtest-regression.validation";

function previewArtifact(): BacktestRegressionArtifact {
  const times = [
    "2026-05-29T01:00:00.000000Z",
    "2026-06-01T01:00:00.000000Z",
    "2026-06-02T01:00:00.000000Z",
    "2026-06-03T01:00:00.000000Z",
  ] as const;
  const digest = (value: unknown): string => sha256Json(value);
  const nav = ["100000", "100400", "100200", "100600"] as const;
  const observations: BacktestRegressionArtifact["inputs"]["navObservations"] = [
    { observationTime: times[0], nav: nav[0], provenanceDigest: digest(["nav", 0]) },
    { observationTime: times[1], nav: nav[1], provenanceDigest: digest(["nav", 1]) },
    { observationTime: times[2], nav: nav[2], provenanceDigest: digest(["nav", 2]) },
    { observationTime: times[3], nav: nav[3], provenanceDigest: digest(["nav", 3]) },
  ];
  const riskFreeObservations: BacktestRegressionArtifact["inputs"]["riskFreeObservations"] = [
    { observationTime: times[0], rate: "0", provenanceDigest: digest(["rf", 0]) },
    { observationTime: times[1], rate: "0", provenanceDigest: digest(["rf", 1]) },
    { observationTime: times[2], rate: "0", provenanceDigest: digest(["rf", 2]) },
    { observationTime: times[3], rate: "0", provenanceDigest: digest(["rf", 3]) },
  ];
  const manifestJson = { schemaVersion: "1.0.0", engineVersion: "1.0.0", fixture: "local-preview" };
  const toolchain = {
    python: "3.12.13" as const,
    uv: "0.12.3" as const,
    hatchling: "1.27.0",
    rootPyprojectSha256: digest("preview-root-pyproject"),
    servicePyprojectSha256: digest("preview-service-pyproject"),
    uvLockSha256: digest("preview-uv-lock"),
  };
  const artifactWithoutDigest = {
    schemaVersion: "backtest-regression-run-v1" as const,
    canonicalizationVersion: "backtest-regression-c14n-v1" as const,
    suiteId: "p5-core-chain",
    runId: "local-preview-run",
    fixtureId: "local-preview-fixture",
    trust: {
      mode: "FIXTURE_SELF_CONTAINED" as const,
      evidenceIntegrityConfidence: "HIGH" as const,
      evidenceRefs: [
        { kind: "OPAQUE_EXTERNAL" as const, namespace: "preview", value: "local-preview" },
      ],
    },
    manifest: { json: manifestJson, sha256: digest(manifestJson) },
    inputs: {
      fixtureSha256: digest("local-preview-fixture"),
      executionInputDigests: [digest("execution")],
      portfolioHistoryRef: {
        tapeId: "local-preview-history",
        eventTapeDigest: digest("history"),
        eventCount: 3,
      },
      valuationLineage: {
        valuationPolicyId: "raw-accounting-mark",
        valuationPolicyVersion: "1.0.0",
        valuationPolicyDigest: digest("valuation-policy"),
        valuations: times.map((observationTime, index) => ({
          observationTime,
          inputDigest: digest(["valuation-input", index]),
          markDigest: digest(["mark", index]),
          stateDigest: digest("state"),
          nav: nav[index] ?? "0",
        })),
      },
      navObservations: observations,
      riskFreeObservations,
      tPlusOne: {
        buyOrderId: "preview-buy",
        sellOrderId: "preview-sell",
        buyExecutionInputDigest: digest("execution-buy"),
        sameDaySellExecutionInputDigest: digest("execution-sell-same-day"),
        nextDaySellExecutionInputDigest: digest("execution-sell-next-day"),
        sameDaySellabilityDigest: digest("sellability-same-day"),
        nextDaySellabilityDigest: digest("sellability-next-day"),
        sameDayBatchDigest: digest("batch-same-day"),
        nextDayBatchDigest: digest("batch-next-day"),
      },
    },
    provenance: {
      code: {
        allowlist: [{ path: "fixture/local-preview.json", sha256: digest("fixture") }],
        treeSha256: digest("fixture-tree"),
      },
      config: [
        { name: "preview", version: "1.0.0", sha256: digest("config") },
        {
          name: "quant-engine-pyproject.toml",
          version: "0.0.0",
          sha256: toolchain.servicePyprojectSha256,
        },
        {
          name: "root-pyproject.toml",
          version: "repo-root",
          sha256: toolchain.rootPyprojectSha256,
        },
      ],
      dependencies: [
        { name: "uv.lock", version: "repo-root", sha256: toolchain.uvLockSha256 },
        { name: "workspace", version: "0.0.0", sha256: digest("dependencies") },
      ],
      toolchain: { ...toolchain, evidenceSha256: toolchainEvidenceSha256(toolchain) },
    },
    versions: {
      engine: "1.0.0",
      manifest: "1.0.0",
      eventOrder: "1.0.0",
      execution: "execution-v1",
      matching: "matching-v1",
      portfolio: "portfolio-v1",
      valuation: "valuation-v1",
      metrics: "1.0.0",
      strategy: "1.0.0",
      policy: "1.0.0",
      fixture: "local-preview-fixture",
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
      pnl: { realized: "0", unrealized: "600", total: "600", fees: "2" },
      finalNav: "100600",
      finalValuation: {
        cutoffTime: times[3],
        nav: "100600",
        totalPnl: "600",
        stateDigest: digest("state"),
        inputDigest: digest("valuation-input-3"),
        sampleCount: 1,
      },
      metrics: {
        cumulativeChainedReturn: { status: "AVAILABLE", value: "0.006" },
        annualizedReturn: { status: "AVAILABLE", value: "0.6" },
        annualizedVolatility: { status: "AVAILABLE", value: "0.01" },
        maximumDrawdown: { status: "AVAILABLE", value: "0.002" },
        sharpe: { status: "AVAILABLE", value: "1" },
        sortino: { status: "AVAILABLE", value: "1" },
        calmar: { status: "AVAILABLE", value: "2" },
      },
      observations,
      tPlusOne: {
        sameDay: {
          orderId: "preview-sell",
          status: "REJECTED" as const,
          rejectReason: "T_PLUS_ONE_NOT_SELLABLE",
          fillCount: 0,
          batchDigest: digest("batch-same-day"),
          resultDigest: digest("result-same-day"),
          tradingDate: "2026-05-29",
          sellabilityDigest: digest("sellability-same-day"),
        },
        nextDay: {
          orderId: "preview-sell",
          status: "FILLED" as const,
          rejectReason: null,
          fillCount: 1,
          batchDigest: digest("batch-next-day"),
          resultDigest: digest("result-next-day"),
          tradingDate: "2026-06-01",
          sellabilityDigest: digest("sellability-next-day"),
        },
      },
    },
  } satisfies Omit<BacktestRegressionArtifact, "artifactSha256">;
  return { ...artifactWithoutDigest, artifactSha256: sha256Json(artifactWithoutDigest) };
}

export const LOCAL_PREVIEW_ARTIFACT = previewArtifact();
export const LOCAL_PREVIEW_BASELINE: BacktestRegressionBaseline = {
  schemaVersion: "backtest-regression-baseline-v1",
  baselineId: "p5-core-chain",
  suiteId: "p5-core-chain",
  expectedArtifact: LOCAL_PREVIEW_ARTIFACT,
  expectedArtifactSha256: LOCAL_PREVIEW_ARTIFACT.artifactSha256,
  approval: {
    approvalId: "local-preview-approval",
    reviewedBy: "LOCAL_PREVIEW",
    reviewedAt: "2026-08-26T00:00:00.000000Z",
    reviewedArtifactSha256: LOCAL_PREVIEW_ARTIFACT.artifactSha256,
    changeReference: { kind: "OPAQUE_EXTERNAL", namespace: "preview", value: "local-preview" },
    reason: "Explicit local preview fixture; no baseline controls are exposed.",
    evidenceRefs: [{ kind: "OPAQUE_EXTERNAL", namespace: "preview", value: "local-preview" }],
  },
};
