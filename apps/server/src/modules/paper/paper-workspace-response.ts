import type {
  PaperTerminalAccount,
  PaperTerminalAllocation,
  PaperTerminalAllocationRejection,
  PaperTerminalAudit,
  PaperTerminalBookDiff,
  PaperTerminalOrder,
  PaperTerminalPosition,
  PaperTerminalReconciliation,
  PaperTerminalRisk,
  PaperTerminalRiskCheck,
  PaperTerminalWorkspace,
} from "@kunlun/shared-types";

type RecordValue = Record<string, unknown>;
type ParsedMoney = { readonly units: bigint; readonly scale: number };
type ParsedInstant = { readonly seconds: bigint; readonly fraction: string };

const DIGEST = /^[0-9a-f]{64}$/;
const INSTRUMENT_ID = /^[0-9]{6}\.(?:SH|SZ|BJ)$/;
const CANONICAL_NON_NEGATIVE_MONEY = /^(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/;
const INSTANT =
  /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|([+-])(\d{2}):(\d{2}))$/;

export class PaperWorkspaceResponseError extends Error {
  constructor() {
    super("quant-engine returned an invalid paper workspace");
    this.name = "PaperWorkspaceResponseError";
  }
}

/** Validates and reconstructs the complete internal API response before it becomes trusted data. */
export function parsePaperWorkspaceResponse(value: unknown): PaperTerminalWorkspace {
  try {
    const input = exactRecord(value, [
      "schemaVersion",
      "status",
      "dataMeaning",
      "executionCapability",
      "persistenceMode",
      "generatedAt",
      "limitations",
      "account",
      "latestAllocation",
      "orders",
      "latestRisk",
      "reconciliation",
      "audit",
    ]);
    const workspace: PaperTerminalWorkspace = {
      schemaVersion: literal(input["schemaVersion"], "paper-terminal-workspace-v1"),
      status: oneOf(input["status"], ["EMPTY", "READY", "DEGRADED", "UNAVAILABLE"]),
      dataMeaning: literal(input["dataMeaning"], "SIMULATION_ONLY_NO_BROKER_PATH"),
      executionCapability: literal(input["executionCapability"], "PAPER_ONLY"),
      persistenceMode: oneOf(input["persistenceMode"], [
        "VOLATILE_IN_MEMORY",
        "DURABLE_COMMAND_JOURNAL",
      ]),
      generatedAt: instant(input["generatedAt"]),
      limitations: nonEmptyArray(input["limitations"], nonEmptyString),
      account: nullable(input["account"], parseAccount),
      latestAllocation: nullable(input["latestAllocation"], parseAllocation),
      orders: array(input["orders"], parseOrder),
      latestRisk: nullable(input["latestRisk"], parseRisk),
      reconciliation: nullable(input["reconciliation"], parseReconciliation),
      audit: parseAudit(input["audit"]),
    };
    validateWorkspaceCoherence(workspace);
    return workspace;
  } catch (error) {
    if (error instanceof PaperWorkspaceResponseError) throw error;
    throw new PaperWorkspaceResponseError();
  }
}

function parseAccount(value: unknown): PaperTerminalAccount {
  const input = exactRecord(value, [
    "accountId",
    "name",
    "status",
    "baseCurrency",
    "initialCapital",
    "cash",
    "nav",
    "dataCutoffTime",
    "eventCount",
    "eventChainDigest",
    "positions",
  ]);
  const initialCapital = money(input["initialCapital"]);
  if (initialCapital === "0") fail();
  return {
    accountId: digest(input["accountId"]),
    name: nonEmptyString(input["name"]),
    status: oneOf(input["status"], ["ACTIVE", "SUSPENDED", "CLOSED"]),
    baseCurrency: literal(input["baseCurrency"], "CNY"),
    initialCapital,
    cash: money(input["cash"]),
    nav: money(input["nav"]),
    dataCutoffTime: instant(input["dataCutoffTime"]),
    eventCount: safeInteger(input["eventCount"], 1),
    eventChainDigest: digest(input["eventChainDigest"]),
    positions: array(input["positions"], parsePosition),
  };
}

function parsePosition(value: unknown): PaperTerminalPosition {
  const input = exactRecord(value, [
    "instrumentId",
    "quantity",
    "availableQuantity",
    "costAmount",
    "marketValue",
  ]);
  const instrumentId = string(input["instrumentId"]);
  if (!INSTRUMENT_ID.test(instrumentId)) fail();
  const quantity = safeInteger(input["quantity"], 1);
  const availableQuantity = safeInteger(input["availableQuantity"], 0);
  const costAmount = money(input["costAmount"]);
  const marketValue = money(input["marketValue"]);
  if (availableQuantity > quantity) fail();
  return { instrumentId, quantity, availableQuantity, costAmount, marketValue };
}

function parseAllocation(value: unknown): PaperTerminalAllocation {
  const input = exactRecord(value, [
    "decisionId",
    "policyId",
    "policyVersion",
    "intentCount",
    "rejectionCount",
    "rejections",
  ]);
  const rejections = array(input["rejections"], parseAllocationRejection);
  const rejectionCount = safeInteger(input["rejectionCount"], 0);
  if (rejectionCount !== rejections.length) fail();
  return {
    decisionId: digest(input["decisionId"]),
    policyId: nonEmptyString(input["policyId"]),
    policyVersion: nonEmptyString(input["policyVersion"]),
    intentCount: safeInteger(input["intentCount"], 0),
    rejectionCount,
    rejections,
  };
}

function parseAllocationRejection(value: unknown): PaperTerminalAllocationRejection {
  const input = exactRecord(value, ["instrumentId", "reason", "explanation"]);
  return {
    instrumentId: nonEmptyString(input["instrumentId"]),
    reason: nonEmptyString(input["reason"]),
    explanation: nonEmptyString(input["explanation"]),
  };
}

function parseOrder(value: unknown): PaperTerminalOrder {
  const input = exactRecord(value, [
    "orderId",
    "instrumentId",
    "side",
    "status",
    "quantity",
    "filledQuantity",
    "averageFillPrice",
    "totalFees",
    "explanation",
    "updatedAt",
  ]);
  const instrumentId = string(input["instrumentId"]);
  if (!INSTRUMENT_ID.test(instrumentId)) fail();
  const quantity = safeInteger(input["quantity"], 1);
  const filledQuantity = safeInteger(input["filledQuantity"], 0);
  const averageFillPrice = nullable(input["averageFillPrice"], money);
  if (filledQuantity > quantity || (filledQuantity === 0) !== (averageFillPrice === null)) fail();
  if (averageFillPrice === "0") fail();
  return {
    orderId: digest(input["orderId"]),
    instrumentId,
    side: oneOf(input["side"], ["BUY", "SELL"]),
    status: oneOf(input["status"], [
      "CREATED",
      "CHECKED",
      "SUBMITTED",
      "PARTIALLY_FILLED",
      "CANCEL_PENDING",
      "FILLED",
      "CANCELLED",
      "REJECTED",
    ]),
    quantity,
    filledQuantity,
    averageFillPrice,
    totalFees: money(input["totalFees"]),
    explanation: nonEmptyString(input["explanation"]),
    updatedAt: instant(input["updatedAt"]),
  };
}

function parseRisk(value: unknown): PaperTerminalRisk {
  const input = exactRecord(value, [
    "decisionId",
    "allowed",
    "policyId",
    "policyVersion",
    "checks",
  ]);
  return {
    decisionId: digest(input["decisionId"]),
    allowed: boolean(input["allowed"]),
    policyId: nonEmptyString(input["policyId"]),
    policyVersion: nonEmptyString(input["policyVersion"]),
    checks: nonEmptyArray(input["checks"], parseRiskCheck),
  };
}

function parseRiskCheck(value: unknown): PaperTerminalRiskCheck {
  const input = exactRecord(value, ["code", "status", "actual", "limit", "explanation"]);
  return {
    code: nonEmptyString(input["code"]),
    status: oneOf(input["status"], ["PASS", "FAIL"]),
    actual: string(input["actual"]),
    limit: nullable(input["limit"], string),
    explanation: nonEmptyString(input["explanation"]),
  };
}

function parseReconciliation(value: unknown): PaperTerminalReconciliation {
  const input = exactRecord(value, [
    "reconciliationId",
    "status",
    "asOf",
    "duplicateFillCount",
    "diffs",
  ]);
  return {
    reconciliationId: digest(input["reconciliationId"]),
    status: oneOf(input["status"], ["MATCHED", "DRIFTED"]),
    asOf: instant(input["asOf"]),
    duplicateFillCount: safeInteger(input["duplicateFillCount"], 0),
    diffs: array(input["diffs"], parseBookDiff),
  };
}

function parseBookDiff(value: unknown): PaperTerminalBookDiff {
  const input = exactRecord(value, ["kind", "instrumentId", "expected", "observed", "difference"]);
  const instrumentId = nullable(input["instrumentId"], string);
  return {
    kind: nonEmptyString(input["kind"]),
    instrumentId,
    expected: string(input["expected"]),
    observed: string(input["observed"]),
    difference: string(input["difference"]),
  };
}

function parseAudit(value: unknown): PaperTerminalAudit {
  const input = exactRecord(value, [
    "accountEventCount",
    "executionEventCount",
    "orderAuditCount",
    "alertCount",
    "accountDigest",
    "executionDigest",
    "lastClientRequestId",
  ]);
  return {
    accountEventCount: safeInteger(input["accountEventCount"], 0),
    executionEventCount: safeInteger(input["executionEventCount"], 0),
    orderAuditCount: safeInteger(input["orderAuditCount"], 0),
    alertCount: safeInteger(input["alertCount"], 0),
    accountDigest: nullable(input["accountDigest"], digest),
    executionDigest: nullable(input["executionDigest"], digest),
    lastClientRequestId: nullable(input["lastClientRequestId"], string),
  };
}

function validateWorkspaceCoherence(workspace: PaperTerminalWorkspace): void {
  const { account, audit } = workspace;
  if (account === null) {
    if (workspace.status !== "EMPTY" && workspace.status !== "UNAVAILABLE") fail();
    if (
      workspace.latestAllocation !== null ||
      workspace.orders.length !== 0 ||
      workspace.latestRisk !== null ||
      workspace.reconciliation !== null ||
      audit.accountEventCount !== 0 ||
      audit.executionEventCount !== 0 ||
      audit.orderAuditCount !== 0 ||
      audit.alertCount !== 0 ||
      audit.accountDigest !== null ||
      audit.executionDigest !== null ||
      audit.lastClientRequestId !== null
    ) {
      fail();
    }
    return;
  }

  if (workspace.status !== "READY" && workspace.status !== "DEGRADED") fail();
  if (audit.accountEventCount !== account.eventCount || audit.accountDigest === null) fail();
  if (audit.executionDigest === null || audit.lastClientRequestId === null) fail();
  if (compareInstants(account.dataCutoffTime, workspace.generatedAt) > 0) fail();

  const positionIds = new Set(account.positions.map((position) => position.instrumentId));
  if (positionIds.size !== account.positions.length) fail();
  if (!accountBalancesToNav(account)) fail();

  const isDegraded =
    audit.alertCount > 0 ||
    workspace.latestRisk?.allowed === false ||
    workspace.reconciliation?.status === "DRIFTED";
  if (workspace.status === "READY" && isDegraded) fail();
  if (workspace.status === "DEGRADED" && !isDegraded) fail();
}

function accountBalancesToNav(account: PaperTerminalAccount): boolean {
  const nav = moneyParts(account.nav);
  const amounts = [
    moneyParts(account.cash),
    ...account.positions.map((position) => moneyParts(position.marketValue)),
  ];
  const scale = Math.max(nav.scale, ...amounts.map((amount) => amount.scale));
  const total = amounts.reduce(
    (sum, amount) => sum + amount.units * powerOfTen(scale - amount.scale),
    0n,
  );
  return total === nav.units * powerOfTen(scale - nav.scale);
}

function moneyParts(value: string): ParsedMoney {
  const [whole = "", fraction] = value.split(".");
  const decimal = fraction ?? "";
  return { units: BigInt(`${whole}${decimal}`), scale: decimal.length };
}

function powerOfTen(exponent: number): bigint {
  return 10n ** BigInt(exponent);
}

function compareInstants(left: string, right: string): number {
  const leftInstant = parseInstant(left);
  const rightInstant = parseInstant(right);
  if (leftInstant.seconds < rightInstant.seconds) return -1;
  if (leftInstant.seconds > rightInstant.seconds) return 1;
  const scale = Math.max(leftInstant.fraction.length, rightInstant.fraction.length);
  for (let index = 0; index < scale; index += 1) {
    const leftDigit = leftInstant.fraction[index] ?? "0";
    const rightDigit = rightInstant.fraction[index] ?? "0";
    if (leftDigit < rightDigit) return -1;
    if (leftDigit > rightDigit) return 1;
  }
  return 0;
}

function parseInstant(value: string): ParsedInstant {
  const match = INSTANT.exec(value);
  if (!match) fail();
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const fraction = match[7] ?? "";
  if (
    year < 1 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth(year, month) ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    fail();
  }

  let offsetMinutes = 0;
  if (match[8]?.toUpperCase() !== "Z") {
    const offsetHours = Number(match[10]);
    const offsetMinutePart = Number(match[11]);
    if (offsetHours > 23 || offsetMinutePart > 59) fail();
    const direction = match[9] === "+" ? 1 : -1;
    offsetMinutes = direction * (offsetHours * 60 + offsetMinutePart);
  }
  const localSeconds =
    daysFromCivil(year, month, day) * 86_400 + hour * 3_600 + minute * 60 + second;
  return {
    seconds: BigInt(localSeconds - offsetMinutes * 60),
    fraction,
  };
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  return month === 4 || month === 6 || month === 9 || month === 11 ? 30 : 31;
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysFromCivil(year: number, month: number, day: number): number {
  const adjustedYear = year - (month <= 2 ? 1 : 0);
  const era = Math.floor(adjustedYear / 400);
  const yearOfEra = adjustedYear - era * 400;
  const adjustedMonth = month + (month > 2 ? -3 : 9);
  const dayOfYear = Math.floor((153 * adjustedMonth + 2) / 5) + day - 1;
  const dayOfEra =
    yearOfEra * 365 + Math.floor(yearOfEra / 4) - Math.floor(yearOfEra / 100) + dayOfYear;
  return era * 146_097 + dayOfEra - 719_468;
}

function exactRecord(value: unknown, keys: readonly string[]): RecordValue {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  const record: RecordValue = value as RecordValue;
  const expected = new Set(keys);
  if (
    Object.keys(record).length !== expected.size ||
    Object.keys(record).some((key) => !expected.has(key))
  ) {
    fail();
  }
  return record;
}

function array<T>(value: unknown, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value)) fail();
  const items: readonly unknown[] = value;
  return items.map(parse);
}

function nonEmptyArray<T>(value: unknown, parse: (item: unknown) => T): [T, ...T[]] {
  const items = array(value, parse);
  const [first, ...rest] = items;
  if (first === undefined) fail();
  return [first, ...rest];
}

function nullable<T>(value: unknown, parse: (item: unknown) => T): T | null {
  return value === null ? null : parse(value);
}

function literal<T extends string>(value: unknown, expected: T): T {
  if (value !== expected) fail();
  return expected;
}

function oneOf<const T extends readonly string[]>(value: unknown, allowed: T): T[number] {
  if (typeof value !== "string" || !allowed.some((candidate) => candidate === value)) fail();
  return value as T[number];
}

function string(value: unknown): string {
  if (typeof value !== "string") fail();
  return value;
}

function nonEmptyString(value: unknown): string {
  const result = string(value);
  if (result.length === 0) fail();
  return result;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") fail();
  return value;
}

function digest(value: unknown): string {
  const result = string(value);
  if (!DIGEST.test(result)) fail();
  return result;
}

function money(value: unknown): string {
  const result = string(value);
  if (!CANONICAL_NON_NEGATIVE_MONEY.test(result)) fail();
  return result;
}

function safeInteger(value: unknown, minimum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) fail();
  return value;
}

function instant(value: unknown): string {
  const result = string(value);
  parseInstant(result);
  return result;
}

function fail(): never {
  throw new PaperWorkspaceResponseError();
}
