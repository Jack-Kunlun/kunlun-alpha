import { describe, expect, it } from "vitest";
import type { PaperTerminalWorkspace } from "@kunlun/shared-types";
import {
  PaperWorkspaceResponseError,
  parsePaperWorkspaceResponse,
} from "./paper-workspace-response";

const EMPTY_WORKSPACE: PaperTerminalWorkspace = {
  schemaVersion: "paper-terminal-workspace-v1",
  status: "EMPTY",
  dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
  executionCapability: "PAPER_ONLY",
  persistenceMode: "VOLATILE_IN_MEMORY",
  generatedAt: "2026-10-23T12:00:00.000Z",
  limitations: ["易失内存模式"],
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

const READY_WORKSPACE: PaperTerminalWorkspace = {
  ...EMPTY_WORKSPACE,
  status: "READY",
  account: {
    accountId: "a".repeat(64),
    name: "研究账户",
    status: "ACTIVE",
    baseCurrency: "CNY",
    initialCapital: "900719925474099312346",
    cash: "0.1",
    nav: "900719925474099312346",
    dataCutoffTime: "2026-10-23T19:00:00+08:00",
    eventCount: 2,
    eventChainDigest: "b".repeat(64),
    positions: [
      {
        instrumentId: "600519.SH",
        quantity: 100,
        availableQuantity: 0,
        costAmount: "900719925474099312345.8",
        marketValue: "900719925474099312345.9",
      },
    ],
  },
  audit: {
    accountEventCount: 2,
    executionEventCount: 0,
    orderAuditCount: 0,
    alertCount: 0,
    accountDigest: "c".repeat(64),
    executionDigest: "0".repeat(64),
    lastClientRequestId: "create-request-1",
  },
};

describe("parsePaperWorkspaceResponse", () => {
  it("preserves a valid empty workspace", () => {
    expect(parsePaperWorkspaceResponse(EMPTY_WORKSPACE)).toEqual(EMPTY_WORKSPACE);
  });

  it("preserves exact large money strings and a valid account snapshot", () => {
    const parsed = parsePaperWorkspaceResponse(READY_WORKSPACE);
    expect(parsed).toEqual(READY_WORKSPACE);
    expect(parsed.account?.nav).toBe("900719925474099312346");
    expect(parsed.account?.positions[0]?.marketValue).toBe("900719925474099312345.9");
  });

  it("compares timezone-aware timestamps without losing Python microseconds", () => {
    const snapshot = mutableWorkspace();
    snapshot["generatedAt"] = "2026-10-23T11:00:00.123456Z";
    const account = snapshot["account"] as Record<string, unknown>;
    account["dataCutoffTime"] = "2026-10-23T19:00:00.123455+08:00";

    expect(parsePaperWorkspaceResponse(snapshot)).toMatchObject({
      generatedAt: "2026-10-23T11:00:00.123456Z",
    });
  });

  it("retains a valid degraded workspace without projecting replacement values", () => {
    const degraded: PaperTerminalWorkspace = {
      ...READY_WORKSPACE,
      status: "DEGRADED",
      latestRisk: {
        decisionId: "d".repeat(64),
        allowed: false,
        policyId: "paper-risk",
        policyVersion: "1.0.0",
        checks: [
          {
            code: "risk-check",
            status: "FAIL",
            actual: "100",
            limit: "50",
            explanation: "超过限额",
          },
        ],
      },
    };

    expect(parsePaperWorkspaceResponse(degraded)).toEqual(degraded);
  });

  it("fails closed on a degraded workspace with an inconsistent NAV", () => {
    const degraded = mutableWorkspace();
    degraded["status"] = "DEGRADED";
    degraded["reconciliation"] = {
      reconciliationId: "d".repeat(64),
      status: "DRIFTED",
      asOf: "2026-10-23T11:00:00Z",
      duplicateFillCount: 0,
      diffs: [],
    };
    const account = degraded["account"] as Record<string, unknown>;
    account["nav"] = "900719925474099312347";

    expect(() => parsePaperWorkspaceResponse(degraded)).toThrow(PaperWorkspaceResponseError);
  });

  it("preserves valid legacy allocation, execution, risk, and reconciliation records", () => {
    const degraded: PaperTerminalWorkspace = {
      ...READY_WORKSPACE,
      status: "DEGRADED",
      latestAllocation: {
        decisionId: "d".repeat(64),
        policyId: "paper-allocation",
        policyVersion: "1.0.0",
        intentCount: 1,
        rejectionCount: 0,
        rejections: [],
      },
      orders: [
        {
          orderId: "e".repeat(64),
          instrumentId: "600519.SH",
          side: "BUY",
          status: "FILLED",
          quantity: 100,
          filledQuantity: 100,
          averageFillPrice: "10.01",
          totalFees: "1",
          explanation: "模拟成交",
          updatedAt: "2026-10-23T19:00:00+08:00",
        },
      ],
      latestRisk: {
        decisionId: "f".repeat(64),
        allowed: true,
        policyId: "paper-risk",
        policyVersion: "1.0.0",
        checks: [
          {
            code: "cash-available",
            status: "PASS",
            actual: "1000",
            limit: "0",
            explanation: "现金充足",
          },
        ],
      },
      reconciliation: {
        reconciliationId: "1".repeat(64),
        status: "DRIFTED",
        asOf: "2026-10-23T11:00:00Z",
        duplicateFillCount: 0,
        diffs: [
          {
            kind: "POSITION_QUANTITY",
            instrumentId: "600519.SH",
            expected: "100",
            observed: "99",
            difference: "-1",
          },
        ],
      },
      audit: {
        ...READY_WORKSPACE.audit,
        executionEventCount: 5,
        orderAuditCount: 2,
      },
    };

    expect(parsePaperWorkspaceResponse(degraded)).toEqual(degraded);
  });

  it("accepts the explicit unavailable shell", () => {
    expect(
      parsePaperWorkspaceResponse({
        ...EMPTY_WORKSPACE,
        status: "UNAVAILABLE",
        limitations: ["模拟引擎当前不可达"],
      }),
    ).toMatchObject({ status: "UNAVAILABLE", account: null });
  });

  it.each([
    ["simulation meaning", (value: Record<string, unknown>) => (value["dataMeaning"] = "BROKER")],
    ["extra root fields", (value: Record<string, unknown>) => (value["unexpected"] = true)],
    [
      "missing audit fields",
      (value: Record<string, unknown>) => {
        const audit = value["audit"] as Record<string, unknown>;
        delete audit["alertCount"];
      },
    ],
    [
      "invalid account digest relationship",
      (value: Record<string, unknown>) => {
        const audit = value["audit"] as Record<string, unknown>;
        audit["accountEventCount"] = 1;
      },
    ],
    [
      "invalid account cutoff",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        account["dataCutoffTime"] = "2026-10-23T12:00:00.000000001Z";
      },
    ],
    [
      "invalid account NAV",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        account["nav"] = "900719925474099312345.99";
      },
    ],
    [
      "non-canonical money",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        account["cash"] = "01.0";
      },
    ],
    [
      "non-positive initial capital",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        account["initialCapital"] = "0";
      },
    ],
    [
      "negative position cost",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const position = firstPosition(account);
        position["costAmount"] = "-1";
      },
    ],
    [
      "negative market value",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const position = firstPosition(account);
        position["marketValue"] = "-1";
      },
    ],
    [
      "malformed calendar date",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        account["dataCutoffTime"] = "2026-02-30T19:00:00+08:00";
      },
    ],
    [
      "incorrect digest format",
      (value: Record<string, unknown>) => {
        const audit = value["audit"] as Record<string, unknown>;
        audit["accountDigest"] = "not-a-digest";
      },
    ],
    [
      "duplicate instrument positions",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const positions = account["positions"] as unknown[];
        positions.push({ ...(positions[0] as Record<string, unknown>) });
      },
    ],
    [
      "fractional position quantities",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const position = firstPosition(account);
        position["quantity"] = 100.5;
      },
    ],
    [
      "empty position records",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const position = firstPosition(account);
        position["quantity"] = 0;
        position["availableQuantity"] = 0;
      },
    ],
    [
      "available quantity above total",
      (value: Record<string, unknown>) => {
        const account = value["account"] as Record<string, unknown>;
        const position = firstPosition(account);
        position["availableQuantity"] = 101;
      },
    ],
  ])("rejects %s", (_label, mutate) => {
    const value = mutableWorkspace();
    mutate(value);
    expect(() => parsePaperWorkspaceResponse(value)).toThrow(PaperWorkspaceResponseError);
  });

  it("rejects account data on an EMPTY workspace", () => {
    const value = { ...EMPTY_WORKSPACE, account: READY_WORKSPACE.account };
    expect(() => parsePaperWorkspaceResponse(value)).toThrow(PaperWorkspaceResponseError);
  });

  it("rejects malformed shapes without exposing supplied content", () => {
    const hostilePayload = {
      ...EMPTY_WORKSPACE,
      dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
      secret: "upstream-private-response-body",
    };
    try {
      parsePaperWorkspaceResponse(hostilePayload);
      throw new Error("expected invalid workspace to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(PaperWorkspaceResponseError);
      expect((error as Error).message).not.toContain("upstream-private-response-body");
    }
  });
});

function mutableWorkspace(): Record<string, unknown> {
  const cloned: unknown = structuredClone(READY_WORKSPACE);
  if (typeof cloned !== "object" || cloned === null || Array.isArray(cloned)) {
    throw new Error("workspace test fixture must be an object");
  }
  return cloned as Record<string, unknown>;
}

function firstPosition(account: Record<string, unknown>): Record<string, unknown> {
  const positions: unknown = account["positions"];
  if (!Array.isArray(positions)) throw new Error("workspace test fixture must contain positions");
  const position: unknown = positions[0];
  if (typeof position !== "object" || position === null || Array.isArray(position)) {
    throw new Error("workspace test fixture must contain a position object");
  }
  return position as Record<string, unknown>;
}
