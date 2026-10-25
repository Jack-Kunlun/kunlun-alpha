import { afterEach, describe, expect, it, vi } from "vitest";
import { BadRequestException, ServiceUnavailableException } from "@nestjs/common";
import { parsePaperReconciliationResponse } from "./paper-reconciliation-response";
import { HttpPaperEngineClient, PaperEngineHttpError } from "./paper-engine.client";
import { PaperTerminalService } from "./paper-terminal.service";

function report() {
  return {
    schemaVersion: "paper-reconciliation-result-v1",
    reconciliationId: "a".repeat(64),
    accountId: "b".repeat(64),
    asOf: "2026-10-25T02:00:00Z",
    status: "MATCHED",
    expectedBookDigest: "c".repeat(64),
    observedBookDigest: "c".repeat(64),
    diffs: [],
    duplicateFillCount: 0,
    executionCapability: "PAPER_ONLY",
    dataMeaning: "SIMULATION_BOOK_RECONCILIATION",
  };
}
const drift = () => ({
  ...report(),
  status: "DRIFTED",
  observedBookDigest: "d".repeat(64),
  diffs: [
    {
      kind: "CASH",
      instrumentId: null,
      expected: "100000.01",
      observed: "100000",
      difference: "-0.01",
    },
  ],
});

afterEach(() => vi.unstubAllGlobals());
describe("fresh paper reconciliation boundary", () => {
  it("reads the current report through the internal GET boundary", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(report()));
    vi.stubGlobal("fetch", fetcher);
    const client = new HttpPaperEngineClient("http://quant-engine:8081", 1000);
    await expect(new PaperTerminalService(client, true).reconciliation()).resolves.toEqual(
      report(),
    );
    expect(fetcher).toHaveBeenCalledWith(
      new URL("http://quant-engine:8081/v1/paper/reconciliation"),
      expect.objectContaining({ method: "GET" }),
    );
  });
  it("preserves drift detail and decimal precision", () => {
    expect(parsePaperReconciliationResponse(drift())).toEqual(drift());
    const value = {
      ...drift(),
      diffs: [
        {
          kind: "POSITION_COST",
          instrumentId: "600519.SH",
          expected: "9007199254740993.00000001",
          observed: "9007199254740993",
          difference: "-0.00000001",
        },
      ],
    };
    expect(parsePaperReconciliationResponse(value)).toEqual(value);
  });
  it.each([
    { status: "LIVE" },
    { executionCapability: "LIVE" },
    { accountId: "private" },
    { asOf: "2026-02-30T00:00:00Z" },
    { status: "DRIFTED" },
    { observedBookDigest: "d".repeat(64) },
    { duplicateFillCount: -1 },
    { private: true },
  ])("rejects invalid or incoherent reports %j", (change) => {
    expect(() => parsePaperReconciliationResponse({ ...report(), ...change })).toThrow();
  });
  it.each([
    { difference: "0.01" },
    { expected: "NaN" },
    { observed: "-1" },
    { instrumentId: "600519.SH" },
    { kind: "FUTURE_FIELD" },
    { difference: "-0" },
  ])("rejects corrupt diff fields %j", (change) => {
    const value = drift();
    expect(() =>
      parsePaperReconciliationResponse({ ...value, diffs: [{ ...value.diffs[0], ...change }] }),
    ).toThrow();
  });
  it("rejects duplicate fields, fractional quantities, and cash without null instrument", () => {
    const value = drift();
    expect(() =>
      parsePaperReconciliationResponse({ ...value, diffs: [...value.diffs, ...value.diffs] }),
    ).toThrow();
    expect(() =>
      parsePaperReconciliationResponse({
        ...value,
        diffs: [
          {
            kind: "POSITION_QUANTITY",
            instrumentId: "000001.SZ",
            expected: "1.1",
            observed: "2",
            difference: "0.9",
          },
        ],
      }),
    ).toThrow();
  });
  it("fails closed and keeps upstream contents private", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ ...report(), status: "LIVE" })),
    );
    const client = new HttpPaperEngineClient("http://quant-engine:8081", 1000);
    await expect(client.reconciliation()).rejects.toMatchObject({
      status: 502,
      message: "quant-engine returned an invalid paper reconciliation",
    });
    await expect(new PaperTerminalService(client).reconciliation()).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ message: "private upstream" }, { status: 422 })),
    );
    await expect(new PaperTerminalService(client).reconciliation()).rejects.toBeInstanceOf(
      BadRequestException,
    );
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new PaperEngineHttpError("private", 503)));
    await expect(new PaperTerminalService(client).reconciliation()).rejects.toBeInstanceOf(
      ServiceUnavailableException,
    );
  });
});
