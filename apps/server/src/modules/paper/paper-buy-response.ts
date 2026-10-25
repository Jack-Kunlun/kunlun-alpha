import { createHash } from "node:crypto";
import type { PaperAllocationDecision, PaperTerminalWorkspace } from "@kunlun/shared-types";
import { parsePaperWorkspaceResponse } from "./paper-workspace-response";
import { paperPreviewValidation as p } from "./paper-preview-response";
import { paperInstant, paperNotional, PAPER_RISK_CODES } from "./paper-risk-response";

export function parsePaperBuyResponse(
  value: unknown,
  allocation: PaperAllocationDecision,
): PaperTerminalWorkspace {
  const workspace = parsePaperWorkspaceResponse(value),
    intent = allocation.intents[0];
  if (intent?.side !== "BUY" || workspace.account?.accountId !== allocation.accountId) fail();
  const account = workspace.account;
  const codes = workspace.latestRisk?.checks.map((check) => check.code) ?? [];
  if (
    workspace.status !== "READY" ||
    workspace.persistenceMode !== "DURABLE_COMMAND_JOURNAL" ||
    workspace.audit.lastClientRequestId !== `buy:${allocation.decisionId}` ||
    workspace.audit.alertCount !== 0 ||
    workspace.latestRisk?.allowed !== true ||
    workspace.latestRisk.checks.length !== 10 ||
    new Set(codes).size !== 10 ||
    PAPER_RISK_CODES.some((code) => !codes.includes(code)) ||
    workspace.latestRisk.checks.some((check) => check.status !== "PASS") ||
    workspace.reconciliation?.status !== "MATCHED"
  )
    fail();
  const position = account.positions.find(
      (position) => position.instrumentId === intent.instrumentId,
    ),
    target = allocation.targets[0];
  if (
    position === undefined ||
    target === undefined ||
    position.quantity < intent.targetQuantity ||
    position.availableQuantity > target.currentQuantity ||
    compareSum(
      [account.cash, ...account.positions.map((p) => p.costAmount)],
      account.initialCapital,
    ) !== 0 ||
    compareSum(
      [
        paperNotional(intent.referencePrice, intent.quantity),
        expectedFee(intent.referencePrice, intent.quantity),
      ],
      position.costAmount,
    ) > 0
  )
    fail();
  const orderId = createHash("sha256")
    .update(
      JSON.stringify({
        account_id: allocation.accountId,
        client_order_id: `buy:${allocation.decisionId}`,
        scope: "paper-order",
      }),
    )
    .digest("hex");
  const matches = workspace.orders.filter((order) => order.orderId === orderId),
    order = matches[0];
  if (
    matches.length !== 1 ||
    order === undefined ||
    order.status !== "FILLED" ||
    order.side !== "BUY" ||
    order.instrumentId !== intent.instrumentId ||
    order.quantity !== intent.quantity ||
    order.filledQuantity !== intent.quantity ||
    order.averageFillPrice === null ||
    p.compare(order.averageFillPrice, intent.referencePrice) !== 0 ||
    p.compare(order.totalFees, expectedFee(intent.referencePrice, intent.quantity)) !== 0
  )
    fail();
  if (paperInstant(order.updatedAt) < paperInstant(allocation.decisionTime)) fail();
  return workspace;
}

function expectedFee(price: string, quantity: number): string {
  const [whole = "0", fraction = ""] = price.split(".");
  const numerator = BigInt(whole + fraction) * BigInt(quantity) * 3n,
    denominator = 100n * 10n ** BigInt(fraction.length);
  let cents = numerator / denominator;
  const remainder = numerator % denominator;
  if (remainder * 2n > denominator || (remainder * 2n === denominator && cents % 2n !== 0n))
    cents++;
  if (cents < 100n) cents = 100n;
  return `${cents / 100n}.${(cents % 100n).toString().padStart(2, "0")}`;
}
function fail(): never {
  throw new Error("quant-engine returned an invalid controlled paper buy");
}

function compareSum(values: string[], target: string): number {
  const scale = Math.max(...[...values, target].map((value) => value.split(".")[1]?.length ?? 0));
  const units = (value: string) => {
    const [whole = "0", fraction = ""] = value.split(".");
    return BigInt(whole + fraction.padEnd(scale, "0"));
  };
  const sum = values.reduce((total, value) => total + units(value), 0n),
    expected = units(target);
  return sum < expected ? -1 : sum > expected ? 1 : 0;
}
