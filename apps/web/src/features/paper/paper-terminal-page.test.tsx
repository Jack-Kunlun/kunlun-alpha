import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { PaperTerminalPage } from "./paper-terminal-page";
import { usePaperTerminal } from "./use-paper-terminal";

vi.mock("./use-paper-terminal", () => ({
  paperRequestId: () => "test-request-id",
  usePaperTerminal: vi.fn(),
}));

const mocked = vi.mocked(usePaperTerminal);

describe("PaperTerminalPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders an honest empty state and account composer", () => {
    mocked.mockReturnValue(model(emptyWorkspace(), "empty"));
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("创建本地模拟账户");
    expect(html).toContain("易失内存模式");
    expect(html).toContain("无券商路径");
    expect(html).not.toMatch(/P6-N|Phase 6/);
  });

  it("renders orders, server-side risk and reconciliation evidence", () => {
    mocked.mockReturnValue(model(readyWorkspace(), "ready"));
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("600519.SH");
    expect(html).toContain("FILLED");
    expect(html).toContain("MATCHED");
    expect(html).toContain("风险：");
  });

  it("renders unavailable and forbidden states separately", () => {
    mocked.mockReturnValue(model({ ...emptyWorkspace(), status: "UNAVAILABLE" }, "unavailable"));
    expect(renderToStaticMarkup(<PaperTerminalPage />)).toContain("模拟引擎暂不可用");
    mocked.mockReturnValue(model(null, "forbidden"));
    expect(renderToStaticMarkup(<PaperTerminalPage />)).toContain("无权访问模拟组合");
  });
});

function model(
  workspace: PaperTerminalWorkspace | null,
  state: "empty" | "ready" | "unavailable" | "forbidden",
) {
  return {
    workspace,
    state,
    error: null,
    submitting: false,
    refresh: vi.fn().mockResolvedValue(undefined),
    createAccount: vi.fn().mockResolvedValue(undefined),
    simulate: vi.fn().mockResolvedValue(undefined),
  } as ReturnType<typeof usePaperTerminal>;
}

function emptyWorkspace(): PaperTerminalWorkspace {
  return {
    schemaVersion: "paper-terminal-workspace-v1",
    status: "EMPTY",
    dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
    executionCapability: "PAPER_ONLY",
    persistenceMode: "VOLATILE_IN_MEMORY",
    generatedAt: "2026-08-27T02:00:00.000Z",
    limitations: ["服务重启会清空", "不连接真实账户或券商"],
    account: null,
    latestAllocation: null,
    orders: [],
    latestRisk: null,
    reconciliation: null,
    audit: {
      accountEventCount: 0,
      executionEventCount: 0,
      orderAuditCount: 0,
      alertCount: 0,
      accountDigest: null,
      executionDigest: null,
      lastClientRequestId: null,
    },
  };
}

function readyWorkspace(): PaperTerminalWorkspace {
  return {
    ...emptyWorkspace(),
    status: "READY",
    account: {
      accountId: "a".repeat(64),
      name: "本地研究账户",
      status: "ACTIVE",
      baseCurrency: "CNY",
      initialCapital: "100000",
      cash: "69999",
      nav: "99999",
      dataCutoffTime: "2026-08-27T02:00:00.000Z",
      eventCount: 4,
      eventChainDigest: "b".repeat(64),
      positions: [
        {
          instrumentId: "600519.SH",
          quantity: 300,
          availableQuantity: 0,
          costAmount: "30001",
          marketValue: "30000",
        },
      ],
    },
    latestAllocation: {
      decisionId: "c".repeat(64),
      policyId: "paper-terminal-allocation",
      policyVersion: "1.0.0",
      intentCount: 1,
      rejectionCount: 0,
      rejections: [],
    },
    orders: [
      {
        orderId: "d".repeat(64),
        instrumentId: "600519.SH",
        side: "BUY",
        status: "FILLED",
        quantity: 300,
        filledQuantity: 300,
        averageFillPrice: "100",
        totalFees: "1",
        explanation: "模拟订单",
        updatedAt: "2026-08-27T02:00:00.000Z",
      },
    ],
    latestRisk: {
      decisionId: "e".repeat(64),
      allowed: true,
      policyId: "paper-terminal-risk",
      policyVersion: "1.0.0",
      checks: [
        { code: "ENGINE_READY", status: "PASS", actual: "true", limit: null, explanation: "通过" },
      ],
    },
    reconciliation: {
      reconciliationId: "f".repeat(64),
      status: "MATCHED",
      asOf: "2026-08-27T02:00:00.000Z",
      duplicateFillCount: 0,
      diffs: [],
    },
    audit: {
      accountEventCount: 4,
      executionEventCount: 4,
      orderAuditCount: 4,
      alertCount: 0,
      accountDigest: "b".repeat(64),
      executionDigest: "d".repeat(64),
      lastClientRequestId: "simulate-request-1",
    },
  };
}
