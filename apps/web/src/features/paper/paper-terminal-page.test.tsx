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

  it("keeps account creation behind a deliberate dialog action", () => {
    mocked.mockReturnValue(model(emptyWorkspace(), "empty"));
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("创建账户");
    expect(html).not.toContain("账户名称");
    expect(html).not.toContain("初始资金");
    expect(html).not.toContain("<form");
    expect(html).toContain("重启后清空");
    expect(html).toContain("当前运行期间有效，重启后清空");
    expect(html).not.toContain("quant-engine");
    expect(html).not.toContain("哈希日志");
    expect(html).toContain("无券商路径");
    expect(html).not.toMatch(/P6-N|Phase 6/);
  });

  it("shows read-only account values without valuation or trading controls", () => {
    mocked.mockReturnValue(model(readyWorkspace(), "ready"));
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("600519.SH");
    expect(html).toContain("100000");
    expect(html).toContain("69999");
    expect(html).toContain("30001");
    expect(html).toContain("账面现金");
    expect(html).not.toContain("可用现金");
    expect(html).toContain('dateTime="2026-08-27T02:00:00.000Z">2026/08/27 10:00:00</time>');
    expect(html).not.toContain("99999");
    expect(html).not.toContain("30000");
    expect(html).not.toContain("执行模拟闭环");
    expect(html).toContain("模拟订单记录");
    expect(html).toContain("已模拟成交");
    expect(html).not.toContain("风控与对账");
    expect(html).not.toContain("FILLED");
    expect(html).not.toContain("MATCHED");
  });

  it("shows an explicit empty positions state", () => {
    const workspace = readyWorkspace();
    mocked.mockReturnValue(
      model(
        {
          ...workspace,
          account: workspace.account === null ? null : { ...workspace.account, positions: [] },
        },
        "ready",
      ),
    );
    expect(renderToStaticMarkup(<PaperTerminalPage />)).toContain("暂无持仓");
  });

  it("warns when the ledger is degraded without changing the account status", () => {
    const workspace = readyWorkspace();
    mocked.mockReturnValue(model({ ...workspace, status: "DEGRADED" }, "ready"));
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("账本存在异常，请核对后再使用资金与持仓信息");
    expect(html).toContain("正常");
  });

  it("refuses malformed account amounts instead of displaying them as balances", () => {
    const workspace = readyWorkspace();
    mocked.mockReturnValue(
      model(
        {
          ...workspace,
          account: workspace.account === null ? null : { ...workspace.account, cash: "NaN" },
        },
        "ready",
      ),
    );
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("账户账本数据无效");
    expect(html).not.toContain("NaN");
  });

  it("refuses future account snapshots", () => {
    const workspace = readyWorkspace();
    mocked.mockReturnValue(
      model(
        {
          ...workspace,
          account:
            workspace.account === null
              ? null
              : { ...workspace.account, dataCutoffTime: "2999-08-27T02:00:00.000Z" },
        },
        "ready",
      ),
    );
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("账户账本数据无效");
    expect(html).toContain("晚于工作区生成时间");
  });

  it("labels the durable command journal without implying live execution", () => {
    mocked.mockReturnValue(
      model(
        {
          ...emptyWorkspace(),
          persistenceMode: "DURABLE_COMMAND_JOURNAL",
          limitations: ["日志损坏时拒绝恢复", "不连接真实账户或券商"],
        },
        "empty",
      ),
    );
    const html = renderToStaticMarkup(<PaperTerminalPage />);
    expect(html).toContain("重启后保留");
    expect(html).toContain("服务端保存，重启后保留");
    expect(html).toContain("无券商路径");
    expect(html).not.toContain("quant-engine");
    expect(html).not.toContain("哈希日志");
  });

  it("renders unavailable and forbidden states separately", () => {
    mocked.mockReturnValue(model({ ...emptyWorkspace(), status: "UNAVAILABLE" }, "unavailable"));
    const unavailable = renderToStaticMarkup(<PaperTerminalPage />);
    expect(unavailable).toContain("模拟账本暂不可用");
    expect(unavailable).not.toContain("quant-engine");
    mocked.mockReturnValue(model(null, "forbidden"));
    const forbidden = renderToStaticMarkup(<PaperTerminalPage />);
    expect(forbidden).toContain("无权访问模拟账本");
    expect(forbidden).toContain("当前账号无权访问此账本");
    expect(forbidden).not.toContain("paper:read");
    mocked.mockReturnValue(model(null, "loading"));
    expect(renderToStaticMarkup(<PaperTerminalPage />)).toContain("正在加载模拟账本");
    mocked.mockReturnValue(model(null, "error"));
    expect(renderToStaticMarkup(<PaperTerminalPage />)).toContain("模拟账本加载失败");
  });
});

function model(
  workspace: PaperTerminalWorkspace | null,
  state: "empty" | "ready" | "unavailable" | "forbidden" | "loading" | "error",
) {
  return {
    workspace,
    state,
    submitting: false,
    accept: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
    createAccount: vi.fn().mockResolvedValue(undefined),
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
