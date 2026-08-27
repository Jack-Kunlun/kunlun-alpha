import { BadRequestException, NotFoundException } from "@nestjs/common";
import { describe, expect, it, vi } from "vitest";
import { RankingEngineHttpError, type RankingEngineClient } from "./ranking-engine.client";
import { RankingTerminalService } from "./ranking-terminal.service";

describe("RankingTerminalService", () => {
  it("normalizes a point-in-time query before forwarding", async () => {
    const client = fakeClient();
    const service = new RankingTerminalService(client);
    await service.latest("2026-08-27T10:00:00+08:00");
    expect(client.latest).toHaveBeenCalledWith("2026-08-27T02:00:00.000Z");
  });

  it("rejects invalid time and preserves empty-repository semantics", async () => {
    const client = fakeClient();
    const service = new RankingTerminalService(client);
    await expect(service.latest("tomorrow")).rejects.toBeInstanceOf(BadRequestException);
    client.latest = vi.fn().mockRejectedValue(new RankingEngineHttpError("missing", 404));
    await expect(service.latest(null)).rejects.toBeInstanceOf(NotFoundException);
  });
});

function fakeClient(): RankingEngineClient {
  return {
    latest: vi.fn().mockResolvedValue({}),
  } as unknown as RankingEngineClient;
}
