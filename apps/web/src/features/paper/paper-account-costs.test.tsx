import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { readPaperAccountCosts } from "./paper-account-costs";
import { PaperAccountCostsCard } from "./paper-account-costs-card";

function workspace(): PaperTerminalWorkspace {
  const raw: unknown = JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
      "utf8",
    ),
  );
  return structuredClone((raw as { completed: PaperTerminalWorkspace }).completed);
}
function withAmounts(costs: string[], fees: string[]): PaperTerminalWorkspace {
  const w = workspace();
  if (w.account === null) throw new Error("missing fixture account");
  const position = w.account.positions[0]!,
    order = w.orders[0]!;
  w.account.positions = costs.map((costAmount, i) => ({
    ...position,
    instrumentId: i === 0 ? "600519.SH" : "000001.SZ",
    costAmount,
  }));
  w.orders = fees.map((totalFees, i) => ({
    ...order,
    orderId: i.toString(16).padStart(64, "0"),
    totalFees,
  }));
  return w;
}
describe("paper account cost summary", () => {
  it("uses actual remaining cost and cumulative paid fees without adding fees twice", () => {
    const w = workspace(),
      before = structuredClone(w);
    expect(readPaperAccountCosts(w)).toMatchObject({
      positionCost: "30009",
      paidFees: "9",
      filledOrderCount: 1,
      generatedAt: w.generatedAt,
      degraded: false,
    });
    expect(w).toEqual(before);
  });
  it("keeps a valid empty account at zero rather than inventing fills", () => {
    expect(readPaperAccountCosts(withAmounts([], []))).toMatchObject({
      positionCost: "0",
      paidFees: "0",
      filledOrderCount: 0,
    });
  });
  it.each([
    [["0.1", "0.2"], ["0.1", "0.2"], "0.3", "0.3"],
    [
      ["9007199254740993.00000001", "0.00000002"],
      ["0.00000001", "0.00000002"],
      "9007199254740993.00000003",
      "0.00000003",
    ],
    [["1.99", "0.01"], ["0", "0"], "2", "0"],
  ] as const)("sums decimal strings exactly %j", (costs, fees, positionCost, paidFees) => {
    expect(readPaperAccountCosts(withAmounts([...costs], [...fees]))).toMatchObject({
      positionCost,
      paidFees,
      filledOrderCount: fees.length,
    });
  });
  it("includes fees from partial and cancelled filled orders, excludes unfilled orders", () => {
    const w = withAmounts(["30009"], ["1.1", "2.2", "0", "0"]);
    w.orders[0] = { ...w.orders[0]!, status: "PARTIALLY_FILLED", filledQuantity: 50 };
    w.orders[1] = { ...w.orders[1]!, status: "CANCELLED", side: "SELL", filledQuantity: 25 };
    w.orders[2] = {
      ...w.orders[2]!,
      status: "SUBMITTED",
      filledQuantity: 0,
      averageFillPrice: null,
    };
    w.orders[3] = {
      ...w.orders[3]!,
      status: "REJECTED",
      filledQuantity: 0,
      averageFillPrice: null,
    };
    expect(readPaperAccountCosts(w)).toMatchObject({ paidFees: "3.3", filledOrderCount: 2 });
  });
  it("refuses duplicated order identities rather than double counting fees", () => {
    const w = workspace();
    w.orders.push({ ...w.orders[0]! });
    expect(() => readPaperAccountCosts(w)).toThrow();
  });
  it("refuses fees on orders without fills", () => {
    const w = workspace();
    w.orders[0] = {
      ...w.orders[0]!,
      status: "REJECTED",
      filledQuantity: 0,
      averageFillPrice: null,
    };
    expect(() => readPaperAccountCosts(w)).toThrow();
  });
  it.each(["NaN", "-1", "1e-8"])("refuses malformed money %s instead of showing zero", (amount) => {
    expect(() => readPaperAccountCosts(withAmounts([amount], ["0"]))).toThrow();
    expect(() => readPaperAccountCosts(withAmounts(["1"], [amount]))).toThrow();
  });
  it("does not publish a summary for missing accounts or live-capable input", () => {
    const w = workspace();
    expect(() => readPaperAccountCosts({ ...w, account: null })).toThrow();
    expect(() => readPaperAccountCosts({ ...w, executionCapability: "LIVE" })).toThrow();
    expect(() => readPaperAccountCosts({ ...w, status: "UNAVAILABLE" })).toThrow();
  });
  it("does not aggregate future order facts, including nanosecond boundaries", () => {
    const w = workspace();
    w.generatedAt = "2026-10-25T02:00:00.123456789Z";
    w.orders[0] = { ...w.orders[0]!, updatedAt: w.generatedAt };
    expect(readPaperAccountCosts(w).paidFees).toBe("9");
    w.orders[0].updatedAt = "2026-10-25T02:00:00.123456790Z";
    expect(() => readPaperAccountCosts(w)).toThrow();
    w.orders[0].updatedAt = "2026-02-30T00:00:00Z";
    expect(() => readPaperAccountCosts(w)).toThrow();
  });
  it("labels the snapshot and distinguishes cost, paid fees and order count from market value", () => {
    const html = renderToStaticMarkup(<PaperAccountCostsCard workspace={workspace()} />);
    for (const text of [
      "持仓成本合计",
      "累计模拟手续费",
      "有成交订单",
      "30009",
      "不代表行情市值",
      "请勿重复相加",
      "工作区快照时间",
    ])
      expect(html).toContain(text);
    expect(html).not.toContain("收益率");
    const degraded = renderToStaticMarkup(
      <PaperAccountCostsCard workspace={{ ...workspace(), status: "DEGRADED" }} />,
    );
    expect(degraded).toContain('role="alert"');
    expect(degraded).toContain("账本标记异常");
  });
  it("shows an unavailable summary for bad orders and preserves the base page's separate state", () => {
    const w = workspace();
    w.orders.push({ ...w.orders[0]! });
    const html = renderToStaticMarkup(<PaperAccountCostsCard workspace={w} />);
    expect(html).toContain("成本与费用汇总暂不可用");
    expect(html).toContain('role="alert"');
    expect(html).not.toContain("30009");
  });
});
