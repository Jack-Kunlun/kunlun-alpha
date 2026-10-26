import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { PaperBuyOrdersCard } from "./paper-buy-orders-card";
import {
  readPaperOrderBrowser,
  selectPaperOrders,
  type PaperOrderFilters,
} from "./paper-order-browser";
import { PaperOrderDetailFields } from "./paper-order-detail-drawer";

function workspace(): PaperTerminalWorkspace {
  return JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
      "utf8",
    ),
  ).completed as PaperTerminalWorkspace;
}

describe("paper order browsing", () => {
  it("offers labeled local filters and a separate order detail action", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PaperBuyOrdersCard workspace={workspace()} />
      </MemoryRouter>,
    );
    expect(html).toContain("搜索证券或订单编号");
    expect(html).toContain("订单方向");
    expect(html).toContain("订单状态");
    expect(html).toContain("查看详情");
    expect(html).toContain("显示 1 / 1 笔");
  });

  it("preserves all exact order fields and escapes the explanation without adding risk associations", () => {
    const value = workspace();
    value.orders[0]!.averageFillPrice = "100.123456789123456789";
    value.orders[0]!.totalFees = "9.000000000000000001";
    value.orders[0]!.explanation = '<script>alert("x")</script>\nmanual paper order';
    const model = readPaperOrderBrowser(value);
    const row = model.rows[0]!;
    expect(row.price).toBe(value.orders[0]!.averageFillPrice);
    expect(row.fees).toBe(value.orders[0]!.totalFees);
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PaperOrderDetailFields row={row} generatedAt={model.generatedAt} />
      </MemoryRouter>,
    );
    for (const field of [row.id, row.price!, row.fees, row.time, model.generatedAt])
      expect(html).toContain(field);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("风险通过");
    expect(html).not.toContain(value.latestRisk?.decisionId);
  });

  it("sorts exact timestamps including offsets and sub-millisecond differences, then stable IDs", () => {
    const value = workspace();
    const base = value.orders[0]!;
    value.generatedAt = "2026-10-25T02:00:00.000000003Z";
    value.orders = [
      { ...base, orderId: "b".repeat(64), updatedAt: "2026-10-25T10:00:00.000000001+08:00" },
      { ...base, orderId: "c".repeat(64), updatedAt: "2026-10-25T02:00:00.000000002Z" },
      { ...base, orderId: "a".repeat(64), updatedAt: "2026-10-25T02:00:00.000000002Z" },
    ];
    expect(readPaperOrderBrowser(value).rows.map((r) => r.id)).toEqual([
      "a".repeat(64),
      "c".repeat(64),
      "b".repeat(64),
    ]);
    expect(value.orders[0]!.orderId).toBe("b".repeat(64));
  });

  it("combines case-insensitive symbol or ID search with direction/status and pages only matching rows", () => {
    const value = workspace();
    const base = value.orders[0]!;
    value.orders = Array.from({ length: 25 }, (_, i) => ({
      ...base,
      orderId: i.toString(16).padStart(64, "0"),
      instrumentId: i === 24 ? "000001.SZ" : "600519.SH",
    }));
    value.orders.push({
      ...base,
      orderId: "d".repeat(64),
      instrumentId: "000001.SZ",
      side: "SELL",
      status: "CANCELLED",
      filledQuantity: 100,
    });
    const rows = readPaperOrderBrowser(value).rows;
    const all: PaperOrderFilters = { text: "", side: "ALL", status: "ALL" };
    expect(selectPaperOrders(rows, all, 1).rows).toHaveLength(20);
    expect(selectPaperOrders(rows, all, 2)).toMatchObject({ count: 26, page: 2, pageCount: 2 });
    expect(selectPaperOrders(rows, all, 2).rows).toHaveLength(6);
    const filters: PaperOrderFilters = { text: " 000001.sz ", side: "SELL", status: "CANCELLED" };
    expect(selectPaperOrders(rows, filters, 999)).toMatchObject({
      count: 1,
      page: 1,
      pageCount: 1,
    });
    expect(selectPaperOrders(rows, filters, 1).rows[0]?.id).toBe("d".repeat(64));
    expect(selectPaperOrders(rows, { ...all, text: "DDDD" }, 1).count).toBe(1);
    expect(selectPaperOrders(rows, { ...filters, status: "FILLED" }, 1)).toMatchObject({
      rows: [],
      count: 0,
      page: 1,
      pageCount: 1,
    });
    expect(selectPaperOrders(rows, all, NaN).page).toBe(1);
    expect(rows).toHaveLength(26);
  });

  it("retains pending and cancelled partial records with original fees and no invented fill price", () => {
    const value = workspace();
    const base = value.orders[0]!;
    value.orders = [
      { ...base, status: "CREATED", filledQuantity: 0, averageFillPrice: null, totalFees: "0" },
    ];
    expect(readPaperOrderBrowser(value).rows[0]).toMatchObject({
      price: null,
      fees: "0",
      filled: 0,
      status: "待检查",
    });
    value.orders = [{ ...base, status: "CANCELLED", filledQuantity: 100, totalFees: "2.5" }];
    expect(readPaperOrderBrowser(value).rows[0]).toMatchObject({
      price: "100",
      fees: "2.5",
      filled: 100,
      status: "已取消",
    });
  });

  it.each(["CANCEL_PENDING", "CANCELLED"] as const)(
    "rejects impossible fully filled %s records",
    (status) => {
      const value = workspace();
      value.orders[0]!.status = status;
      expect(() => readPaperOrderBrowser(value)).toThrow();
    },
  );

  it.each([
    ["duplicate IDs", (v: PaperTerminalWorkspace) => v.orders.push({ ...v.orders[0]! })],
    [
      "future timestamp by 1ns",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.updatedAt = "2026-10-25T02:00:00.000000001Z";
      },
    ],
    [
      "impossible date",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.updatedAt = "2026-02-30T02:00:00Z";
      },
    ],
    [
      "blank explanation",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.explanation = "  ";
      },
    ],
    [
      "fee without fill",
      (v: PaperTerminalWorkspace) => {
        Object.assign(v.orders[0]!, {
          status: "CREATED",
          filledQuantity: 0,
          averageFillPrice: null,
        });
      },
    ],
    [
      "zero fill price",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.averageFillPrice = "0";
      },
    ],
    [
      "inconsistent filled state",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.filledQuantity = 100;
      },
    ],
    [
      "invalid partial state",
      (v: PaperTerminalWorkspace) => {
        v.orders[0]!.status = "PARTIALLY_FILLED";
      },
    ],
    [
      "live capability",
      (v: PaperTerminalWorkspace) => {
        Object.assign(v, { executionCapability: "LIVE" });
      },
    ],
  ] as const)("rejects %s without showing a partial list", (_label, mutate) => {
    const value = workspace();
    mutate(value);
    expect(() => readPaperOrderBrowser(value)).toThrow();
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PaperBuyOrdersCard workspace={value} />
      </MemoryRouter>,
    );
    expect(html).toContain('role="alert"');
    expect(html).not.toContain("查看详情");
  });

  it("shows an honest empty list and retains a degraded warning without changing the workspace", () => {
    const value = workspace();
    value.orders = [];
    value.status = "DEGRADED";
    const before = JSON.stringify(value);
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <PaperBuyOrdersCard workspace={value} />
      </MemoryRouter>,
    );
    expect(html).toContain("暂无模拟订单");
    expect(html).toContain("账本存在异常");
    expect(html).not.toContain("查看详情");
    expect(JSON.stringify(value)).toBe(before);
  });
});
