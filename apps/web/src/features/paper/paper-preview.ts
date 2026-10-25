import type { PaperTerminalSimulationCommand } from "@kunlun/shared-types";

export interface PaperPreviewFormValues {
  instrumentId: string;
  price: string;
  score: string;
  confidence: string;
  lotSize: string;
}
const POSITIVE = /^(?:0\.\d*[1-9]\d*|[1-9]\d*(?:\.\d+)?)$/;
const RATIO = /^(?:0(?:\.\d+)?|1(?:\.0+)?)$/;
const MONEY = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
export function buildPaperPreviewCommand(
  values: PaperPreviewFormValues,
  requestId: string,
): { command: PaperTerminalSimulationCommand; error: null } | { command: null; error: string } {
  const instrumentId = values.instrumentId.trim().toUpperCase();
  if (!/^\d{6}\.(SH|SZ|BJ)$/.test(instrumentId))
    return { command: null, error: "请输入规范证券代码，例如 600519.SH。" };
  if (values.price.length > 32 || !POSITIVE.test(values.price))
    return { command: null, error: "假设参考价须为正十进制数，最多 32 个字符。" };
  if ([values.score, values.confidence].some((v) => v.length > 20 || !RATIO.test(v)))
    return { command: null, error: "信号强度和假设可信度须在 0 到 1 之间。" };
  const lotSize = Number(values.lotSize);
  if (!/^[1-9]\d*$/.test(values.lotSize) || !Number.isSafeInteger(lotSize) || lotSize > 10000)
    return { command: null, error: "整手单位须为 1 到 10000 的整数。" };
  return {
    command: {
      schemaVersion: "paper-terminal-simulation-v1",
      clientRequestId: requestId,
      instrumentId,
      price: values.price,
      score: values.score,
      confidence: values.confidence,
      lotSize,
    },
    error: null,
  };
}

const REJECTIONS = {
  ACCOUNT_NOT_ACTIVE: "账户当前不可用。",
  CONFLICTING_SIGNALS: "存在互相冲突的信号。",
  LOW_CONFIDENCE: "假设可信度低于 0.5。",
  SHORT_NOT_SUPPORTED: "当前试算不支持卖空。",
  MISSING_MARKET_DATA: "缺少参考价格。",
  FUTURE_DATA: "输入晚于试算时点。",
  MISSING_VALUATION: "账本缺少必要估值。",
  BOARD_LOT_ROUNDED_TO_ZERO: "目标变化不足一个整手单位。",
  INSUFFICIENT_CASH: "账面可分配现金不足。",
  NO_ACTION: "当前持仓已等于按整手取整的目标。",
};
export type PaperPreviewDisplay = { time: string; instrumentId: string; policyVersion: string } & (
  | { kind: "rejected"; reason: string }
  | {
      kind: "target";
      current: number;
      target: number;
      quantity: number;
      side: "BUY" | "SELL";
      price: string;
      weight: string;
      notional: string;
    }
);

/** Consume only fields displayed by the browser; the server validates the full contract. */
export function readPaperPreview(
  value: unknown,
  command: PaperTerminalSimulationCommand,
  accountId: string,
): PaperPreviewDisplay {
  const row = record(value);
  if (
    row.schemaVersion !== "paper-allocation-decision-v1" ||
    row.dataMeaning !== "INTENT_ONLY_NO_BROKER_PATH" ||
    row.executionCapability !== "PAPER_ONLY" ||
    row.accountId !== accountId ||
    row.policyId !== "paper-preview-allocation" ||
    row.policyVersion !== "1.0.0"
  )
    fail();
  if (typeof row.decisionTime !== "string" || !Number.isFinite(Date.parse(row.decisionTime)))
    fail();
  const common = {
    time: row.decisionTime,
    instrumentId: command.instrumentId,
    policyVersion: "1.0.0",
  };
  if (!Array.isArray(row.rejections) || !Array.isArray(row.targets) || !Array.isArray(row.intents))
    fail();
  if (row.rejections.length === 1 && row.targets.length === 0 && row.intents.length === 0) {
    const rejection = record(row.rejections[0]);
    if (
      rejection.instrumentId !== command.instrumentId ||
      typeof rejection.reason !== "string" ||
      !Object.hasOwn(REJECTIONS, rejection.reason)
    )
      fail();
    return {
      ...common,
      kind: "rejected",
      reason: REJECTIONS[rejection.reason as keyof typeof REJECTIONS],
    };
  }
  if (row.rejections.length !== 0 || row.targets.length !== 1 || row.intents.length !== 1) fail();
  const t = record(row.targets[0]),
    i = record(row.intents[0]);
  if (
    t.instrumentId !== command.instrumentId ||
    i.instrumentId !== command.instrumentId ||
    i.brokerExecutable !== false ||
    i.executionCapability !== "PAPER_ONLY" ||
    t.roundingLotSize !== command.lotSize
  )
    fail();
  const price = money(t.referencePrice),
    weight = money(t.targetWeight);
  if (
    normal(price) !== normal(command.price) ||
    normal(money(i.referencePrice)) !== normal(price) ||
    greater(weight, "0.3")
  )
    fail();
  const current = count(t.currentQuantity),
    target = count(t.targetQuantity),
    quantity = count(i.quantity);
  const side = target > current ? "BUY" : "SELL";
  if (
    target === current ||
    quantity !== Math.abs(target - current) ||
    i.side !== side ||
    i.targetQuantity !== target
  )
    fail();
  const [whole = "0", fraction = ""] = price.split(".");
  const units = BigInt(whole + fraction) * BigInt(quantity);
  const digits = units.toString().padStart(fraction.length + 1, "0");
  const notional = normal(
    fraction.length === 0
      ? digits
      : digits.slice(0, -fraction.length) + "." + digits.slice(-fraction.length),
  );
  return { ...common, kind: "target", current, target, quantity, side, price, weight, notional };
}
function fail(): never {
  throw new Error("试算响应与当前输入不一致，请重新试算。");
}
function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail();
  return value;
}
function money(value: unknown): string {
  if (typeof value !== "string" || value.length > 128 || !MONEY.test(value)) fail();
  return value;
}
function normal(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}
function greater(a: string, b: string): boolean {
  const [aw = "0", af = ""] = a.split("."),
    [bw = "0", bf = ""] = b.split(".");
  const scale = Math.max(af.length, bf.length);
  return BigInt(aw + af.padEnd(scale, "0")) > BigInt(bw + bf.padEnd(scale, "0"));
}
