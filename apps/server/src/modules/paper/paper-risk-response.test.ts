import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { PaperAllocationDecision, PaperRiskDecision } from "@kunlun/shared-types";
import { describe, expect, it } from "vitest";
import { parsePaperRiskPreviewRequest, parsePaperRiskPreviewResponse } from "./paper-risk-response";
import { HttpPaperEngineClient } from "./paper-engine.client";
import { PaperTerminalService } from "./paper-terminal.service";
import { afterEach, vi } from "vitest";

afterEach(() => vi.unstubAllGlobals());

function fixture(): { allocation: PaperAllocationDecision; risk: PaperRiskDecision } {
  // This isolated fixed-clock fixture is produced by the real domain models;
  // both request and response below cross the validators before use.
  const raw: unknown = JSON.parse(
    readFileSync(resolve(process.cwd(), "../../data/fixtures/paper-risk-preview-v1.json"), "utf8"),
  );
  if (typeof raw !== "object" || raw === null) throw new Error("invalid fixture");
  const data = raw as Record<string, unknown>;
  const allocation = parsePaperRiskPreviewRequest(data.allocation);
  return { allocation, risk: parsePaperRiskPreviewResponse(data.risk, allocation) };
}
describe("risk preview boundary", () => {
  it("accepts the existing snapshot contract and all ten consistent checks", () => {
    const { allocation, risk } = fixture();
    expect(risk.allowed).toBe(false);
    expect(risk.intentId).toBe(allocation.intents[0]?.intentId);
    expect(risk.checks).toHaveLength(10);
  });
  it.each([
    "allowed",
    "missing",
    "duplicate",
    "intent",
    "basis",
    "execution",
    "status",
    "notional",
    "weight",
    "future",
    "checksum",
    "policy",
  ])("rejects inconsistent %s", (field) => {
    const { allocation, risk } = fixture();
    if (field === "allowed") risk.allowed = true;
    if (field === "missing") risk.checks.pop();
    if (field === "duplicate") risk.checks[1] = risk.checks[0]!;
    if (field === "intent") risk.intentId = "0".repeat(64);
    if (field === "basis") risk.accountStateDigest = "0".repeat(64);
    if (field === "execution") {
      const c = risk.checks.find((c) => c.code === "EXECUTION_CONNECTED")!;
      c.actual = "true";
      c.status = "PASS";
    }
    if (field === "status") risk.checks[0]!.status = "FAIL";
    if (field === "notional")
      risk.checks.find((c) => c.code === "ORDER_NOTIONAL_LIMIT")!.actual = "29999";
    if (field === "weight")
      risk.checks.find((c) => c.code === "POSITION_WEIGHT_LIMIT")!.actual = "0.1";
    if (field === "future") allocation.decisionTime = "2026-10-25T02:00:00.000000001Z";
    if (field === "checksum") risk.decisionId = "0".repeat(64);
    if (field === "policy") risk.policyDigest = "0".repeat(64);
    expect(() => parsePaperRiskPreviewResponse(risk, allocation)).toThrow();
  });
  it("allows read-only checks through account-only service and forwards the exact snapshot", async () => {
    const { allocation, risk } = fixture();
    const fetchMock = vi.fn().mockResolvedValue(Response.json(risk));
    vi.stubGlobal("fetch", fetchMock);
    const service = new PaperTerminalService(
      new HttpPaperEngineClient("http://quant-engine:8081", 1000),
      true,
    );
    await expect(service.riskPreview(allocation)).resolves.toEqual(risk);
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://quant-engine:8081/v1/paper/risk-previews"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(allocation) }),
    );
    await expect(service.riskPreview({})).rejects.toMatchObject({ status: 400 });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("preserves stale-basis conflicts and redacts upstream messages", async () => {
    const { allocation } = fixture();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(Response.json({ message: "private upstream body" }, { status: 409 })),
    );
    const service = new PaperTerminalService(
      new HttpPaperEngineClient("http://quant-engine:8081", 1000),
      true,
    );
    await expect(service.riskPreview(allocation)).rejects.toMatchObject({
      status: 409,
      message: "试算基准已变化，请重新试算",
    });
  });
  it("fails closed on a corrupt upstream report", async () => {
    const { allocation, risk } = fixture();
    risk.allowed = true;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(risk)));
    const client = new HttpPaperEngineClient("http://quant-engine:8081", 1000);
    await expect(client.riskPreview(allocation)).rejects.toMatchObject({
      status: 502,
      message: "quant-engine returned an invalid paper risk preview",
    });
  });
  it("rejects incomplete or rejected allocation requests", () => {
    expect(() => parsePaperRiskPreviewRequest({})).toThrow();
    const { allocation } = fixture();
    allocation.intents = [];
    expect(() => parsePaperRiskPreviewRequest(allocation)).toThrow();
  });
});
