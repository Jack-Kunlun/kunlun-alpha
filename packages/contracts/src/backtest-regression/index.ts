/** Runtime boundary for the read-only backtest regression contracts. */

import { createHash } from "node:crypto";

export type RegressionJsonValue =
  null | boolean | number | string | RegressionJsonValue[] | { [key: string]: RegressionJsonValue };

export interface ContentDigestReference {
  kind: "CONTENT_SHA256";
  sha256: string;
}

export interface OpaqueExternalDigestReference {
  kind: "OPAQUE_EXTERNAL";
  namespace: string;
  value: string;
}

export type DigestReference = ContentDigestReference | OpaqueExternalDigestReference;

type SafeId = string;
type Sha256 = string;
type Timestamp = string;
type Decimal = string;

interface RegressionTrust {
  mode: "FIXTURE_SELF_CONTAINED" | "VERIFIED";
  evidenceIntegrityConfidence: "LOW" | "MEDIUM" | "HIGH";
  evidenceRefs: DigestReference[];
}

interface RegressionManifest {
  json: Record<string, RegressionJsonValue>;
  sha256: Sha256;
}

interface Observation {
  observationTime: Timestamp;
  nav: Decimal;
  provenanceDigest: Sha256;
}

interface RiskFreeObservation {
  observationTime: Timestamp;
  rate: Decimal;
  provenanceDigest: Sha256;
}

interface PortfolioHistoryRef {
  tapeId: SafeId;
  eventTapeDigest: Sha256;
  eventCount: number;
}

interface ValuationLineageItem {
  observationTime: Timestamp;
  inputDigest: Sha256;
  markDigest: Sha256;
  stateDigest: Sha256;
  nav: Decimal;
}

interface ValuationLineage {
  valuationPolicyId: string;
  valuationPolicyVersion: string;
  valuationPolicyDigest: Sha256;
  valuations: ValuationLineageItem[];
}

interface TPlusOneInputs {
  buyOrderId: SafeId;
  sellOrderId: SafeId;
  buyExecutionInputDigest: Sha256;
  sameDaySellExecutionInputDigest: Sha256;
  nextDaySellExecutionInputDigest: Sha256;
  sameDaySellabilityDigest: Sha256;
  nextDaySellabilityDigest: Sha256;
  sameDayBatchDigest: Sha256;
  nextDayBatchDigest: Sha256;
}

interface CodeDigestEntry {
  path: string;
  sha256: Sha256;
}

interface DigestEntry {
  name: string;
  version: string;
  sha256: Sha256;
}

interface CodeProvenance {
  allowlist: CodeDigestEntry[];
  treeSha256: Sha256;
}

interface ToolchainEvidence {
  python: "3.12.13";
  uv: "0.12.3";
  evidenceSha256: Sha256;
  hatchling: string;
  rootPyprojectSha256: Sha256;
  servicePyprojectSha256: Sha256;
  uvLockSha256: Sha256;
}

interface RegressionProvenance {
  code: CodeProvenance;
  config: DigestEntry[];
  dependencies: DigestEntry[];
  toolchain: ToolchainEvidence;
}

interface RegressionVersions {
  engine: string;
  manifest: string;
  eventOrder: string;
  execution: string;
  matching: string;
  portfolio: string;
  valuation: string;
  metrics: string;
  strategy: string;
  policy: string;
  fixture: string;
}

interface FinalValuation {
  cutoffTime: Timestamp;
  nav: Decimal;
  totalPnl: Decimal;
  stateDigest: Sha256;
  inputDigest: Sha256;
  sampleCount: number;
}

interface MetricValue {
  status: string;
  value: Decimal | null;
}

interface TPlusOneObservation {
  orderId: SafeId;
  status: "REJECTED" | "FILLED";
  rejectReason: string | null;
  fillCount: number;
  batchDigest: Sha256;
  resultDigest: Sha256;
  tradingDate: string;
  sellabilityDigest: Sha256 | null;
}

interface TPlusOneResults {
  sameDay: TPlusOneObservation;
  nextDay: TPlusOneObservation;
}

interface RegressionInputs {
  fixtureSha256: Sha256;
  executionInputDigests: Sha256[];
  portfolioHistoryRef: PortfolioHistoryRef;
  valuationLineage: ValuationLineage;
  navObservations: [Observation, Observation, Observation, Observation, ...Observation[]];
  riskFreeObservations: [
    RiskFreeObservation,
    RiskFreeObservation,
    RiskFreeObservation,
    RiskFreeObservation,
    ...RiskFreeObservation[],
  ];
  tPlusOne: TPlusOneInputs;
}

interface RegressionResults {
  counts: {
    events: number;
    intents: number;
    orders: number;
    fills: number;
    navObservations: number;
    tPlusOneRejected: number;
    nextDaySellFills: number;
  };
  pnl: {
    realized: Decimal;
    unrealized: Decimal;
    total: Decimal;
    fees: Decimal;
  };
  finalNav: Decimal;
  finalValuation: FinalValuation;
  metrics: {
    cumulativeChainedReturn: MetricValue;
    annualizedReturn: MetricValue;
    annualizedVolatility: MetricValue;
    maximumDrawdown: MetricValue;
    sharpe: MetricValue;
    sortino: MetricValue;
    calmar: MetricValue;
  };
  observations: [Observation, Observation, Observation, Observation, ...Observation[]];
  tPlusOne: TPlusOneResults;
}

export interface BacktestRegressionArtifact {
  schemaVersion: "backtest-regression-run-v1";
  canonicalizationVersion: "backtest-regression-c14n-v1";
  suiteId: SafeId;
  runId: SafeId;
  fixtureId: SafeId;
  trust: RegressionTrust;
  manifest: RegressionManifest;
  inputs: RegressionInputs;
  provenance: RegressionProvenance;
  versions: RegressionVersions;
  results: RegressionResults;
  artifactSha256: Sha256;
}

export interface BaselineApproval {
  approvalId: SafeId;
  reviewedBy: string;
  reviewedAt: Timestamp;
  reviewedArtifactSha256: Sha256;
  changeReference: DigestReference;
  reason: string;
  evidenceRefs: DigestReference[];
}

export interface BacktestRegressionBaseline {
  schemaVersion: "backtest-regression-baseline-v1";
  baselineId: SafeId;
  suiteId: SafeId;
  expectedArtifact: BacktestRegressionArtifact;
  expectedArtifactSha256: string;
  approval: BaselineApproval;
}

export interface BacktestRegressionDiff {
  category: "SCHEMA" | "MANIFEST_INPUT" | "ALGORITHM_CONFIG" | "DEPENDENCY_TOOLCHAIN" | "RESULT";
  pointer: string;
  status: "ADDED" | "REMOVED" | "REPLACED";
  baselineValue: unknown;
  candidateValue: unknown;
}

export interface BacktestRegressionComparison {
  baselineSha256: Sha256;
  candidateSha256: Sha256;
  status: "MATCHED" | "DRIFTED";
  categoryCounts: {
    SCHEMA: number;
    MANIFEST_INPUT: number;
    ALGORITHM_CONFIG: number;
    DEPENDENCY_TOOLCHAIN: number;
    RESULT: number;
  };
  diffs: BacktestRegressionDiff[];
  diffLines: string[];
}

export interface BacktestRegressionRunSummary {
  schemaVersion: "backtest-regression-summary-v1";
  suiteId: SafeId;
  runId: SafeId;
  fixtureId: SafeId;
  status: "MATCHED" | "DRIFTED";
  candidateSha256: Sha256;
  baselineSha256: Sha256;
  dataStart: Timestamp;
  dataEnd: Timestamp;
  availability: string;
  evidenceIntegrityConfidence: "LOW" | "MEDIUM" | "HIGH";
  preview: boolean;
}

const SHA256 = /^[0-9a-f]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/;
const DECIMAL = /^(?:0|-?(?:0\.[0-9]*[1-9]|[1-9][0-9]*(?:\.[0-9]*[1-9])?))$/;
export const REGRESSION_DIFF_CATEGORIES = [
  "SCHEMA",
  "MANIFEST_INPUT",
  "ALGORITHM_CONFIG",
  "DEPENDENCY_TOOLCHAIN",
  "RESULT",
] as const;
const ROOT_PYPROJECT_ENTRY = "root-pyproject.toml";
const SERVICE_PYPROJECT_ENTRY = "quant-engine-pyproject.toml";
const UV_LOCK_ENTRY = "uv.lock";

function canonicalValue(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    if (typeof value === "string" && value.includes("\r"))
      throw new TypeError("canonical JSON must not contain CR");
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value) || !Number.isInteger(value))
      throw new TypeError("canonical JSON must not contain floats");
    return value;
  }
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value !== null && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort(compareAscii)) {
      if ([...key].some((character) => character.charCodeAt(0) > 0x7f)) {
        throw new TypeError("canonical JSON object keys must be ASCII");
      }
      result[key] = canonicalValue((value as Record<string, unknown>)[key]);
    }
    return result;
  }
  throw new TypeError("canonical JSON contains an unsupported value");
}

export function canonicalJson(value: unknown): string {
  const rendered = JSON.stringify(canonicalValue(value));
  if (rendered === undefined) throw new TypeError("canonical JSON cannot be undefined");
  return `${rendered}\n`;
}

export function sha256Json(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function assertNoDuplicateJsonKeys(raw: string): void {
  let index = 0;
  const fail = (): never => {
    throw new TypeError("JSON contains invalid structure or duplicate keys");
  };
  const whitespace = (): void => {
    while (index < raw.length && /\s/.test(raw[index] ?? "")) index += 1;
  };
  const string = (): string => {
    if (raw[index] !== '"') return fail();
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
        if (typeof parsed !== "string") return fail();
        return parsed;
      }
    }
    return fail();
  };
  const value = (): void => {
    whitespace();
    const character = raw[index];
    if (character === '"') {
      string();
      return;
    }
    if (character === "{") {
      index += 1;
      whitespace();
      const keys = new Set<string>();
      if (raw[index] === "}") {
        index += 1;
        return;
      }
      while (index < raw.length) {
        whitespace();
        const key = string();
        if (keys.has(key)) return fail();
        keys.add(key);
        whitespace();
        if (raw[index] !== ":") return fail();
        index += 1;
        value();
        whitespace();
        if (raw[index] === "}") {
          index += 1;
          return;
        }
        if (raw[index] !== ",") return fail();
        index += 1;
      }
      return fail();
    }
    if (character === "[") {
      index += 1;
      whitespace();
      if (raw[index] === "]") {
        index += 1;
        return;
      }
      while (index < raw.length) {
        value();
        whitespace();
        if (raw[index] === "]") {
          index += 1;
          return;
        }
        if (raw[index] !== ",") return fail();
        index += 1;
      }
      return fail();
    }
    const start = index;
    while (index < raw.length && !/[\s,\]}]/.test(raw[index] ?? "")) index += 1;
    if (start === index) return fail();
    try {
      JSON.parse(raw.slice(start, index));
    } catch {
      return fail();
    }
  };
  value();
  whitespace();
  if (index !== raw.length) fail();
}

export function parseCanonicalJson(raw: string): Record<string, unknown> {
  if (raw.charCodeAt(0) === 0xfeff || raw.includes("\r"))
    throw new TypeError("JSON encoding is invalid");
  assertNoDuplicateJsonKeys(raw);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    throw new TypeError("JSON is malformed");
  }
  if (canonicalJson(parsed) !== raw) throw new TypeError("JSON is not canonical");
  return record(parsed, "JSON");
}

function record(value: unknown, field: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${field} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exact(value: unknown, keys: readonly string[], field: string): Record<string, unknown> {
  const item = record(value, field);
  const expected = new Set(keys);
  for (const key of Object.keys(item)) {
    if (!expected.has(key)) throw new TypeError(`${field} contains unknown key ${key}`);
  }
  for (const key of keys) {
    if (!(key in item)) throw new TypeError(`${field} is missing key ${key}`);
  }
  return item;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) throw new TypeError(`${field} must be text`);
  return value;
}

function safeId(value: unknown, field: string): string {
  const candidate = text(value, field);
  if (!SAFE_ID.test(candidate) || candidate.includes("..") || /\s|\0/.test(candidate)) {
    throw new TypeError(`${field} is not a safe id`);
  }
  return candidate;
}

function sha(value: unknown, field: string): string {
  const candidate = text(value, field);
  if (!SHA256.test(candidate)) throw new TypeError(`${field} must be lowercase SHA-256`);
  return candidate;
}

function timestamp(value: unknown, field: string): string {
  const candidate = text(value, field);
  if (!TIMESTAMP.test(candidate) || Number.isNaN(Date.parse(candidate))) {
    throw new TypeError(`${field} must be UTC RFC3339 with six fractional digits`);
  }
  return candidate;
}

function decimal(value: unknown, field: string): string {
  const candidate = text(value, field);
  if (!DECIMAL.test(candidate) || (candidate.startsWith("-0") && /^-0(?:\.0+)?$/.test(candidate))) {
    throw new TypeError(`${field} must be a canonical Decimal string`);
  }
  const [integer, fraction] = candidate.replace(/^-/, "").split(".");
  const normalized =
    `${candidate.startsWith("-") ? "-" : ""}${integer}${fraction === undefined ? "" : `.${fraction.replace(/0+$/, "")}`}`.replace(
      /\.$/,
      "",
    );
  if (normalized !== candidate) throw new TypeError(`${field} must use canonical Decimal spelling`);
  return candidate;
}

export function parseCanonicalDecimal(value: unknown): string {
  return decimal(value, "Decimal");
}

function compareAscii(left: string, right: string): number {
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left.charCodeAt(index) !== right.charCodeAt(index)) {
      return left.charCodeAt(index) - right.charCodeAt(index);
    }
  }
  return left.length - right.length;
}

export function toolchainEvidenceSha256(
  toolchain: Omit<ToolchainEvidence, "evidenceSha256">,
): string {
  return sha256Json({
    hatchling: toolchain.hatchling,
    python: toolchain.python,
    rootPyprojectSha256: toolchain.rootPyprojectSha256,
    servicePyprojectSha256: toolchain.servicePyprojectSha256,
    uv: toolchain.uv,
    uvLockSha256: toolchain.uvLockSha256,
  });
}

function digestReference(value: unknown, field: string): DigestReference {
  const item = record(value, field);
  if (item.kind === "CONTENT_SHA256") {
    const result = exact(item, ["kind", "sha256"], field);
    return { kind: "CONTENT_SHA256", sha256: sha(result.sha256, `${field}.sha256`) };
  }
  if (item.kind === "OPAQUE_EXTERNAL") {
    const result = exact(item, ["kind", "namespace", "value"], field);
    return {
      kind: "OPAQUE_EXTERNAL",
      namespace: text(result.namespace, `${field}.namespace`),
      value: text(result.value, `${field}.value`),
    };
  }
  throw new TypeError(`${field}.kind is unsupported`);
}

function observations(value: unknown, field: string, valueKey: string): void {
  if (!Array.isArray(value) || value.length < 4)
    throw new TypeError(`${field} must contain at least four observations`);
  let previous: string | undefined;
  value.forEach((raw, index) => {
    const item = exact(
      raw,
      ["observationTime", valueKey, "provenanceDigest"],
      `${field}[${index}]`,
    );
    const current = timestamp(item.observationTime, `${field}[${index}].observationTime`);
    if (previous !== undefined && current <= previous)
      throw new TypeError(`${field} must be ordered`);
    previous = current;
    decimal(item[valueKey], `${field}[${index}].${valueKey}`);
    sha(item.provenanceDigest, `${field}[${index}].provenanceDigest`);
  });
}

function tPlusOneInputs(value: unknown, field: string): TPlusOneInputs {
  const item = exact(
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
  safeId(item.buyOrderId, `${field}.buyOrderId`);
  safeId(item.sellOrderId, `${field}.sellOrderId`);
  for (const key of [
    "buyExecutionInputDigest",
    "sameDaySellExecutionInputDigest",
    "nextDaySellExecutionInputDigest",
    "sameDaySellabilityDigest",
    "nextDaySellabilityDigest",
    "sameDayBatchDigest",
    "nextDayBatchDigest",
  ] as const) {
    sha(item[key], `${field}.${key}`);
  }
  return {
    buyOrderId: safeId(item.buyOrderId, `${field}.buyOrderId`),
    sellOrderId: safeId(item.sellOrderId, `${field}.sellOrderId`),
    buyExecutionInputDigest: sha(item.buyExecutionInputDigest, `${field}.buyExecutionInputDigest`),
    sameDaySellExecutionInputDigest: sha(
      item.sameDaySellExecutionInputDigest,
      `${field}.sameDaySellExecutionInputDigest`,
    ),
    nextDaySellExecutionInputDigest: sha(
      item.nextDaySellExecutionInputDigest,
      `${field}.nextDaySellExecutionInputDigest`,
    ),
    sameDaySellabilityDigest: sha(
      item.sameDaySellabilityDigest,
      `${field}.sameDaySellabilityDigest`,
    ),
    nextDaySellabilityDigest: sha(
      item.nextDaySellabilityDigest,
      `${field}.nextDaySellabilityDigest`,
    ),
    sameDayBatchDigest: sha(item.sameDayBatchDigest, `${field}.sameDayBatchDigest`),
    nextDayBatchDigest: sha(item.nextDayBatchDigest, `${field}.nextDayBatchDigest`),
  };
}

function tPlusOneObservation(value: unknown, field: string): TPlusOneObservation {
  const item = exact(
    value,
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
    field,
  );
  safeId(item.orderId, `${field}.orderId`);
  if (item.status !== "REJECTED" && item.status !== "FILLED")
    throw new TypeError(`${field}.status is unsupported`);
  if (item.rejectReason !== null) text(item.rejectReason, `${field}.rejectReason`);
  if (typeof item.fillCount !== "number" || !Number.isInteger(item.fillCount) || item.fillCount < 0)
    throw new TypeError(`${field}.fillCount is invalid`);
  sha(item.batchDigest, `${field}.batchDigest`);
  sha(item.resultDigest, `${field}.resultDigest`);
  const tradingDate = text(item.tradingDate, `${field}.tradingDate`);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(tradingDate) ||
    Number.isNaN(Date.parse(`${tradingDate}T00:00:00Z`))
  )
    throw new TypeError(`${field}.tradingDate is invalid`);
  if (item.sellabilityDigest !== null) sha(item.sellabilityDigest, `${field}.sellabilityDigest`);
  if (item.status === "REJECTED" && item.rejectReason === null)
    throw new TypeError(`${field}.rejectReason is required for rejected orders`);
  if (item.status === "FILLED" && item.rejectReason !== null)
    throw new TypeError(`${field}.rejectReason must be null for filled orders`);
  return {
    orderId: safeId(item.orderId, `${field}.orderId`),
    status: item.status,
    rejectReason:
      item.rejectReason === null ? null : text(item.rejectReason, `${field}.rejectReason`),
    fillCount: item.fillCount,
    batchDigest: sha(item.batchDigest, `${field}.batchDigest`),
    resultDigest: sha(item.resultDigest, `${field}.resultDigest`),
    tradingDate,
    sellabilityDigest:
      item.sellabilityDigest === null
        ? null
        : sha(item.sellabilityDigest, `${field}.sellabilityDigest`),
  };
}

function tPlusOneResults(value: unknown, field: string): TPlusOneResults {
  const item = exact(value, ["sameDay", "nextDay"], field);
  const sameDay = tPlusOneObservation(item.sameDay, `${field}.sameDay`);
  const nextDay = tPlusOneObservation(item.nextDay, `${field}.nextDay`);
  if (sameDay.status !== "REJECTED" || sameDay.rejectReason !== "T_PLUS_ONE_NOT_SELLABLE")
    throw new TypeError(`${field}.sameDay must record the T+1 rejection`);
  if (nextDay.status !== "FILLED" || nextDay.fillCount < 1)
    throw new TypeError(`${field}.nextDay must record a fill`);
  return { sameDay, nextDay };
}

function artifact(input: unknown): BacktestRegressionArtifact {
  const item = exact(
    input,
    [
      "schemaVersion",
      "canonicalizationVersion",
      "suiteId",
      "runId",
      "fixtureId",
      "trust",
      "manifest",
      "inputs",
      "provenance",
      "versions",
      "results",
      "artifactSha256",
    ],
    "artifact",
  );
  if (item.schemaVersion !== "backtest-regression-run-v1")
    throw new TypeError("unsupported artifact schema");
  if (item.canonicalizationVersion !== "backtest-regression-c14n-v1")
    throw new TypeError("unsupported canonicalization");
  safeId(item.suiteId, "artifact.suiteId");
  safeId(item.runId, "artifact.runId");
  safeId(item.fixtureId, "artifact.fixtureId");
  const trust = exact(
    item.trust,
    ["mode", "evidenceIntegrityConfidence", "evidenceRefs"],
    "artifact.trust",
  );
  if (trust.mode !== "FIXTURE_SELF_CONTAINED" && trust.mode !== "VERIFIED")
    throw new TypeError("unsupported trust mode");
  if (
    trust.evidenceIntegrityConfidence !== "LOW" &&
    trust.evidenceIntegrityConfidence !== "MEDIUM" &&
    trust.evidenceIntegrityConfidence !== "HIGH"
  )
    throw new TypeError("unsupported evidence confidence");
  if (!Array.isArray(trust.evidenceRefs))
    throw new TypeError("artifact.trust.evidenceRefs must be an array");
  trust.evidenceRefs.forEach((ref, index) =>
    digestReference(ref, `artifact.trust.evidenceRefs[${index}]`),
  );
  const manifest = exact(item.manifest, ["json", "sha256"], "artifact.manifest");
  record(manifest.json, "artifact.manifest.json");
  sha(manifest.sha256, "artifact.manifest.sha256");
  if (sha256Json(manifest.json) !== manifest.sha256)
    throw new TypeError("manifest digest mismatch");
  const inputs = exact(
    item.inputs,
    [
      "fixtureSha256",
      "executionInputDigests",
      "portfolioHistoryRef",
      "valuationLineage",
      "navObservations",
      "riskFreeObservations",
      "tPlusOne",
    ],
    "artifact.inputs",
  );
  sha(inputs.fixtureSha256, "artifact.inputs.fixtureSha256");
  if (!Array.isArray(inputs.executionInputDigests))
    throw new TypeError("executionInputDigests must be an array");
  inputs.executionInputDigests.forEach((digestValue, index) =>
    sha(digestValue, `executionInputDigests[${index}]`),
  );
  observations(inputs.navObservations, "artifact.inputs.navObservations", "nav");
  observations(inputs.riskFreeObservations, "artifact.inputs.riskFreeObservations", "rate");
  tPlusOneInputs(inputs.tPlusOne, "artifact.inputs.tPlusOne");
  const history = exact(
    inputs.portfolioHistoryRef,
    ["tapeId", "eventTapeDigest", "eventCount"],
    "portfolioHistoryRef",
  );
  safeId(history.tapeId, "portfolioHistoryRef.tapeId");
  sha(history.eventTapeDigest, "portfolioHistoryRef.eventTapeDigest");
  if (
    typeof history.eventCount !== "number" ||
    !Number.isInteger(history.eventCount) ||
    history.eventCount < 0
  )
    throw new TypeError("portfolioHistoryRef.eventCount is invalid");
  const lineage = exact(
    inputs.valuationLineage,
    ["valuationPolicyId", "valuationPolicyVersion", "valuationPolicyDigest", "valuations"],
    "valuationLineage",
  );
  text(lineage.valuationPolicyId, "valuationLineage.valuationPolicyId");
  text(lineage.valuationPolicyVersion, "valuationLineage.valuationPolicyVersion");
  sha(lineage.valuationPolicyDigest, "valuationLineage.valuationPolicyDigest");
  if (!Array.isArray(lineage.valuations))
    throw new TypeError("valuationLineage.valuations must be an array");
  lineage.valuations.forEach((raw, index) => {
    const valuation = exact(
      raw,
      ["observationTime", "inputDigest", "markDigest", "stateDigest", "nav"],
      `valuations[${index}]`,
    );
    timestamp(valuation.observationTime, `valuations[${index}].observationTime`);
    sha(valuation.inputDigest, `valuations[${index}].inputDigest`);
    sha(valuation.markDigest, `valuations[${index}].markDigest`);
    sha(valuation.stateDigest, `valuations[${index}].stateDigest`);
    decimal(valuation.nav, `valuations[${index}].nav`);
  });
  const provenance = exact(
    item.provenance,
    ["code", "config", "dependencies", "toolchain"],
    "artifact.provenance",
  );
  const code = exact(provenance.code, ["allowlist", "treeSha256"], "artifact.provenance.code");
  if (!Array.isArray(code.allowlist)) throw new TypeError("code.allowlist must be an array");
  code.allowlist.forEach((raw, index) => {
    const entry = exact(raw, ["path", "sha256"], `code.allowlist[${index}]`);
    const path = text(entry.path, `code.allowlist[${index}].path`);
    if (
      path.startsWith("/") ||
      path.includes("\\") ||
      path.includes("://") ||
      path.split("/").some((part) => part === "" || part === "." || part === "..")
    )
      throw new TypeError("code path must be relative");
    sha(entry.sha256, `code.allowlist[${index}].sha256`);
  });
  sha(code.treeSha256, "code.treeSha256");
  for (const name of ["config", "dependencies"] as const) {
    if (!Array.isArray(provenance[name]))
      throw new TypeError(`provenance.${name} must be an array`);
    provenance[name].forEach((raw, index) => {
      const entry = exact(raw, ["name", "version", "sha256"], `${name}[${index}]`);
      text(entry.name, `${name}[${index}].name`);
      text(entry.version, `${name}[${index}].version`);
      sha(entry.sha256, `${name}[${index}].sha256`);
    });
  }
  const toolchain = exact(
    provenance.toolchain,
    [
      "python",
      "uv",
      "evidenceSha256",
      "hatchling",
      "rootPyprojectSha256",
      "servicePyprojectSha256",
      "uvLockSha256",
    ],
    "toolchain",
  );
  if (toolchain.python !== "3.12.13" || toolchain.uv !== "0.12.3")
    throw new TypeError("toolchain pin mismatch");
  if (toolchain.hatchling !== "1.27.0") throw new TypeError("hatchling pin mismatch");
  sha(toolchain.evidenceSha256, "toolchain.evidenceSha256");
  sha(toolchain.rootPyprojectSha256, "toolchain.rootPyprojectSha256");
  sha(toolchain.servicePyprojectSha256, "toolchain.servicePyprojectSha256");
  sha(toolchain.uvLockSha256, "toolchain.uvLockSha256");
  const uniqueEntry = (entries: unknown, name: string, field: string): Record<string, unknown> => {
    if (!Array.isArray(entries)) throw new TypeError(field + " must be an array");
    const matches = entries.filter(
      (entry): entry is Record<string, unknown> =>
        typeof entry === "object" &&
        entry !== null &&
        (entry as Record<string, unknown>).name === name,
    );
    if (matches.length !== 1)
      throw new TypeError(field + " must contain exactly one " + name + " entry");
    const match = matches[0];
    if (match === undefined) throw new TypeError(field + " entry is missing");
    return match;
  };
  const rootEntry = uniqueEntry(
    provenance.config,
    ROOT_PYPROJECT_ENTRY,
    "artifact.provenance.config",
  );
  const serviceEntry = uniqueEntry(
    provenance.config,
    SERVICE_PYPROJECT_ENTRY,
    "artifact.provenance.config",
  );
  const lockEntry = uniqueEntry(
    provenance.dependencies,
    UV_LOCK_ENTRY,
    "artifact.provenance.dependencies",
  );
  if (rootEntry.sha256 !== toolchain.rootPyprojectSha256)
    throw new TypeError("root pyproject digest binding is invalid");
  if (serviceEntry.sha256 !== toolchain.servicePyprojectSha256)
    throw new TypeError("service pyproject digest binding is invalid");
  if (lockEntry.sha256 !== toolchain.uvLockSha256)
    throw new TypeError("uv.lock digest binding is invalid");
  const evidencePayload = {
    python: toolchain.python as "3.12.13",
    uv: toolchain.uv as "0.12.3",
    hatchling: text(toolchain.hatchling, "toolchain.hatchling"),
    rootPyprojectSha256: toolchain.rootPyprojectSha256 as string,
    servicePyprojectSha256: toolchain.servicePyprojectSha256 as string,
    uvLockSha256: toolchain.uvLockSha256 as string,
  };
  if (toolchain.evidenceSha256 !== toolchainEvidenceSha256(evidencePayload)) {
    throw new TypeError("toolchain evidence digest is invalid");
  }
  const versions = record(item.versions, "artifact.versions");
  for (const [key, value] of Object.entries(versions)) text(value, `versions.${key}`);
  const results = exact(
    item.results,
    ["counts", "pnl", "finalNav", "finalValuation", "metrics", "observations", "tPlusOne"],
    "artifact.results",
  );
  const counts = exact(
    results.counts,
    [
      "events",
      "intents",
      "orders",
      "fills",
      "navObservations",
      "tPlusOneRejected",
      "nextDaySellFills",
    ],
    "results.counts",
  );
  for (const [key, value] of Object.entries(counts)) {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0)
      throw new TypeError(`results.counts.${key} is invalid`);
  }
  exact(results.pnl, ["realized", "unrealized", "total", "fees"], "results.pnl");
  const pnl = results.pnl as Record<string, unknown>;
  for (const [key, value] of Object.entries(pnl)) decimal(value, `results.pnl.${key}`);
  decimal(results.finalNav, "results.finalNav");
  const finalValuation = exact(
    results.finalValuation,
    ["cutoffTime", "nav", "totalPnl", "stateDigest", "inputDigest", "sampleCount"],
    "results.finalValuation",
  );
  timestamp(finalValuation.cutoffTime, "results.finalValuation.cutoffTime");
  decimal(finalValuation.nav, "results.finalValuation.nav");
  decimal(finalValuation.totalPnl, "results.finalValuation.totalPnl");
  sha(finalValuation.stateDigest, "results.finalValuation.stateDigest");
  sha(finalValuation.inputDigest, "results.finalValuation.inputDigest");
  if (
    typeof finalValuation.sampleCount !== "number" ||
    !Number.isInteger(finalValuation.sampleCount) ||
    finalValuation.sampleCount < 0
  )
    throw new TypeError("results.finalValuation.sampleCount is invalid");
  const metrics = exact(
    results.metrics,
    [
      "cumulativeChainedReturn",
      "annualizedReturn",
      "annualizedVolatility",
      "maximumDrawdown",
      "sharpe",
      "sortino",
      "calmar",
    ],
    "results.metrics",
  );
  for (const [name, raw] of Object.entries(metrics)) {
    const metric = exact(raw, ["status", "value"], `results.metrics.${name}`);
    text(metric.status, `results.metrics.${name}.status`);
    if (metric.value !== null) decimal(metric.value, `results.metrics.${name}.value`);
  }
  observations(results.observations, "results.observations", "nav");
  const resultTPlusOne = tPlusOneResults(results.tPlusOne, "artifact.results.tPlusOne");
  if (counts.tPlusOneRejected !== 1 || counts.nextDaySellFills !== 1)
    throw new TypeError("results T+1 counts are inconsistent");
  sha(item.artifactSha256, "artifact.artifactSha256");
  const withoutDigest = { ...item };
  delete withoutDigest.artifactSha256;
  if (sha256Json(withoutDigest) !== item.artifactSha256)
    throw new TypeError("artifact digest mismatch");
  return {
    ...item,
    inputs: { ...inputs, tPlusOne: tPlusOneInputs(inputs.tPlusOne, "artifact.inputs.tPlusOne") },
    results: { ...results, counts, tPlusOne: resultTPlusOne },
  } as BacktestRegressionArtifact;
}

export function parseBacktestRegressionArtifact(input: unknown): BacktestRegressionArtifact {
  const parsed = typeof input === "string" ? parseCanonicalJson(input) : input;
  return artifact(parsed);
}

export function parseBacktestRegressionBaseline(input: unknown): BacktestRegressionBaseline {
  const item = exact(
    input,
    [
      "schemaVersion",
      "baselineId",
      "suiteId",
      "expectedArtifact",
      "expectedArtifactSha256",
      "approval",
    ],
    "baseline",
  );
  if (item.schemaVersion !== "backtest-regression-baseline-v1")
    throw new TypeError("unsupported baseline schema");
  safeId(item.baselineId, "baseline.baselineId");
  safeId(item.suiteId, "baseline.suiteId");
  const expectedArtifact = artifact(item.expectedArtifact);
  if (expectedArtifact.suiteId !== item.suiteId) throw new TypeError("baseline suite mismatch");
  if (expectedArtifact.artifactSha256 !== item.expectedArtifactSha256)
    throw new TypeError("baseline artifact digest mismatch");
  const approval = exact(
    item.approval,
    [
      "approvalId",
      "reviewedBy",
      "reviewedAt",
      "reviewedArtifactSha256",
      "changeReference",
      "reason",
      "evidenceRefs",
    ],
    "baseline.approval",
  );
  const approvalId = safeId(approval.approvalId, "approval.approvalId");
  const reviewedBy = text(approval.reviewedBy, "approval.reviewedBy");
  const reviewedAt = timestamp(approval.reviewedAt, "approval.reviewedAt");
  if (approval.reviewedArtifactSha256 !== expectedArtifact.artifactSha256)
    throw new TypeError("approval digest mismatch");
  const changeReference = digestReference(approval.changeReference, "approval.changeReference");
  if (changeReference.kind !== "OPAQUE_EXTERNAL")
    throw new TypeError("approval changeReference must be opaque");
  const reason = text(approval.reason, "approval.reason");
  if (!Array.isArray(approval.evidenceRefs))
    throw new TypeError("approval.evidenceRefs must be an array");
  const evidenceRefs = approval.evidenceRefs.map((ref, index) =>
    digestReference(ref, `approval.evidenceRefs[${index}]`),
  );
  const typedApproval: BaselineApproval = {
    approvalId,
    reviewedBy,
    reviewedAt,
    reviewedArtifactSha256: sha(approval.reviewedArtifactSha256, "approval.reviewedArtifactSha256"),
    changeReference,
    reason,
    evidenceRefs,
  };
  return { ...item, expectedArtifact, approval: typedApproval } as BacktestRegressionBaseline;
}

export function parseBacktestRegressionComparison(input: unknown): BacktestRegressionComparison {
  const item = exact(
    input,
    ["baselineSha256", "candidateSha256", "status", "categoryCounts", "diffs", "diffLines"],
    "comparison",
  );
  const baselineSha256 = sha(item.baselineSha256, "comparison.baselineSha256");
  const candidateSha256 = sha(item.candidateSha256, "comparison.candidateSha256");
  if (item.status !== "MATCHED" && item.status !== "DRIFTED") {
    throw new TypeError("comparison status is unsupported");
  }
  if (!Array.isArray(item.diffs) || !Array.isArray(item.diffLines)) {
    throw new TypeError("comparison arrays are invalid");
  }
  const diffs = item.diffs.map((raw, index): BacktestRegressionDiff => {
    const field = "comparison.diffs[" + index + "]";
    const diff = exact(
      raw,
      ["category", "pointer", "status", "baselineValue", "candidateValue"],
      field,
    );
    const category = text(diff.category, field + ".category");
    if (!(REGRESSION_DIFF_CATEGORIES as readonly string[]).includes(category)) {
      throw new TypeError(field + ".category is unsupported");
    }
    const pointer = text(diff.pointer, field + ".pointer");
    if (
      !pointer.startsWith("/") ||
      [...pointer].some((character) => character.charCodeAt(0) > 0x7f)
    ) {
      throw new TypeError(field + ".pointer must be an ASCII RFC 6901 pointer");
    }
    for (let pointerIndex = 0; pointerIndex < pointer.length; pointerIndex += 1) {
      if (pointer[pointerIndex] === "~") {
        const escape = pointer[pointerIndex + 1];
        if (escape !== "0" && escape !== "1")
          throw new TypeError(field + ".pointer has an invalid escape");
        pointerIndex += 1;
      }
    }
    canonicalValue(diff.baselineValue);
    canonicalValue(diff.candidateValue);
    const status = text(diff.status, field + ".status");
    if (!(["ADDED", "REMOVED", "REPLACED"] as readonly string[]).includes(status)) {
      throw new TypeError(field + ".status is unsupported");
    }
    if (status === "ADDED" && (diff.baselineValue !== null || diff.candidateValue === null)) {
      throw new TypeError(field + ".ADDED value shape is invalid");
    }
    if (status === "REMOVED" && (diff.baselineValue === null || diff.candidateValue !== null)) {
      throw new TypeError(field + ".REMOVED value shape is invalid");
    }
    if (status === "REPLACED" && (diff.baselineValue === null || diff.candidateValue === null)) {
      throw new TypeError(field + ".REPLACED value shape is invalid");
    }
    return {
      category: category as BacktestRegressionDiff["category"],
      pointer,
      status: status as BacktestRegressionDiff["status"],
      baselineValue: diff.baselineValue,
      candidateValue: diff.candidateValue,
    };
  });
  const categoryCountsValue = record(item.categoryCounts, "comparison.categoryCounts");
  if (
    Object.keys(categoryCountsValue).sort(compareAscii).join("\u0000") !==
    [...REGRESSION_DIFF_CATEGORIES].sort(compareAscii).join("\u0000")
  ) {
    throw new TypeError("comparison.categoryCounts must contain exactly the five categories");
  }
  const categoryCounts = {} as BacktestRegressionComparison["categoryCounts"];
  for (const category of REGRESSION_DIFF_CATEGORIES) {
    const value = categoryCountsValue[category];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
      throw new TypeError("comparison.categoryCounts." + category + " is invalid");
    }
    categoryCounts[category] = value;
  }
  const identities = new Set<string>();
  for (const diff of diffs) {
    const identity = diff.category + "\u0000" + diff.pointer;
    if (identities.has(identity))
      throw new TypeError("comparison contains duplicate diff identities");
    identities.add(identity);
  }
  const sortedDiffs = [...diffs].sort((left, right) => {
    const categoryResult =
      REGRESSION_DIFF_CATEGORIES.indexOf(left.category) -
      REGRESSION_DIFF_CATEGORIES.indexOf(right.category);
    return categoryResult || compareAscii(left.pointer, right.pointer);
  });
  if (diffs.some((diff, index) => diff !== sortedDiffs[index])) {
    throw new TypeError("comparison diffs must be sorted by category and ASCII pointer");
  }
  const expectedCounts = {
    SCHEMA: 0,
    MANIFEST_INPUT: 0,
    ALGORITHM_CONFIG: 0,
    DEPENDENCY_TOOLCHAIN: 0,
    RESULT: 0,
  };
  for (const diff of diffs) expectedCounts[diff.category] += 1;
  for (const category of REGRESSION_DIFF_CATEGORIES) {
    if (categoryCounts[category] !== expectedCounts[category]) {
      throw new TypeError("comparison categoryCounts does not match diffs");
    }
  }
  const diffLines = item.diffLines.map((line, index) =>
    text(line, "comparison.diffLines[" + index + "]"),
  );
  const expectedLines = diffs.map((diff) => diff.category + " " + diff.status + " " + diff.pointer);
  if (
    diffLines.length !== expectedLines.length ||
    diffLines.some((line, index) => line !== expectedLines[index])
  ) {
    throw new TypeError("comparison diffLines are not canonical");
  }
  if (
    item.status === "MATCHED" &&
    (diffs.length !== 0 ||
      diffLines.length !== 0 ||
      Object.values(categoryCounts).some((count) => count !== 0))
  ) {
    throw new TypeError("MATCHED comparison must be empty");
  }
  if (item.status === "DRIFTED" && diffs.length === 0) {
    throw new TypeError("DRIFTED comparison must contain diffs");
  }
  return { baselineSha256, candidateSha256, status: item.status, categoryCounts, diffs, diffLines };
}

export function isBacktestRegressionArtifact(input: unknown): input is BacktestRegressionArtifact {
  try {
    parseBacktestRegressionArtifact(input);
    return true;
  } catch {
    return false;
  }
}
