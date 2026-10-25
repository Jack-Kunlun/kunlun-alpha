import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parsePaperRiskPreviewRequest, parsePaperRiskPreviewResponse } from "./paper-risk-response";
import { parsePaperBuyResponse } from "./paper-buy-response";
import { HttpPaperEngineClient } from "./paper-engine.client";
import { PaperTerminalService } from "./paper-terminal.service";

function fixture() {
  const raw: unknown = JSON.parse(
    readFileSync(
      resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
      "utf8",
    ),
  );
  if (typeof raw !== "object" || raw === null) throw new Error();
  const r = raw as Record<string, unknown>;
  return {
    allocation: parsePaperRiskPreviewRequest(r.allocation),
    risk: r.risk,
    completed: parsePaperBuyResponse(r.completed, parsePaperRiskPreviewRequest(r.allocation)),
  };
}
afterEach(() => vi.unstubAllGlobals());
describe("controlled paper buy boundary", () => {
  it("binds a fully filled result and exact fees to the supplied snapshot", () => {
    const { completed } = fixture();
    expect(completed.orders[0]?.totalFees).toBe("9");
    expect(completed.account?.cash).toBe("69991");
  });
  it.each(["identity", "quantity", "price", "fee", "status"])(
    "rejects a substituted %s",
    (field) => {
      const { allocation, completed } = fixture();
      const o = completed.orders[0]!;
      if (field === "identity") o.orderId = "0".repeat(64);
      if (field === "quantity") {
        o.quantity = 400;
        o.filledQuantity = 400;
      }
      if (field === "price") o.averageFillPrice = "101";
      if (field === "fee") o.totalFees = "0";
      if (field === "status") o.status = "SUBMITTED";
      expect(() => parsePaperBuyResponse(completed, allocation)).toThrow();
    },
  );
  it("accepts available paper risk only when the control plane explicitly enables it", () => {
    const { allocation, risk } = fixture();
    expect(() => parsePaperRiskPreviewResponse(risk, allocation)).toThrow();
    expect(parsePaperRiskPreviewResponse(risk, allocation, true).allowed).toBe(true);
  });
  it("forwards the snapshot only through the controlled endpoint and never opens legacy simulation", async () => {
    const { allocation, completed } = fixture();
    const fetch = vi.fn().mockResolvedValue(Response.json(completed));
    vi.stubGlobal("fetch", fetch);
    const engine = new HttpPaperEngineClient("http://quant-engine:8081", 1000, true);
    const disabled = new PaperTerminalService(engine, true, false);
    await expect(disabled.buyAllocation(allocation)).rejects.toMatchObject({ status: 403 });
    expect(fetch).not.toHaveBeenCalled();
    const service = new PaperTerminalService(engine, true, true);
    await expect(service.buyAllocation(allocation)).resolves.toEqual(completed);
    expect(fetch).toHaveBeenCalledWith(
      new URL("http://quant-engine:8081/v1/paper/buy-simulations"),
      expect.objectContaining({ body: JSON.stringify(allocation) }),
    );
    await expect(service.simulate({})).rejects.toMatchObject({ status: 403 });
    expect(fetch).toHaveBeenCalledOnce();
  });
});

describe("committed buy health closure", () => {
  it.each([
    "degraded",
    "risk",
    "checks",
    "reconciliation",
    "alerts",
    "durable",
    "request",
    "position",
    "cost",
    "balance",
    "future",
  ])("refuses a filled order with invalid %s", (field) => {
    const { allocation, completed } = fixture();
    if (field === "degraded") {
      completed.status = "DEGRADED";
      completed.latestRisk!.allowed = false;
    }
    if (field === "risk") completed.latestRisk = null;
    if (field === "checks") completed.latestRisk!.checks[0]!.status = "FAIL";
    if (field === "reconciliation") completed.reconciliation = null;
    if (field === "alerts") {
      completed.audit.alertCount = 1;
      completed.status = "DEGRADED";
    }
    if (field === "durable") completed.persistenceMode = "VOLATILE_IN_MEMORY";
    if (field === "request") completed.audit.lastClientRequestId = "different-request";
    if (field === "position") {
      completed.account!.positions[0]!.quantity = 200;
      completed.account!.positions[0]!.marketValue = "20000";
      completed.account!.nav = "89991";
    }
    if (field === "cost") {
      completed.account!.positions[0]!.costAmount = "30000";
      completed.account!.cash = "70000";
      completed.account!.nav = "100000";
    }
    if (field === "balance") completed.account!.positions[0]!.costAmount = "30010";
    if (field === "future") allocation.decisionTime = "2026-10-25T02:00:00.000000001Z";
    expect(() => parsePaperBuyResponse(completed, allocation)).toThrow();
  });
  it("accepts an original retry after a later successful buy with larger holdings", () => {
    const raw: unknown = JSON.parse(
      readFileSync(
        resolve(process.cwd(), "../../data/fixtures/paper-controlled-buy-v1.json"),
        "utf8",
      ),
    );
    const data = raw as Record<string, unknown>;
    const allocation = parsePaperRiskPreviewRequest(data.allocation);
    const result = parsePaperBuyResponse(data.retryAfterNextBuy, allocation);
    expect(result.orders).toHaveLength(2);
    expect(result.account?.positions[0]?.quantity).toBeGreaterThan(
      allocation.intents[0]!.targetQuantity,
    );
  });
});

it("fails the public operation closed when the upstream claims a fill with an unhealthy ledger", async () => {
  const { allocation, completed } = fixture();
  completed.status = "DEGRADED";
  completed.latestRisk!.allowed = false;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(completed)));
  const service = new PaperTerminalService(
    new HttpPaperEngineClient("http://quant-engine:8081", 1000, true),
    true,
    true,
  );
  await expect(service.buyAllocation(allocation)).rejects.toMatchObject({ status: 503 });
});
