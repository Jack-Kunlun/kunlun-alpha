import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpPaperEngineClient, PaperEngineHttpError } from "./paper-engine.client";

const UPSTREAM_ERRORS = [
  [409, "模拟账户已存在或请求内容冲突，请刷新账本核对"],
  [422, "模拟账户请求未通过校验，请检查输入"],
  [500, "模拟引擎暂不可用"],
] as const;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HttpPaperEngineClient", () => {
  it("sends previews to the read-only endpoint and rejects a workspace substituted for a decision", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(emptyWorkspace()));
    vi.stubGlobal("fetch", fetchMock);
    const command = {
      schemaVersion: "paper-terminal-simulation-v1" as const,
      clientRequestId: "preview-request-1",
      instrumentId: "600519.SH",
      price: "100",
      score: "1",
      confidence: "1",
      lotSize: 100,
    };
    const client = new HttpPaperEngineClient("http://quant-engine:8081", 1000);
    await expect(client.preview(command)).rejects.toMatchObject({
      status: 502,
      message: "quant-engine returned an invalid paper preview",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://quant-engine:8081/v1/paper/previews"),
      expect.objectContaining({ method: "POST", body: JSON.stringify(command) }),
    );
  });
  it("validates the internal JSON response before returning the workspace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(emptyWorkspace())));
    const client = new HttpPaperEngineClient("http://quant-engine:8000", 1_000);

    await expect(client.workspace()).resolves.toMatchObject({
      schemaVersion: "paper-terminal-workspace-v1",
      status: "EMPTY",
    });
  });

  it("fails closed with a fixed error when the workspace response is corrupt", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ ...emptyWorkspace(), dataMeaning: "private upstream body" }),
        ),
    );
    const client = new HttpPaperEngineClient("http://quant-engine:8000", 1_000);

    const error = await client.workspace().then(
      () => undefined,
      (cause: unknown) => cause,
    );

    expect(error).toBeInstanceOf(PaperEngineHttpError);
    if (!(error instanceof PaperEngineHttpError)) return;
    expect(error.message).toBe("quant-engine returned an invalid paper workspace");
    expect(error.status).toBe(502);
  });

  it("does not expose malformed JSON response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("private upstream body", {
          headers: { "content-type": "application/json" },
          status: 200,
        }),
      ),
    );
    const client = new HttpPaperEngineClient("http://quant-engine:8000", 1_000);

    await expect(client.workspace()).rejects.toMatchObject({
      message: "quant-engine returned an invalid paper workspace",
      status: 502,
    });
  });

  it.each(UPSTREAM_ERRORS)(
    "keeps HTTP %i status semantics without echoing the upstream message",
    async (status, message) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            Response.json(
              { message: "private upstream name, identifier, and log path" },
              { status },
            ),
          ),
      );
      const client = new HttpPaperEngineClient("http://quant-engine:8000", 1_000);
      const error = await client.workspace().then(
        () => undefined,
        (cause: unknown) => cause,
      );

      expect(error).toBeInstanceOf(PaperEngineHttpError);
      if (!(error instanceof PaperEngineHttpError)) return;
      expect(error.status).toBe(status);
      expect(error.message).toBe(message);
      expect(error.message).not.toContain("private upstream");
    },
  );
});

function emptyWorkspace() {
  return {
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
}
