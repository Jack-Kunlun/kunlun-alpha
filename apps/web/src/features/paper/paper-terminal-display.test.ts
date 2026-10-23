import { describe, expect, it } from "vitest";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import { formatPaperLedgerTime, parsePaperTerminalDisplay } from "./paper-terminal-display";

describe("parsePaperTerminalDisplay", () => {
  it("returns only read-only ledger fields and preserves decimal strings", () => {
    const result = parsePaperTerminalDisplay(readyWorkspace());
    expect(result).toEqual({
      kind: "account",
      persistenceMode: "DURABLE_COMMAND_JOURNAL",
      workspaceStatus: "READY",
      generatedAt: "2026-10-23T09:59:00.123456789+00:00",
      account: {
        name: "本地研究账户",
        status: "ACTIVE",
        baseCurrency: "CNY",
        initialCapital: "100000.01",
        cash: "69999.1",
        dataCutoffTime: "2026-10-23T17:58:00.654321987+08:00",
        eventCount: 2,
        positions: [
          {
            instrumentId: "600519.SH",
            quantity: 300,
            availableQuantity: 200,
            costAmount: "30001.25",
          },
        ],
      },
    });
  });

  it("accepts an empty account workspace", () => {
    expect(
      parsePaperTerminalDisplay({ ...readyWorkspace(), status: "EMPTY", account: null }),
    ).toMatchObject({
      kind: "empty",
      persistenceMode: "DURABLE_COMMAND_JOURNAL",
    });
  });

  const invalidCases: Array<[string, (workspace: PaperTerminalWorkspace) => unknown]> = [
    [
      "invalid amount",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        account: { ...workspace.account!, cash: "NaN" },
      }),
    ],
    [
      "non-canonical amount",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        account: { ...workspace.account!, cash: "01.0" },
      }),
    ],
    [
      "future data cutoff",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        account: { ...workspace.account!, dataCutoffTime: "2999-10-23T10:00:00.000Z" },
      }),
    ],
    [
      "non-canonical instrument",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        account: {
          ...workspace.account!,
          positions: [{ ...workspace.account!.positions[0]!, instrumentId: "600519" }],
        },
      }),
    ],
    [
      "invalid quantity",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        account: {
          ...workspace.account!,
          positions: [{ ...workspace.account!.positions[0]!, availableQuantity: 301 }],
        },
      }),
    ],
    [
      "timestamp precision beyond nanoseconds",
      (workspace: PaperTerminalWorkspace) => ({
        ...workspace,
        generatedAt: "2026-10-23T09:59:00.1234567890Z",
      }),
    ],
  ];

  it.each(invalidCases)("rejects %s", (_caseName, mutate) => {
    const result = parsePaperTerminalDisplay(mutate(readyWorkspace()));
    expect(result.kind).toBe("invalid");
  });

  it("rejects impossible calendar timestamps and cutoff after generation", () => {
    expect(
      parsePaperTerminalDisplay({ ...readyWorkspace(), generatedAt: "2026-02-30T09:00:00.000Z" }),
    ).toMatchObject({ kind: "invalid" });

    const workspace = readyWorkspace();
    expect(
      parsePaperTerminalDisplay({
        ...workspace,
        generatedAt: "2026-10-23T09:59:00.123456789Z",
        account: { ...workspace.account!, dataCutoffTime: "2026-10-23T09:59:00.123456790Z" },
      }),
    ).toMatchObject({ kind: "invalid", message: expect.stringContaining("晚于工作区生成时间") });
  });

  it("formats ledger instants in Shanghai time", () => {
    expect(formatPaperLedgerTime("2026-10-23T09:58:00.000Z")).toBe("2026/10/23 17:58:00");
    expect(formatPaperLedgerTime("2026-10-23T17:58:00.000+08:00")).toBe("2026/10/23 17:58:00");
  });
});

function readyWorkspace(): PaperTerminalWorkspace {
  return {
    schemaVersion: "paper-terminal-workspace-v1",
    status: "READY",
    dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
    executionCapability: "PAPER_ONLY",
    persistenceMode: "DURABLE_COMMAND_JOURNAL",
    generatedAt: "2026-10-23T09:59:00.123456789+00:00",
    limitations: ["仅模拟账户", "不连接券商"],
    account: {
      accountId: "a".repeat(64),
      name: "本地研究账户",
      status: "ACTIVE",
      baseCurrency: "CNY",
      initialCapital: "100000.01",
      cash: "69999.1",
      nav: "99999.99",
      dataCutoffTime: "2026-10-23T17:58:00.654321987+08:00",
      eventCount: 2,
      eventChainDigest: "b".repeat(64),
      positions: [
        {
          instrumentId: "600519.SH",
          quantity: 300,
          availableQuantity: 200,
          costAmount: "30001.25",
          marketValue: "30000.00",
        },
      ],
    },
    latestAllocation: null,
    orders: [],
    latestRisk: null,
    reconciliation: null,
    audit: {
      accountEventCount: 2,
      executionEventCount: 0,
      orderAuditCount: 0,
      alertCount: 0,
      accountDigest: "b".repeat(64),
      executionDigest: null,
      lastClientRequestId: null,
    },
  };
}
