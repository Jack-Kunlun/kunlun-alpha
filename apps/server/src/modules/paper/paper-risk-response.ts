import { createHash } from "node:crypto";
import type {
  PaperAllocationDecision,
  PaperRiskDecision,
  PaperRiskCheck,
} from "@kunlun/shared-types";
import { parseSimulation } from "./paper-terminal.validation";
import { parsePaperPreviewResponse, paperPreviewValidation as p } from "./paper-preview-response";

export const PAPER_RISK_CODES = [
  "ACCOUNT_ACTIVE",
  "RISK_ENGINE_READY",
  "EXECUTION_CONNECTED",
  "RECONCILIATION_HEALTHY",
  "ORDER_NOTIONAL_LIMIT",
  "POSITION_WEIGHT_LIMIT",
  "DAILY_TURNOVER_LIMIT",
  "OPEN_ORDER_LIMIT",
  "CASH_AVAILABLE",
  "PAPER_ONLY_BOUNDARY",
] as const;
const LIMITS: Record<string, string> = {
  ORDER_NOTIONAL_LIMIT: "100000000",
  POSITION_WEIGHT_LIMIT: "0.35",
  DAILY_TURNOVER_LIMIT: "1000000000",
  OPEN_ORDER_LIMIT: "20",
  CASH_AVAILABLE: "0",
};
const POLICY = {
  policy_id: "paper-terminal-risk",
  policy_version: "1.0.0",
  maximum_order_notional: "100000000",
  maximum_position_weight: "0.35",
  maximum_daily_turnover: "1000000000",
  maximum_open_orders: 20,
  minimum_cash_buffer: "0",
};

export function parsePaperRiskPreviewRequest(value: unknown): PaperAllocationDecision {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  const row = value as Record<string, unknown>;
  if (!Array.isArray(row.targets) || row.targets.length !== 1) fail();
  const target = row.targets[0];
  if (typeof target !== "object" || target === null || Array.isArray(target)) fail();
  const t = target as Record<string, unknown>;
  const base = parseSimulation({
    schemaVersion: "paper-terminal-simulation-v1",
    clientRequestId: "risk-snapshot-check",
    instrumentId: t.instrumentId,
    price: t.referencePrice,
    score: "0",
    confidence: "1",
    lotSize: t.roundingLotSize,
  });
  const weight = p.decimal(t.targetWeight);
  if (weight.length > 40) fail();
  const allocation = parsePaperPreviewResponse(value, { ...base, score: weight });
  if (
    allocation.intents.length !== 1 ||
    allocation.rejections.length !== 0 ||
    allocation.decisionId !== allocation.decisionDigest
  )
    fail();
  return allocation;
}

export function parsePaperRiskPreviewResponse(
  value: unknown,
  allocation: PaperAllocationDecision,
  controlledBuyEnabled = false,
): PaperRiskDecision {
  const row = p.record(value, [
    "schemaVersion",
    "decisionId",
    "accountId",
    "intentId",
    "decisionTime",
    "allowed",
    "checks",
    "accountStateDigest",
    "executionStateDigest",
    "policyId",
    "policyVersion",
    "policyDigest",
    "executionCapability",
    "dataMeaning",
  ]);
  const intent = allocation.intents[0];
  if (intent === undefined) fail();
  if (
    row.schemaVersion !== "paper-risk-decision-v1" ||
    row.accountId !== allocation.accountId ||
    row.intentId !== intent.intentId ||
    row.accountStateDigest !== allocation.accountStateDigest ||
    row.executionCapability !== "PAPER_ONLY" ||
    row.dataMeaning !== "SERVER_SIDE_RISK_NO_BROKER_PATH" ||
    row.policyId !== "paper-terminal-risk" ||
    row.policyVersion !== "1.0.0" ||
    typeof row.allowed !== "boolean"
  )
    fail();
  const time = p.timestamp(row.decisionTime);
  if (paperInstant(time) < paperInstant(p.timestamp(allocation.decisionTime))) fail();
  const policyDigest = p.digest(row.policyDigest);
  if (policyDigest !== hash(POLICY)) fail();
  if (!Array.isArray(row.checks) || row.checks.length !== PAPER_RISK_CODES.length) fail();
  const seen = new Set<string>();
  const checks: PaperRiskCheck[] = row.checks.map((value: unknown) => {
    const r = p.record(value, ["code", "status", "actual", "limit", "explanation"]);
    const code = PAPER_RISK_CODES.find((c) => c === r.code);
    if (code === undefined || seen.has(code)) fail();
    seen.add(code);
    const actual = p.text(r.actual),
      limit = p.text(r.limit);
    let pass: boolean;
    if (code === "ACCOUNT_ACTIVE") {
      if (!["ACTIVE", "SUSPENDED", "CLOSED"].includes(actual) || limit !== "ACTIVE") fail();
      pass = actual === limit;
    } else if (code === "RISK_ENGINE_READY" || code === "EXECUTION_CONNECTED") {
      if (!["true", "false"].includes(actual) || limit !== "true") fail();
      if (
        code === "EXECUTION_CONNECTED" &&
        actual === "true" &&
        (!controlledBuyEnabled || intent.side !== "BUY")
      )
        fail();
      pass = actual === "true";
    } else if (code === "RECONCILIATION_HEALTHY") {
      if (!["MATCHED", "DRIFTED", "UNAVAILABLE"].includes(actual) || limit !== "MATCHED") fail();
      pass = actual === limit;
    } else if (code === "PAPER_ONLY_BOUNDARY") {
      if (actual !== "PAPER_ONLY" || limit !== "PAPER_ONLY") fail();
      pass = true;
    } else {
      if (limit !== LIMITS[code] || !signedMoney(actual)) fail();
      if (code !== "CASH_AVAILABLE" && actual.startsWith("-")) fail();
      if (code === "OPEN_ORDER_LIMIT" && !/^(0|[1-9]\d*)$/.test(actual)) fail();
      if (
        code === "ORDER_NOTIONAL_LIMIT" &&
        compare(actual, paperNotional(intent.referencePrice, intent.quantity)) !== 0
      )
        fail();
      if (code === "POSITION_WEIGHT_LIMIT" && compare(actual, intent.targetWeight) !== 0) fail();
      if (
        code === "DAILY_TURNOVER_LIMIT" &&
        compare(actual, paperNotional(intent.referencePrice, intent.quantity)) < 0
      )
        fail();
      pass = code === "CASH_AVAILABLE" ? compare(actual, limit) >= 0 : compare(actual, limit) <= 0;
    }
    const status = pass ? "PASS" : "FAIL";
    if (r.status !== status) fail();
    return { code, status, actual, limit, explanation: p.text(r.explanation) };
  });
  const allowed = checks.every((c) => c.status === "PASS");
  if (row.allowed !== allowed) fail();
  const result: PaperRiskDecision = {
    schemaVersion: "paper-risk-decision-v1",
    decisionId: p.digest(row.decisionId),
    accountId: allocation.accountId,
    intentId: intent.intentId,
    decisionTime: time,
    allowed,
    checks,
    accountStateDigest: allocation.accountStateDigest,
    executionStateDigest: p.digest(row.executionStateDigest),
    policyId: "paper-terminal-risk",
    policyVersion: "1.0.0",
    policyDigest,
    executionCapability: "PAPER_ONLY",
    dataMeaning: "SERVER_SIDE_RISK_NO_BROKER_PATH",
  };
  const seed = {
    account_id: result.accountId,
    intent_id: result.intentId,
    decision_time: time,
    account_state_digest: result.accountStateDigest,
    execution_state_digest: result.executionStateDigest,
    policy_digest: policyDigest,
    checks: checks.map((c) => ({ code: c.code, status: c.status, actual: c.actual })),
  };
  if (hash(seed) !== result.decisionId) fail();
  return result;
}
function fail(): never {
  throw new Error("invalid read-only paper risk preview");
}
function signedMoney(value: string): boolean {
  return value.length <= 128 && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
}
function scaled(value: string, scale: number): bigint {
  const [whole = "0", fraction = ""] = value.replace(/^-/, "").split(".");
  return BigInt(whole + fraction.padEnd(scale, "0")) * (value.startsWith("-") ? -1n : 1n);
}
function compare(a: string, b: string): number {
  const scale = Math.max(a.split(".")[1]?.length ?? 0, b.split(".")[1]?.length ?? 0);
  const x = scaled(a, scale),
    y = scaled(b, scale);
  return x < y ? -1 : x > y ? 1 : 0;
}
export function paperNotional(price: string, quantity: number): string {
  const [whole = "0", fraction = ""] = price.split(".");
  const digits = (BigInt(whole + fraction) * BigInt(quantity))
    .toString()
    .padStart(fraction.length + 1, "0");
  return fraction.length === 0
    ? digits
    : digits.slice(0, -fraction.length) + "." + digits.slice(-fraction.length);
}
export function paperInstant(value: string): bigint {
  const fraction = /\.(\d+)(?=Z|[+-])/.exec(value)?.[1] ?? "";
  return (
    BigInt(Date.parse(value.replace(/\.\d+(?=Z|[+-])/, ""))) * 1000000n +
    BigInt(fraction.padEnd(9, "0"))
  );
}
type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
function canonical(value: Json): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value !== null && typeof value === "object")
    return (
      "{" +
      Object.keys(value)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canonical(value[k] ?? null))
        .join(",") +
      "}"
    );
  return JSON.stringify(value);
}
function hash(value: Json): string {
  return createHash("sha256").update(canonical(value)).digest("hex");
}
