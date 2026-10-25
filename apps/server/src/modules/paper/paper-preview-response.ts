import type {
  PaperAllocationDecision,
  PaperAllocationRejection,
  PaperOrderIntent,
  PaperTargetPosition,
  PaperTerminalSimulationCommand,
} from "@kunlun/shared-types";

type Row = Record<string, unknown>;
type PreviewExpectation = Pick<
  PaperTerminalSimulationCommand,
  "instrumentId" | "price" | "score" | "confidence" | "lotSize"
>;
const HASH = /^[0-9a-f]{64}$/;
const DECIMAL = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
const REASONS = [
  "ACCOUNT_NOT_ACTIVE",
  "CONFLICTING_SIGNALS",
  "LOW_CONFIDENCE",
  "SHORT_NOT_SUPPORTED",
  "MISSING_MARKET_DATA",
  "FUTURE_DATA",
  "MISSING_VALUATION",
  "BOARD_LOT_ROUNDED_TO_ZERO",
  "INSUFFICIENT_CASH",
  "NO_ACTION",
] as const;

/** The existing allocation contract, restricted to this one-scenario preview API. */
export function parsePaperPreviewResponse(
  value: unknown,
  command: PreviewExpectation,
): PaperAllocationDecision {
  const row = record(value, [
    "schemaVersion",
    "decisionId",
    "accountId",
    "decisionTime",
    "accountStateDigest",
    "policyId",
    "policyVersion",
    "policyDigest",
    "targets",
    "intents",
    "rejections",
    "decisionDigest",
    "executionCapability",
    "dataMeaning",
  ]);
  equal(row.schemaVersion, "paper-allocation-decision-v1");
  equal(row.executionCapability, "PAPER_ONLY");
  equal(row.dataMeaning, "INTENT_ONLY_NO_BROKER_PATH");
  equal(row.policyId, "paper-preview-allocation");
  equal(row.policyVersion, "1.0.0");
  const accountId = digest(row.accountId),
    decisionTime = timestamp(row.decisionTime),
    policyDigest = digest(row.policyDigest);
  const targets = list(row.targets).map((item): PaperTargetPosition => {
    const t = record(item, [
      "instrumentId",
      "sourceSignalIds",
      "currentQuantity",
      "targetQuantity",
      "targetWeight",
      "referencePrice",
      "roundingLotSize",
      "explanation",
    ]);
    equal(t.instrumentId, command.instrumentId);
    equal(t.roundingLotSize, command.lotSize);
    const price = decimal(t.referencePrice),
      weight = decimal(t.targetWeight);
    if (
      compare(price, "0") <= 0 ||
      compare(price, command.price) !== 0 ||
      compare(weight, expectedWeight(command)) !== 0 ||
      compare(command.confidence, "0.5") < 0
    )
      fail();
    return {
      instrumentId: command.instrumentId,
      sourceSignalIds: ids(t.sourceSignalIds),
      currentQuantity: integer(t.currentQuantity),
      targetQuantity: integer(t.targetQuantity),
      targetWeight: weight,
      referencePrice: price,
      roundingLotSize: command.lotSize,
      explanation: text(t.explanation),
    };
  });
  const intents = list(row.intents).map((item): PaperOrderIntent => {
    const i = record(item, [
      "schemaVersion",
      "intentId",
      "accountId",
      "sourceSignalIds",
      "instrumentId",
      "decisionTime",
      "side",
      "quantity",
      "referencePrice",
      "targetQuantity",
      "targetWeight",
      "policyId",
      "policyVersion",
      "policyDigest",
      "explanation",
      "brokerExecutable",
      "executionCapability",
    ]);
    equal(i.schemaVersion, "paper-order-intent-v1");
    equal(i.accountId, accountId);
    equal(i.instrumentId, command.instrumentId);
    equal(i.decisionTime, decisionTime);
    equal(i.policyId, row.policyId);
    equal(i.policyVersion, row.policyVersion);
    equal(i.policyDigest, policyDigest);
    equal(i.brokerExecutable, false);
    equal(i.executionCapability, "PAPER_ONLY");
    if (i.side !== "BUY" && i.side !== "SELL") fail();
    return {
      schemaVersion: "paper-order-intent-v1",
      intentId: digest(i.intentId),
      accountId,
      sourceSignalIds: ids(i.sourceSignalIds),
      instrumentId: command.instrumentId,
      decisionTime,
      side: i.side,
      quantity: integer(i.quantity, 1),
      referencePrice: decimal(i.referencePrice),
      targetQuantity: integer(i.targetQuantity),
      targetWeight: decimal(i.targetWeight),
      policyId: "paper-preview-allocation",
      policyVersion: "1.0.0",
      policyDigest,
      explanation: text(i.explanation),
      brokerExecutable: false,
      executionCapability: "PAPER_ONLY",
    };
  });
  const rejections = list(row.rejections).map((item): PaperAllocationRejection => {
    const r = record(item, ["instrumentId", "sourceSignalIds", "reason", "explanation"]);
    equal(r.instrumentId, command.instrumentId);
    const reason = REASONS.find((reason) => reason === r.reason);
    if (reason === undefined) fail();
    const lowConfidence = compare(command.confidence, "0.5") < 0;
    const accountPrecondition = ["ACCOUNT_NOT_ACTIVE", "FUTURE_DATA", "MISSING_VALUATION"].includes(
      reason,
    );
    if (
      (reason === "LOW_CONFIDENCE" && !lowConfidence) ||
      (lowConfidence && reason !== "LOW_CONFIDENCE" && !accountPrecondition)
    )
      fail();
    return {
      instrumentId: command.instrumentId,
      sourceSignalIds: ids(r.sourceSignalIds),
      reason,
      explanation: text(r.explanation),
    };
  });
  if (rejections.length === 1) {
    if (targets.length !== 0 || intents.length !== 0) fail();
  } else {
    const target = targets[0],
      intent = intents[0];
    if (target === undefined || intent === undefined) fail();
    const delta = target.targetQuantity - target.currentQuantity;
    if (
      delta === 0 ||
      intent.quantity !== Math.abs(delta) ||
      intent.side !== (delta > 0 ? "BUY" : "SELL")
    )
      fail();
    if (
      intent.targetQuantity !== target.targetQuantity ||
      compare(intent.targetWeight, target.targetWeight) !== 0 ||
      compare(intent.referencePrice, target.referencePrice) !== 0 ||
      intent.sourceSignalIds[0] !== target.sourceSignalIds[0]
    )
      fail();
    if (delta > 0 && delta % command.lotSize !== 0) fail();
  }
  return {
    schemaVersion: "paper-allocation-decision-v1",
    decisionId: digest(row.decisionId),
    accountId,
    decisionTime,
    accountStateDigest: digest(row.accountStateDigest),
    policyId: "paper-preview-allocation",
    policyVersion: "1.0.0",
    policyDigest,
    targets,
    intents,
    rejections,
    decisionDigest: digest(row.decisionDigest),
    executionCapability: "PAPER_ONLY",
    dataMeaning: "INTENT_ONLY_NO_BROKER_PATH",
  };
}

function fail(): never {
  throw new Error("quant-engine returned an invalid paper preview");
}
function record(value: unknown, keys: string[]): Row {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail();
  const row = value as Row;
  if (Object.keys(row).length !== keys.length || keys.some((k) => !Object.hasOwn(row, k))) fail();
  return row;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 1000) fail();
  return value;
}
function equal(value: unknown, expected: unknown): void {
  if (value !== expected) fail();
}
function digest(value: unknown): string {
  const s = text(value);
  if (!HASH.test(s)) fail();
  return s;
}
function ids(value: unknown): [string] {
  const a = list(value);
  if (a.length !== 1) fail();
  return [digest(a[0])];
}
function list(value: unknown): unknown[] {
  if (!Array.isArray(value) || value.length > 1) fail();
  return value as unknown[];
}
function integer(value: unknown, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) fail();
  return value;
}
function decimal(value: unknown): string {
  const s = text(value);
  if (s.length > 128 || !DECIMAL.test(s)) fail();
  return s;
}
function compare(a: string, b: string): number {
  const [aw = "0", af = ""] = a.split("."),
    [bw = "0", bf = ""] = b.split(".");
  const scale = Math.max(af.length, bf.length);
  const x = BigInt(aw + af.padEnd(scale, "0")),
    y = BigInt(bw + bf.padEnd(scale, "0"));
  return x < y ? -1 : x > y ? 1 : 0;
}

function expectedWeight(command: PreviewExpectation): string {
  const [sw = "0", sf = ""] = command.score.split(".");
  const [cw = "0", cf = ""] = command.confidence.split(".");
  const scale = sf.length + cf.length;
  const digits = (BigInt(sw + sf) * BigInt(cw + cf)).toString().padStart(scale + 1, "0");
  const value = scale === 0 ? digits : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`;
  return compare(value, "0.3") > 0 ? "0.3" : value;
}

export const paperPreviewValidation = {
  record,
  text,
  digest,
  decimal,
  integer,
  compare,
  timestamp,
};
function timestamp(value: unknown): string {
  const s = text(value);
  const m =
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(
      s,
    );
  if (m === null || !Number.isFinite(Date.parse(s))) fail();
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number);
  const calendar = new Date(`${m[1]}-${m[2]}-${m[3]}T00:00:00Z`);
  if (
    calendar.getUTCFullYear() !== year ||
    calendar.getUTCMonth() + 1 !== month ||
    calendar.getUTCDate() !== day ||
    hour === undefined ||
    hour > 23 ||
    minute === undefined ||
    minute > 59 ||
    second === undefined ||
    second > 59 ||
    Number(m[7] ?? 0) > 23 ||
    Number(m[8] ?? 0) > 59
  )
    fail();
  return s;
}
