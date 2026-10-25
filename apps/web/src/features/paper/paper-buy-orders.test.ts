import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { readPaperBuyOrders } from "./paper-buy-orders";

function fixture(): unknown {
  return JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
      "utf8",
    ),
  );
}
describe("paper buy records", () => {
  it("shows exact server fills, fees and time without inventing an executable price", () => {
    const data = fixture() as Record<string, unknown>;
    const rows = readPaperBuyOrders(data.completed);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      instrument: "600519.SH",
      side: "模拟买入",
      status: "已模拟成交",
      quantity: 300,
      filled: 300,
      price: "100",
      fees: "9",
    });
  });
  it("refuses corrupt or live-capable data", () => {
    const data = (fixture() as Record<string, unknown>).completed as Record<string, unknown>;
    data.executionCapability = "LIVE";
    expect(() => readPaperBuyOrders(data)).toThrow();
  });
  it("keeps an empty actual order list empty", () => {
    const data = (fixture() as Record<string, unknown>).completed as Record<string, unknown>;
    data.orders = [];
    expect(readPaperBuyOrders(data)).toEqual([]);
  });
});
