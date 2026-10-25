import { BadRequestException, ConflictException, ForbiddenException } from "@nestjs/common";
import { describe, expect, it, vi } from "vitest";
import type { PaperAllocationDecision, PaperTerminalWorkspace } from "@kunlun/shared-types";
import { PaperEngineHttpError, type PaperEngineClient } from "./paper-engine.client";
import { PaperTerminalService } from "./paper-terminal.service";

describe("PaperTerminalService", () => {
  it("permits read-only previews in account-only mode and rejects malformed inputs", async () => {
    const fake = client();
    const service = new PaperTerminalService(fake, true);
    const command = {
      schemaVersion: "paper-terminal-simulation-v1",
      clientRequestId: "preview-request-1",
      instrumentId: "600519.SH",
      price: "100",
      score: "0",
      confidence: "1",
      lotSize: 100,
    };
    await expect(service.preview(command)).resolves.toMatchObject({
      dataMeaning: "INTENT_ONLY_NO_BROKER_PATH",
    });
    expect(fake.preview).toHaveBeenCalledWith(command);
    expect(fake.simulate).not.toHaveBeenCalled();
    await expect(service.preview({ ...command, price: "0" })).rejects.toBeInstanceOf(
      BadRequestException,
    );
    expect(fake.preview).toHaveBeenCalledOnce();
  });
  it("returns an explicit simulation-only unavailable shell when the engine is down", async () => {
    const service = new PaperTerminalService(
      client({ workspace: vi.fn().mockRejectedValue(new Error()) }),
    );
    const result = await service.workspace();
    expect(result.status).toBe("UNAVAILABLE");
    expect(result.executionCapability).toBe("PAPER_ONLY");
    expect(JSON.stringify(result)).not.toMatch(/P6-N|Phase 6/);
  });

  it("validates commands before forwarding and preserves conflict semantics", async () => {
    const fake = client();
    const service = new PaperTerminalService(fake);
    await expect(service.createAccount({ name: "missing fields" })).rejects.toBeInstanceOf(
      BadRequestException,
    );
    fake.createAccount = vi.fn().mockRejectedValue(new PaperEngineHttpError("exists", 409));
    await expect(
      service.createAccount({
        schemaVersion: "paper-terminal-create-account-v1",
        clientRequestId: "create-request-1",
        name: "研究账户",
        initialCapital: "100000",
      }),
    ).rejects.toBeInstanceOf(ConflictException);
  });

  it("forwards a bounded simulation command", async () => {
    const fake = client();
    const service = new PaperTerminalService(fake);
    await service.simulate({
      schemaVersion: "paper-terminal-simulation-v1",
      clientRequestId: "simulate-request-1",
      instrumentId: "600519.SH",
      price: "100",
      score: "1",
      confidence: "1",
      lotSize: 100,
    });
    expect(fake.simulate).toHaveBeenCalledOnce();
  });

  it("rejects simulations before parsing or forwarding in account-only mode", async () => {
    const fake = client();
    const service = new PaperTerminalService(fake, true);
    await expect(service.simulate({})).rejects.toBeInstanceOf(ForbiddenException);
    expect(fake.simulate).not.toHaveBeenCalled();
    await expect(service.workspace()).resolves.toMatchObject({ status: "EMPTY" });
    await service.createAccount({
      schemaVersion: "paper-terminal-create-account-v1",
      clientRequestId: "create-request-1",
      name: "研究账户",
      initialCapital: "100000",
    });
    expect(fake.createAccount).toHaveBeenCalledOnce();
  });

  it("rejects a whitespace-only account name before creating an unreadable account", async () => {
    const fake = client();
    const service = new PaperTerminalService(fake, true);
    await expect(
      service.createAccount({
        schemaVersion: "paper-terminal-create-account-v1",
        clientRequestId: "create-request-1",
        name: "   ",
        initialCapital: "100000",
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
    expect(fake.createAccount).not.toHaveBeenCalled();
  });
});

function client(overrides: Partial<PaperEngineClient> = {}): PaperEngineClient {
  const workspace = emptyWorkspace();
  return {
    riskPreview: vi.fn(),
    preview: vi.fn().mockResolvedValue(emptyPreview()),
    workspace: vi.fn().mockResolvedValue(workspace),
    createAccount: vi.fn().mockResolvedValue(workspace),
    simulate: vi.fn().mockResolvedValue(workspace),
    ...overrides,
  };
}

function emptyPreview(): PaperAllocationDecision {
  return {
    schemaVersion: "paper-allocation-decision-v1",
    decisionId: "a".repeat(64),
    accountId: "b".repeat(64),
    decisionTime: "2026-10-25T02:00:00Z",
    accountStateDigest: "c".repeat(64),
    policyId: "paper-preview-allocation",
    policyVersion: "1.0.0",
    policyDigest: "d".repeat(64),
    targets: [],
    intents: [],
    rejections: [
      {
        instrumentId: "600519.SH",
        sourceSignalIds: ["e".repeat(64)],
        reason: "NO_ACTION",
        explanation: "没有持仓变化",
      },
    ],
    decisionDigest: "f".repeat(64),
    executionCapability: "PAPER_ONLY",
    dataMeaning: "INTENT_ONLY_NO_BROKER_PATH",
  };
}

function emptyWorkspace(): PaperTerminalWorkspace {
  return {
    schemaVersion: "paper-terminal-workspace-v1",
    status: "EMPTY",
    dataMeaning: "SIMULATION_ONLY_NO_BROKER_PATH",
    executionCapability: "PAPER_ONLY",
    persistenceMode: "VOLATILE_IN_MEMORY",
    generatedAt: "2026-08-27T02:00:00.000Z",
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
}
