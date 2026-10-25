import { z } from "zod";
import { readPaperBuyOrders } from "./paper-buy-orders";
import { parsePaperTerminalDisplay } from "./paper-terminal-display";

const cutoffSchema = z.iso.datetime({ offset: true });

export interface PaperAccountCosts {
  positionCost: string;
  paidFees: string;
  filledOrderCount: number;
  generatedAt: string;
  degraded: boolean;
}

/** Read one workspace only. Cost already includes its buy fees; paid fees are a separate disclosure. */
export function readPaperAccountCosts(workspace: unknown): PaperAccountCosts {
  const display = parsePaperTerminalDisplay(workspace);
  if (display.kind !== "account") fail();
  const orders = readPaperBuyOrders(workspace);
  const cutoff = instant(display.generatedAt);
  const seen = new Set<string>();
  for (const order of orders) {
    if (seen.has(order.id) || instant(order.time) > cutoff) fail();
    seen.add(order.id);
    if (order.filled === 0 && sum([order.fees]) !== "0") fail();
  }
  return {
    positionCost: sum(display.account.positions.map((position) => position.costAmount)),
    paidFees: sum(orders.map((order) => order.fees)),
    filledOrderCount: orders.filter((order) => order.filled > 0).length,
    generatedAt: display.generatedAt,
    degraded: display.workspaceStatus === "DEGRADED",
  };
}

function sum(values: readonly string[]): string {
  if (values.some((value) => value.length > 128 || !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value)))
    fail();
  const scale = values.reduce(
    (maximum, value) => Math.max(maximum, value.split(".")[1]?.length ?? 0),
    0,
  );
  const units = values.reduce((total, value) => {
    const [whole = "0", fraction = ""] = value.split(".");
    return total + BigInt(whole + fraction.padEnd(scale, "0"));
  }, 0n);
  const digits = units.toString().padStart(scale + 1, "0");
  return scale === 0
    ? digits
    : `${digits.slice(0, -scale)}.${digits.slice(-scale)}`.replace(/0+$/, "").replace(/\.$/, "");
}

function instant(value: string): bigint {
  const time = value.replace("t", "T").replace(/z$/, "Z");
  if (!cutoffSchema.safeParse(time).success) fail();
  const match = /^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(time);
  if (match === null) fail();
  return (
    BigInt(Date.parse(`${match[1]}${match[3]}`)) * 1_000_000n +
    BigInt((match[2] ?? "").padEnd(9, "0"))
  );
}
function fail(): never {
  throw new Error("成本与费用汇总不可用");
}
