import { readPaperBuyOrders, type PaperBuyOrderRow } from "./paper-buy-orders";
import { comparePaperLedgerTimes, parsePaperTerminalDisplay } from "./paper-terminal-display";

export interface PaperOrderBrowser {
  rows: PaperBuyOrderRow[];
  generatedAt: string;
  degraded: boolean;
}
export interface PaperOrderFilters {
  text: string;
  side: "ALL" | PaperBuyOrderRow["sideCode"];
  status: "ALL" | PaperBuyOrderRow["statusCode"];
}

/** Project one existing workspace. No fills, risk associations or state transitions are inferred. */
export function readPaperOrderBrowser(value: unknown): PaperOrderBrowser {
  const display = parsePaperTerminalDisplay(value);
  if (display.kind !== "account") throw new Error("模拟订单记录不可用");
  const rows = readPaperBuyOrders(value);
  const seen = new Set<string>();
  for (const row of rows) {
    if (
      seen.has(row.id) ||
      comparePaperLedgerTimes(row.time, display.generatedAt) > 0 ||
      (row.filled === 0 && /[1-9]/.test(row.fees)) ||
      (row.filled > 0 && !/[1-9]/.test(row.price ?? "")) ||
      (row.statusCode === "FILLED" && row.filled !== row.quantity) ||
      (row.statusCode === "PARTIALLY_FILLED" &&
        (row.filled === 0 || row.filled === row.quantity)) ||
      (["CANCEL_PENDING", "CANCELLED"].includes(row.statusCode) && row.filled === row.quantity) ||
      (["CREATED", "CHECKED", "SUBMITTED", "REJECTED"].includes(row.statusCode) && row.filled !== 0)
    )
      throw new Error("模拟订单记录不可用");
    seen.add(row.id);
  }
  rows.sort(
    (a, b) => comparePaperLedgerTimes(b.time, a.time) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0),
  );
  return {
    rows,
    generatedAt: display.generatedAt,
    degraded: display.workspaceStatus === "DEGRADED",
  };
}

export function selectPaperOrders(
  rows: readonly PaperBuyOrderRow[],
  filters: PaperOrderFilters,
  requestedPage: number,
) {
  const text = filters.text.trim().toUpperCase();
  const filtered = rows.filter(
    (row) =>
      (text.length === 0 || row.instrument.includes(text) || row.id.toUpperCase().includes(text)) &&
      (filters.side === "ALL" || row.sideCode === filters.side) &&
      (filters.status === "ALL" || row.statusCode === filters.status),
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / 20));
  const page = Math.min(
    pageCount,
    Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
  );
  return {
    rows: filtered.slice((page - 1) * 20, page * 20),
    count: filtered.length,
    page,
    pageCount,
  };
}
