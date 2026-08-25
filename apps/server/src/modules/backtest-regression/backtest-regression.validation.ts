import { createHash } from "node:crypto";
import type {
  BacktestRegressionArtifact,
  BacktestRegressionBaseline,
} from "@kunlun/shared-types";
import {
  parseBacktestRegressionArtifact as parseContractArtifact,
  parseBacktestRegressionBaseline as parseContractBaseline,
} from "@kunlun/contracts/backtest-regression";

export class BacktestRegressionValidationError extends Error {}
export class BacktestRegressionUnavailableError extends Error {}

const SHA256 = /^[0-9a-f]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const DECIMAL = /^(?:0|-?(?:0\.[0-9]*[1-9]|[1-9][0-9]*(?:\.[0-9]*[1-9])?))$/;

export type JsonObject = Record<string, unknown>;
type ArtifactInputs = BacktestRegressionArtifact["inputs"];
type Observation = ArtifactInputs["navObservations"][number];
type RiskFreeObservation = ArtifactInputs["riskFreeObservations"][number];
type TPlusOneInputs = ArtifactInputs["tPlusOne"];
type TPlusOneResults = BacktestRegressionArtifact["results"]["tPlusOne"];
type DigestReference = BacktestRegressionArtifact["trust"]["evidenceRefs"][number];
type DigestEntry = BacktestRegressionArtifact["provenance"]["config"][number];
type CodeDigestEntry = BacktestRegressionArtifact["provenance"]["code"]["allowlist"][number];
type BaselineApproval = BacktestRegressionBaseline["approval"];

export function assertSafeId(value: unknown, field: string): string {
  if (typeof value !== "string" || !SAFE_ID.test(value) || value.includes("..") || /\s|\0/.test(value)) {
    throw new BacktestRegressionValidationError(`${field} is not a safe id`);
  }
  return value;
}

export function assertSha256(value: unknown, field: string): string {
  if (typeof value !== "string" || !SHA256.test(value)) {
    throw new BacktestRegressionValidationError(`${field} must be lowercase SHA-256`);
  }
  return value;
}

export function assertTimestamp(value: unknown, field: string): string {
  if (typeof value !== "string" || !TIMESTAMP.test(value) || Number.isNaN(Date.parse(value))) {
    throw new BacktestRegressionValidationError(`${field} must be UTC RFC3339 with six fractional digits`);
  }
  return value;
}

export function assertDecimal(value: unknown, field: string): string {
  if (typeof value !== "string" || !DECIMAL.test(value) || /^-0(?:\.0+)?$/.test(value)) {
    throw new BacktestRegressionValidationError(`${field} must be a canonical Decimal string`);
  }
  const unsigned = value.startsWith("-") ? value.slice(1) : value;
  const [integer, fraction] = unsigned.split(".");
  const normalized = `${value.startsWith("-") ? "-" : ""}${integer}${fraction === undefined ? "" : `.${fraction.replace(/0+$/, "")}`}`.replace(/\.$/, "");
  if (normalized !== value) throw new BacktestRegressionValidationError(`${field} must use canonical Decimal spelling`);
  return value;
}

function assertText(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) throw new BacktestRegressionValidationError(`${field} must be text`);
  return value;
}

function assertNonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) throw new BacktestRegressionValidationError(`${field} must be a non-negative integer`);
  return value;
}

export function exactObject(value: unknown, keys: readonly string[], field: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new BacktestRegressionValidationError(`${field} must be an object`);
  }
  const result = value as JsonObject;
  const allowed = new Set(keys);
  for (const key of Object.keys(result)) {
    if (!allowed.has(key)) throw new BacktestRegressionValidationError(`${field} contains unknown key ${key}`);
  }
  for (const key of keys) {
    if (!(key in result)) throw new BacktestRegressionValidationError(`${field} is missing key ${key}`);
  }
  return result;
}

function canonicalValue(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number") {
    if (typeof value === "number" && (!Number.isFinite(value) || !Number.isInteger(value))) {
      throw new BacktestRegressionValidationError("canonical JSON must not contain floating point numbers");
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (typeof value === "object") {
    const result: JsonObject = {};
    for (const key of Object.keys(value as JsonObject).sort()) {
      if ([...key].some((character) => character.charCodeAt(0) > 0x7f)) {
        throw new BacktestRegressionValidationError("canonical JSON object keys must be ASCII");
      }
      result[key] = canonicalValue((value as JsonObject)[key]);
    }
    return result;
  }
  throw new BacktestRegressionValidationError("unsupported JSON value");
}

export function canonicalJson(value: unknown): string {
  return `${JSON.stringify(canonicalValue(value))}\n`;
}

export function sha256Json(value: unknown): string {
  return createHash("sha256").update(Buffer.from(canonicalJson(value), "utf8")).digest("hex");
}

function digestReference(value: unknown, field: string): DigestReference {
  const item = value as JsonObject;
  if (item === null || typeof item !== "object" || Array.isArray(item)) {
    throw new BacktestRegressionValidationError(`${field} must be a digest reference`);
  }
  if (item.kind === "CONTENT_SHA256") {
    exactObject(item, ["kind", "sha256"], field);
    return { kind: "CONTENT_SHA256", sha256: assertSha256(item.sha256, `${field}.sha256`) };
  } else if (item.kind === "OPAQUE_EXTERNAL") {
    exactObject(item, ["kind", "namespace", "value"], field);
    if (typeof item.namespace !== "string" || item.namespace.length === 0 || typeof item.value !== "string" || item.value.length === 0) {
      throw new BacktestRegressionValidationError(`${field} opaque value is invalid`);
    }
    return { kind: "OPAQUE_EXTERNAL", namespace: item.namespace, value: item.value };
  } else {
    throw new BacktestRegressionValidationError(`${field}.kind is unsupported`);
  }
}

function observations(value: unknown, field: string, valueKey: "nav"): [Observation, Observation, Observation, Observation, ...Observation[]];
function observations(value: unknown, field: string, valueKey: "rate"): [RiskFreeObservation, RiskFreeObservation, RiskFreeObservation, RiskFreeObservation, ...RiskFreeObservation[]];
function observations(value: unknown, field: string, valueKey: "nav" | "rate"):
  | [Observation, Observation, Observation, Observation, ...Observation[]]
  | [RiskFreeObservation, RiskFreeObservation, RiskFreeObservation, RiskFreeObservation, ...RiskFreeObservation[]] {
  if (!Array.isArray(value)) throw new BacktestRegressionValidationError(`${field} must be an array`);
  if (value.length < 4) throw new BacktestRegressionValidationError(`${field} must contain at least four observations`);
  let previous: string | null = null;
  const parsed: Array<Observation | RiskFreeObservation> = [];
  value.forEach((raw, index) => {
    const item = exactObject(raw, ["observationTime", valueKey, "provenanceDigest"], `${field}[${index}]`);
    const current = assertTimestamp(item.observationTime, `${field}[${index}].observationTime`);
    if (previous !== null && current <= previous) throw new BacktestRegressionValidationError(`${field} must be ordered`);
    previous = current;
    const provenanceDigest = assertSha256(item.provenanceDigest, `${field}[${index}].provenanceDigest`);
    if (valueKey === "nav") parsed.push({ observationTime: current, nav: assertDecimal(item.nav, `${field}[${index}].nav`), provenanceDigest });
    else parsed.push({ observationTime: current, rate: assertDecimal(item.rate, `${field}[${index}].rate`), provenanceDigest });
  });
  if (valueKey === "nav") {
    const nav = parsed as Observation[];
    return [nav[0]!, nav[1]!, nav[2]!, nav[3]!, ...nav.slice(4)];
  }
  const rates = parsed as RiskFreeObservation[];
  return [rates[0]!, rates[1]!, rates[2]!, rates[3]!, ...rates.slice(4)];
}

function tPlusOne(value: unknown, field: string, inputs: true): TPlusOneInputs;
function tPlusOne(value: unknown, field: string, inputs: false): TPlusOneResults;
function tPlusOne(value: unknown, field: string, inputs: boolean): TPlusOneInputs | TPlusOneResults {
  if (inputs) {
    const item = exactObject(
      value,
      [
        "buyOrderId",
        "sellOrderId",
        "buyExecutionInputDigest",
        "sameDaySellExecutionInputDigest",
        "nextDaySellExecutionInputDigest",
        "sameDaySellabilityDigest",
        "nextDaySellabilityDigest",
        "sameDayBatchDigest",
        "nextDayBatchDigest",
      ],
      field,
    );
    return {
      buyOrderId: assertSafeId(item.buyOrderId, `${field}.buyOrderId`),
      sellOrderId: assertSafeId(item.sellOrderId, `${field}.sellOrderId`),
      buyExecutionInputDigest: assertSha256(item.buyExecutionInputDigest, `${field}.buyExecutionInputDigest`),
      sameDaySellExecutionInputDigest: assertSha256(item.sameDaySellExecutionInputDigest, `${field}.sameDaySellExecutionInputDigest`),
      nextDaySellExecutionInputDigest: assertSha256(item.nextDaySellExecutionInputDigest, `${field}.nextDaySellExecutionInputDigest`),
      sameDaySellabilityDigest: assertSha256(item.sameDaySellabilityDigest, `${field}.sameDaySellabilityDigest`),
      nextDaySellabilityDigest: assertSha256(item.nextDaySellabilityDigest, `${field}.nextDaySellabilityDigest`),
      sameDayBatchDigest: assertSha256(item.sameDayBatchDigest, `${field}.sameDayBatchDigest`),
      nextDayBatchDigest: assertSha256(item.nextDayBatchDigest, `${field}.nextDayBatchDigest`),
    };
  }
  const results = exactObject(value, ["sameDay", "nextDay"], field);
  const parseObservation = (name: "sameDay" | "nextDay"): TPlusOneResults["sameDay"] => {
    const item = exactObject(
      results[name],
      [
        "orderId",
        "status",
        "rejectReason",
        "fillCount",
        "batchDigest",
        "resultDigest",
        "tradingDate",
        "sellabilityDigest",
      ],
      `${field}.${name}`,
    );
    const orderId = assertSafeId(item.orderId, `${field}.${name}.orderId`);
    if (item.status !== "REJECTED" && item.status !== "FILLED") {
      throw new BacktestRegressionValidationError(`${field}.${name}.status is invalid`);
    }
    if (item.rejectReason !== null && typeof item.rejectReason !== "string") {
      throw new BacktestRegressionValidationError(`${field}.${name}.rejectReason is invalid`);
    }
    if (typeof item.fillCount !== "number" || !Number.isInteger(item.fillCount) || item.fillCount < 0) {
      throw new BacktestRegressionValidationError(`${field}.${name}.fillCount is invalid`);
    }
    const batchDigest = assertSha256(item.batchDigest, `${field}.${name}.batchDigest`);
    const resultDigest = assertSha256(item.resultDigest, `${field}.${name}.resultDigest`);
    if (typeof item.tradingDate !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(item.tradingDate) || Number.isNaN(Date.parse(`${item.tradingDate}T00:00:00Z`))) {
      throw new BacktestRegressionValidationError(`${field}.${name}.tradingDate is invalid`);
    }
    const rejectReason = item.rejectReason === null ? null : assertText(item.rejectReason, `${field}.${name}.rejectReason`);
    if (item.status === "REJECTED" && rejectReason === null) throw new BacktestRegressionValidationError(`${field}.${name}.rejectReason is required for rejected orders`);
    if (item.status === "FILLED" && rejectReason !== null) throw new BacktestRegressionValidationError(`${field}.${name}.rejectReason must be null for filled orders`);
    return {
      orderId,
      status: item.status,
      rejectReason,
      fillCount: item.fillCount,
      batchDigest,
      resultDigest,
      tradingDate: item.tradingDate,
      sellabilityDigest: item.sellabilityDigest === null ? null : assertSha256(item.sellabilityDigest, `${field}.${name}.sellabilityDigest`),
    };
  };
  const sameDay = parseObservation("sameDay");
  const nextDay = parseObservation("nextDay");
  if (sameDay.status !== "REJECTED" || sameDay.rejectReason !== "T_PLUS_ONE_NOT_SELLABLE") throw new BacktestRegressionValidationError(`${field}.sameDay must record the T+1 rejection`);
  if (nextDay.status !== "FILLED" || nextDay.fillCount < 1) throw new BacktestRegressionValidationError(`${field}.nextDay must record a fill`);
  return { sameDay, nextDay };
}

function digestEntries(value: unknown, field: string): DigestEntry[] {
  if (!Array.isArray(value)) throw new BacktestRegressionValidationError(`${field} must be an array`);
  return value.map((raw, index) => {
    const entry = exactObject(raw, ["name", "version", "sha256"], `${field}[${index}]`);
    return {
      name: assertText(entry.name, `${field}[${index}].name`),
      version: assertText(entry.version, `${field}[${index}].version`),
      sha256: assertSha256(entry.sha256, `${field}[${index}].sha256`),
    };
  });
}

function parseBacktestRegressionArtifactLegacy(value: unknown): BacktestRegressionArtifact {
  const item = exactObject(value, ["schemaVersion", "canonicalizationVersion", "suiteId", "runId", "fixtureId", "trust", "manifest", "inputs", "provenance", "versions", "results", "artifactSha256"], "artifact");
  if (item.schemaVersion !== "backtest-regression-run-v1" || item.canonicalizationVersion !== "backtest-regression-c14n-v1") throw new BacktestRegressionValidationError("artifact schema is unsupported");
  const suiteId = assertSafeId(item.suiteId, "artifact.suiteId");
  const runId = assertSafeId(item.runId, "artifact.runId");
  const fixtureId = assertSafeId(item.fixtureId, "artifact.fixtureId");
  const trust = exactObject(item.trust, ["mode", "evidenceIntegrityConfidence", "evidenceRefs"], "artifact.trust");
  if (trust.mode !== "FIXTURE_SELF_CONTAINED" && trust.mode !== "VERIFIED") throw new BacktestRegressionValidationError("artifact trust mode is unsupported");
  if (trust.evidenceIntegrityConfidence !== "LOW" && trust.evidenceIntegrityConfidence !== "MEDIUM" && trust.evidenceIntegrityConfidence !== "HIGH") throw new BacktestRegressionValidationError("artifact evidence confidence is unsupported");
  if (!Array.isArray(trust.evidenceRefs)) throw new BacktestRegressionValidationError("artifact evidenceRefs must be an array");
  const typedTrust: BacktestRegressionArtifact["trust"] = {
    mode: trust.mode,
    evidenceIntegrityConfidence: trust.evidenceIntegrityConfidence,
    evidenceRefs: trust.evidenceRefs.map((ref, index) => digestReference(ref, `artifact.trust.evidenceRefs[${index}]`)),
  };
  const manifest = exactObject(item.manifest, ["json", "sha256"], "artifact.manifest");
  if (manifest.json === null || typeof manifest.json !== "object" || Array.isArray(manifest.json)) throw new BacktestRegressionValidationError("manifest.json must be an object");
  const manifestJson: Record<string, unknown> = {};
  Object.entries(manifest.json).forEach(([key, value]) => { manifestJson[key] = value; });
  const manifestDigest = assertSha256(manifest.sha256, "manifest.sha256");
  if (sha256Json(manifest.json) !== manifestDigest) throw new BacktestRegressionUnavailableError("manifest digest mismatch");
  const typedManifest = { json: manifestJson, sha256: manifestDigest };
  const inputs = exactObject(item.inputs, ["fixtureSha256", "executionInputDigests", "portfolioHistoryRef", "valuationLineage", "navObservations", "riskFreeObservations", "tPlusOne"], "artifact.inputs");
  const fixtureSha256 = assertSha256(inputs.fixtureSha256, "inputs.fixtureSha256");
  if (!Array.isArray(inputs.executionInputDigests)) throw new BacktestRegressionValidationError("inputs.executionInputDigests must be an array");
  const executionInputDigests = inputs.executionInputDigests.map((digest, index) => assertSha256(digest, `inputs.executionInputDigests[${index}]`));
  const history = exactObject(inputs.portfolioHistoryRef, ["tapeId", "eventTapeDigest", "eventCount"], "portfolioHistoryRef");
  const portfolioHistoryRef = {
    tapeId: assertSafeId(history.tapeId, "portfolioHistoryRef.tapeId"),
    eventTapeDigest: assertSha256(history.eventTapeDigest, "portfolioHistoryRef.eventTapeDigest"),
    eventCount: assertNonNegativeInteger(history.eventCount, "portfolioHistoryRef.eventCount"),
  };
  const lineage = exactObject(inputs.valuationLineage, ["valuationPolicyId", "valuationPolicyVersion", "valuationPolicyDigest", "valuations"], "valuationLineage");
  if (typeof lineage.valuationPolicyId !== "string" || typeof lineage.valuationPolicyVersion !== "string") throw new BacktestRegressionValidationError("valuation policy identity is invalid");
  const valuationPolicyDigest = assertSha256(lineage.valuationPolicyDigest, "valuationLineage.valuationPolicyDigest");
  if (!Array.isArray(lineage.valuations)) throw new BacktestRegressionValidationError("valuationLineage.valuations must be an array");
  const valuations = lineage.valuations.map((raw, index) => {
    const valuation = exactObject(raw, ["observationTime", "inputDigest", "markDigest", "stateDigest", "nav"], `valuationLineage.valuations[${index}]`);
    return {
      observationTime: assertTimestamp(valuation.observationTime, `valuationLineage.valuations[${index}].observationTime`),
      inputDigest: assertSha256(valuation.inputDigest, `valuationLineage.valuations[${index}].inputDigest`),
      markDigest: assertSha256(valuation.markDigest, `valuationLineage.valuations[${index}].markDigest`),
      stateDigest: assertSha256(valuation.stateDigest, `valuationLineage.valuations[${index}].stateDigest`),
      nav: assertDecimal(valuation.nav, `valuationLineage.valuations[${index}].nav`),
    };
  });
  const typedInputs: ArtifactInputs = {
    fixtureSha256,
    executionInputDigests,
    portfolioHistoryRef,
    valuationLineage: {
      valuationPolicyId: lineage.valuationPolicyId,
      valuationPolicyVersion: lineage.valuationPolicyVersion,
      valuationPolicyDigest,
      valuations,
    },
    navObservations: observations(inputs.navObservations, "inputs.navObservations", "nav"),
    riskFreeObservations: observations(inputs.riskFreeObservations, "inputs.riskFreeObservations", "rate"),
    tPlusOne: tPlusOne(inputs.tPlusOne, "inputs.tPlusOne", true),
  };
  const provenance = exactObject(item.provenance, ["code", "config", "dependencies", "toolchain"], "artifact.provenance");
  const code = exactObject(provenance.code, ["allowlist", "treeSha256"], "provenance.code");
  if (!Array.isArray(code.allowlist)) throw new BacktestRegressionValidationError("provenance.code.allowlist must be an array");
  const codeAllowlist: CodeDigestEntry[] = code.allowlist.map((raw, index) => {
    const entry = exactObject(raw, ["path", "sha256"], `provenance.code.allowlist[${index}]`);
    const path = assertText(entry.path, `provenance.code.allowlist[${index}].path`);
    if (path.startsWith("/") || path.includes("\\") || path.includes("://") || path.split("/").some((part) => part === "" || part === "." || part === "..")) throw new BacktestRegressionValidationError("provenance code path is not relative");
    return { path, sha256: assertSha256(entry.sha256, `provenance.code.allowlist[${index}].sha256`) };
  });
  const codeTreeSha256 = assertSha256(code.treeSha256, "provenance.code.treeSha256");
  const config = digestEntries(provenance.config, "provenance.config");
  const dependencies = digestEntries(provenance.dependencies, "provenance.dependencies");
  const toolchain = exactObject(provenance.toolchain, ["python", "uv", "hatchling", "rootPyprojectSha256", "servicePyprojectSha256", "uvLockSha256", "evidenceSha256"], "provenance.toolchain");
  if (toolchain.python !== "3.12.13" || toolchain.uv !== "0.12.3" || toolchain.hatchling !== "1.27.0") throw new BacktestRegressionValidationError("toolchain pin mismatch");
  const typedProvenance: BacktestRegressionArtifact["provenance"] = {
    code: { allowlist: codeAllowlist, treeSha256: codeTreeSha256 },
    config,
    dependencies,
    toolchain: {
      python: "3.12.13",
      uv: "0.12.3",
      hatchling: "1.27.0",
      rootPyprojectSha256: assertSha256(toolchain.rootPyprojectSha256, "provenance.toolchain.rootPyprojectSha256"),
      servicePyprojectSha256: assertSha256(toolchain.servicePyprojectSha256, "provenance.toolchain.servicePyprojectSha256"),
      uvLockSha256: assertSha256(toolchain.uvLockSha256, "provenance.toolchain.uvLockSha256"),
      evidenceSha256: assertSha256(toolchain.evidenceSha256, "provenance.toolchain.evidenceSha256"),
    },
  };
  const versions = exactObject(item.versions, ["engine", "manifest", "eventOrder", "execution", "matching", "portfolio", "valuation", "metrics", "strategy", "policy", "fixture"], "artifact.versions");
  const version = (key: string): string => assertText(versions[key], `versions.${key}`);
  const typedVersions: BacktestRegressionArtifact["versions"] = {
    engine: version("engine"), manifest: version("manifest"), eventOrder: version("eventOrder"), execution: version("execution"),
    matching: version("matching"), portfolio: version("portfolio"), valuation: version("valuation"), metrics: version("metrics"),
    strategy: version("strategy"), policy: version("policy"), fixture: version("fixture"),
  };
  const results = exactObject(item.results, ["counts", "pnl", "finalNav", "finalValuation", "metrics", "observations", "tPlusOne"], "artifact.results");
  const counts = exactObject(results.counts, ["events", "intents", "orders", "fills", "navObservations", "tPlusOneRejected", "nextDaySellFills"], "results.counts");
  const count = (key: string): number => assertNonNegativeInteger(counts[key], `results.counts.${key}`);
  const typedCounts = {
    events: count("events"), intents: count("intents"), orders: count("orders"), fills: count("fills"),
    navObservations: count("navObservations"), tPlusOneRejected: count("tPlusOneRejected"), nextDaySellFills: count("nextDaySellFills"),
  };
  const pnl = exactObject(results.pnl, ["realized", "unrealized", "total", "fees"], "results.pnl");
  const typedPnl = {
    realized: assertDecimal(pnl.realized, "results.pnl.realized"),
    unrealized: assertDecimal(pnl.unrealized, "results.pnl.unrealized"),
    total: assertDecimal(pnl.total, "results.pnl.total"),
    fees: assertDecimal(pnl.fees, "results.pnl.fees"),
  };
  const finalNav = assertDecimal(results.finalNav, "results.finalNav");
  const finalValuation = exactObject(results.finalValuation, ["cutoffTime", "nav", "totalPnl", "stateDigest", "inputDigest", "sampleCount"], "results.finalValuation");
  const typedFinalValuation = {
    cutoffTime: assertTimestamp(finalValuation.cutoffTime, "results.finalValuation.cutoffTime"),
    nav: assertDecimal(finalValuation.nav, "results.finalValuation.nav"),
    totalPnl: assertDecimal(finalValuation.totalPnl, "results.finalValuation.totalPnl"),
    stateDigest: assertSha256(finalValuation.stateDigest, "results.finalValuation.stateDigest"),
    inputDigest: assertSha256(finalValuation.inputDigest, "results.finalValuation.inputDigest"),
    sampleCount: assertNonNegativeInteger(finalValuation.sampleCount, "results.finalValuation.sampleCount"),
  };
  const metrics = exactObject(results.metrics, ["cumulativeChainedReturn", "annualizedReturn", "annualizedVolatility", "maximumDrawdown", "sharpe", "sortino", "calmar"], "results.metrics");
  const metric = (key: string): BacktestRegressionArtifact["results"]["metrics"]["sharpe"] => {
    const raw = exactObject(metrics[key], ["status", "value"], `results.metrics.${key}`);
    return {
      status: assertText(raw.status, `results.metrics.${key}.status`),
      value: raw.value === null ? null : assertDecimal(raw.value, `results.metrics.${key}.value`),
    };
  };
  const typedMetrics = {
    cumulativeChainedReturn: metric("cumulativeChainedReturn"),
    annualizedReturn: metric("annualizedReturn"),
    annualizedVolatility: metric("annualizedVolatility"),
    maximumDrawdown: metric("maximumDrawdown"),
    sharpe: metric("sharpe"),
    sortino: metric("sortino"),
    calmar: metric("calmar"),
  };
  const typedResults: BacktestRegressionArtifact["results"] = {
    counts: typedCounts,
    pnl: typedPnl,
    finalNav,
    finalValuation: typedFinalValuation,
    metrics: typedMetrics,
    observations: observations(results.observations, "results.observations", "nav"),
    tPlusOne: tPlusOne(results.tPlusOne, "results.tPlusOne", false),
  };
  /* Keep the explicit result fields above; unknown keys are rejected by exactObject. */
  Object.entries(metrics).forEach(([key, raw]) => {
    const metric = exactObject(raw, ["status", "value"], `results.metrics.${key}`);
    if (typeof metric.status !== "string" || metric.status.length === 0) throw new BacktestRegressionValidationError(`results.metrics.${key}.status is invalid`);
    if (metric.value !== null) assertDecimal(metric.value, `results.metrics.${key}.value`);
  });
  const artifactSha256 = assertSha256(item.artifactSha256, "artifact.artifactSha256");
  const artifactWithoutDigest: Omit<BacktestRegressionArtifact, "artifactSha256"> = {
    schemaVersion: "backtest-regression-run-v1",
    canonicalizationVersion: "backtest-regression-c14n-v1",
    suiteId,
    runId,
    fixtureId,
    trust: typedTrust,
    manifest: typedManifest,
    inputs: typedInputs,
    provenance: typedProvenance,
    versions: typedVersions,
    results: typedResults,
  };
  if (sha256Json(artifactWithoutDigest) !== artifactSha256) throw new BacktestRegressionUnavailableError("artifact digest mismatch");
  return { ...artifactWithoutDigest, artifactSha256 };
}

function assertNoDuplicateJsonKeys(raw: string): void {
  let index = 0;

  const fail = (): never => {
    throw new BacktestRegressionValidationError("JSON contains invalid structure or duplicate keys");
  };
  const skipWhitespace = (): void => {
    while (index < raw.length && /\s/.test(raw[index] ?? "")) index += 1;
  };
  const parseString = (): string => {
    if (raw[index] !== '"') fail();
    const start = index;
    index += 1;
    while (index < raw.length) {
      const character = raw[index];
      if (character === "\\") {
        index += 2;
        continue;
      }
      index += 1;
      if (character === '"') {
        const parsed = JSON.parse(raw.slice(start, index)) as unknown;
        if (typeof parsed !== "string") fail();
        return parsed as string;
      }
    }
    return fail();
  };
  const parseValue = (): void => {
    skipWhitespace();
    const character = raw[index];
    if (character === '"') {
      parseString();
      return;
    }
    if (character === "{") {
      index += 1;
      skipWhitespace();
      const keys = new Set<string>();
      if (raw[index] === "}") {
        index += 1;
        return;
      }
      while (index < raw.length) {
        skipWhitespace();
        const key = parseString();
        if (keys.has(key)) fail();
        keys.add(key);
        skipWhitespace();
        if (raw[index] !== ":") fail();
        index += 1;
        parseValue();
        skipWhitespace();
        if (raw[index] === "}") {
          index += 1;
          return;
        }
        if (raw[index] !== ",") fail();
        index += 1;
      }
      fail();
    }
    if (character === "[") {
      index += 1;
      skipWhitespace();
      if (raw[index] === "]") {
        index += 1;
        return;
      }
      while (index < raw.length) {
        parseValue();
        skipWhitespace();
        if (raw[index] === "]") {
          index += 1;
          return;
        }
        if (raw[index] !== ",") fail();
        index += 1;
      }
      fail();
    }
    const start = index;
    while (index < raw.length && !/[\s,\]}]/.test(raw[index] ?? "")) index += 1;
    if (start === index) fail();
    try {
      JSON.parse(raw.slice(start, index));
    } catch {
      fail();
    }
  };

  parseValue();
  skipWhitespace();
  if (index !== raw.length) fail();
}

export function parseCanonicalBacktestRegressionJson(raw: string): JsonObject {
  if (raw.charCodeAt(0) === 0xfeff || raw.includes("\r")) throw new BacktestRegressionUnavailableError("artifact JSON encoding is invalid");
  assertNoDuplicateJsonKeys(raw);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch (error) {
    throw new BacktestRegressionUnavailableError("artifact JSON is malformed");
  }
  if (canonicalJson(parsed) !== raw) throw new BacktestRegressionUnavailableError("artifact JSON is not canonical");
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new BacktestRegressionUnavailableError("artifact JSON root is not an object");
  }
  return parsed as JsonObject;
}

function parseBacktestRegressionBaselineLegacy(value: unknown): BacktestRegressionBaseline {
  const baseline = exactObject(value, ["schemaVersion", "baselineId", "suiteId", "expectedArtifact", "expectedArtifactSha256", "approval"], "baseline");
  if (baseline.schemaVersion !== "backtest-regression-baseline-v1") throw new BacktestRegressionValidationError("baseline schema is unsupported");
  const baselineId = assertSafeId(baseline.baselineId, "baseline.baselineId");
  const suiteId = assertSafeId(baseline.suiteId, "baseline.suiteId");
  const expected = parseBacktestRegressionArtifact(baseline.expectedArtifact);
  const expectedDigest = assertSha256(baseline.expectedArtifactSha256, "baseline.expectedArtifactSha256");
  if (expectedDigest !== expected.artifactSha256) throw new BacktestRegressionUnavailableError("baseline expected artifact digest mismatch");
  const approval = exactObject(baseline.approval, ["approvalId", "reviewedBy", "reviewedAt", "reviewedArtifactSha256", "changeReference", "reason", "evidenceRefs"], "baseline.approval");
  const approvalId = assertSafeId(approval.approvalId, "baseline.approval.approvalId");
  const reviewedBy = assertText(approval.reviewedBy, "baseline.approval.reviewedBy");
  const reviewedAt = assertTimestamp(approval.reviewedAt, "baseline.approval.reviewedAt");
  if (assertSha256(approval.reviewedArtifactSha256, "baseline.approval.reviewedArtifactSha256") !== expectedDigest) {
    throw new BacktestRegressionUnavailableError("baseline approval artifact digest mismatch");
  }
  const changeReference = digestReference(approval.changeReference, "baseline.approval.changeReference");
  if (changeReference.kind !== "OPAQUE_EXTERNAL") throw new BacktestRegressionValidationError("baseline change reference must be opaque");
  const reason = assertText(approval.reason, "baseline.approval.reason");
  if (!Array.isArray(approval.evidenceRefs)) throw new BacktestRegressionValidationError("baseline approval evidenceRefs must be an array");
  const typedApproval: BaselineApproval = {
    approvalId,
    reviewedBy,
    reviewedAt,
    reviewedArtifactSha256: expectedDigest,
    changeReference,
    reason,
    evidenceRefs: approval.evidenceRefs.map((ref, index) => digestReference(ref, `baseline.approval.evidenceRefs[${index}]`)),
  };
  return {
    schemaVersion: "backtest-regression-baseline-v1",
    baselineId,
    suiteId,
    expectedArtifact: expected,
    expectedArtifactSha256: expectedDigest,
    approval: typedApproval,
  };
}

export function parseBacktestRegressionArtifact(value: unknown): BacktestRegressionArtifact {
  try {
    return parseContractArtifact(value) as unknown as BacktestRegressionArtifact;
  } catch (error) {
    const message = error instanceof Error ? error.message : "artifact validation failed";
    throw new BacktestRegressionValidationError(message);
  }
}

export function parseBacktestRegressionBaseline(value: unknown): BacktestRegressionBaseline {
  try {
    return parseContractBaseline(value) as unknown as BacktestRegressionBaseline;
  } catch (error) {
    const message = error instanceof Error ? error.message : "baseline validation failed";
    throw new BacktestRegressionValidationError(message);
  }
}

export function parseBacktestRegressionJson(raw: string): BacktestRegressionArtifact {
  return parseBacktestRegressionArtifact(parseCanonicalBacktestRegressionJson(raw));
}
