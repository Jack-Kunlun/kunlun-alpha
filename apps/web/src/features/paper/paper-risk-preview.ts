export interface PaperRiskContext {
  allocation: unknown;
  accountId: string;
  intentId: string;
  accountStateDigest: string;
  decisionTime: string;
}
export interface PaperRiskView {
  time: string;
  policyVersion: string;
  rows: Array<{ code: string; name: string; passed: boolean; actual: string; limit: string }>;
}
const NAMES = {
  ACCOUNT_ACTIVE: "账户状态",
  RISK_ENGINE_READY: "风险检查引擎",
  EXECUTION_CONNECTED: "模拟执行入口",
  RECONCILIATION_HEALTHY: "本次账簿核对",
  ORDER_NOTIONAL_LIMIT: "单笔假设金额（CNY）",
  POSITION_WEIGHT_LIMIT: "目标集中度比例",
  DAILY_TURNOVER_LIMIT: "当日累计假设金额（CNY）",
  OPEN_ORDER_LIMIT: "活动模拟订单数",
  CASH_AVAILABLE: "试算后账面现金（CNY，未含费用）",
  PAPER_ONLY_BOUNDARY: "仅模拟边界",
};
function fail(): never {
  throw new Error("风险检查结果与当前试算不一致，请重试。");
}
function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) fail();
  return value;
}
function time(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) fail();
  return value;
}
/** Keep the complete server snapshot opaque; neither the form nor the UI rebuilds it. */
export function capturePaperRiskContext(value: unknown): PaperRiskContext {
  const row = record(value);
  if (
    row.schemaVersion !== "paper-allocation-decision-v1" ||
    row.dataMeaning !== "INTENT_ONLY_NO_BROKER_PATH" ||
    row.executionCapability !== "PAPER_ONLY" ||
    !Array.isArray(row.intents) ||
    row.intents.length !== 1 ||
    !Array.isArray(row.targets) ||
    row.targets.length !== 1 ||
    !Array.isArray(row.rejections) ||
    row.rejections.length !== 0
  )
    fail();
  const intent = record(row.intents[0]);
  const accountId = digest(row.accountId),
    decisionTime = time(row.decisionTime);
  if (
    intent.accountId !== accountId ||
    intent.decisionTime !== decisionTime ||
    intent.brokerExecutable !== false ||
    intent.executionCapability !== "PAPER_ONLY"
  )
    fail();
  return {
    allocation: value,
    accountId,
    decisionTime,
    intentId: digest(intent.intentId),
    accountStateDigest: digest(row.accountStateDigest),
  };
}
function display(code: string, value: unknown): string {
  if (typeof value !== "string" || value.length > 128) fail();
  const words: Record<string, Record<string, string>> = {
    ACCOUNT_ACTIVE: { ACTIVE: "正常", SUSPENDED: "暂停", CLOSED: "关闭" },
    RISK_ENGINE_READY: { true: "可用", false: "不可用" },
    EXECUTION_CONNECTED: { true: "已开放", false: "未开放" },
    RECONCILIATION_HEALTHY: { MATCHED: "一致", DRIFTED: "存在差异", UNAVAILABLE: "不可用" },
    PAPER_ONLY_BOUNDARY: { PAPER_ONLY: "仅模拟" },
  };
  const options = words[code];
  if (options !== undefined) return options[value] ?? fail();
  if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)) fail();
  return value;
}
export function readPaperRiskPreview(value: unknown, context: PaperRiskContext): PaperRiskView {
  const row = record(value);
  if (
    row.schemaVersion !== "paper-risk-decision-v1" ||
    row.dataMeaning !== "SERVER_SIDE_RISK_NO_BROKER_PATH" ||
    row.executionCapability !== "PAPER_ONLY" ||
    row.allowed !== false ||
    row.accountId !== context.accountId ||
    row.intentId !== context.intentId ||
    row.accountStateDigest !== context.accountStateDigest ||
    row.policyId !== "paper-terminal-risk" ||
    row.policyVersion !== "1.0.0" ||
    !Array.isArray(row.checks) ||
    row.checks.length !== 10
  )
    fail();
  const decisionTime = time(row.decisionTime);
  if (Date.parse(decisionTime) < Date.parse(context.decisionTime)) fail();
  const seen = new Set<string>();
  const rows = row.checks.map((value) => {
    const check = record(value),
      code = check.code;
    if (
      typeof code !== "string" ||
      !Object.hasOwn(NAMES, code) ||
      seen.has(code) ||
      (check.status !== "PASS" && check.status !== "FAIL")
    )
      fail();
    seen.add(code);
    if (code === "EXECUTION_CONNECTED" && (check.actual !== "false" || check.status !== "FAIL"))
      fail();
    return {
      code,
      name: NAMES[code as keyof typeof NAMES],
      passed: check.status === "PASS",
      actual: display(code, check.actual),
      limit: display(code, check.limit),
    };
  });
  return { time: decisionTime, policyVersion: "1.0.0", rows };
}
