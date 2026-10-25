const STATUSES = {
  CREATED: "待检查",
  CHECKED: "已检查",
  SUBMITTED: "已提交模拟撮合",
  PARTIALLY_FILLED: "部分模拟成交",
  CANCEL_PENDING: "模拟撤销中",
  FILLED: "已模拟成交",
  CANCELLED: "已取消",
  REJECTED: "已拒绝",
};
export interface PaperBuyOrderRow {
  id: string;
  instrument: string;
  side: string;
  status: string;
  quantity: number;
  filled: number;
  price: string | null;
  fees: string;
  time: string;
}
export function readPaperBuyOrders(value: unknown): PaperBuyOrderRow[] {
  const row = record(value);
  if (
    row.schemaVersion !== "paper-terminal-workspace-v1" ||
    row.executionCapability !== "PAPER_ONLY" ||
    row.dataMeaning !== "SIMULATION_ONLY_NO_BROKER_PATH" ||
    !Array.isArray(row.orders)
  )
    fail();
  return row.orders
    .map((value) => {
      const r = record(value);
      if (
        typeof r.orderId !== "string" ||
        !/^[0-9a-f]{64}$/.test(r.orderId) ||
        typeof r.instrumentId !== "string" ||
        !/^\d{6}\.(SH|SZ|BJ)$/.test(r.instrumentId) ||
        typeof r.status !== "string" ||
        !Object.hasOwn(STATUSES, r.status) ||
        (r.side !== "BUY" && r.side !== "SELL") ||
        !Number.isSafeInteger(r.quantity) ||
        typeof r.quantity !== "number" ||
        r.quantity <= 0 ||
        !Number.isSafeInteger(r.filledQuantity) ||
        typeof r.filledQuantity !== "number" ||
        r.filledQuantity < 0 ||
        r.filledQuantity > r.quantity ||
        typeof r.updatedAt !== "string" ||
        !Number.isFinite(Date.parse(r.updatedAt))
      )
        fail();
      if ((r.averageFillPrice === null) !== (r.filledQuantity === 0)) fail();
      return {
        id: r.orderId,
        instrument: r.instrumentId,
        side: r.side === "BUY" ? "模拟买入" : "模拟卖出",
        status: STATUSES[r.status as keyof typeof STATUSES],
        quantity: r.quantity,
        filled: r.filledQuantity,
        price: r.averageFillPrice === null ? null : money(r.averageFillPrice),
        fees: money(r.totalFees),
        time: r.updatedAt,
      };
    })
    .sort((a, b) => Date.parse(b.time) - Date.parse(a.time) || a.id.localeCompare(b.id));
}
function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
function money(value: unknown): string {
  if (typeof value !== "string" || value.length > 128 || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value))
    fail();
  return value;
}
function fail(): never {
  throw new Error("模拟成交记录不可用");
}
