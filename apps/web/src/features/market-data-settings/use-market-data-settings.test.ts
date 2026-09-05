import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/lib/api-client";
import { getMarketDataSettings, updateMarketDataSettings } from "./market-data-settings-client";

describe("market data settings API boundary", () => {
  it("uses the browser settings endpoint and validates a safe response", async () => {
    const client: ApiClient = {
      get: vi.fn().mockResolvedValue({
        schemaVersion: "market-data-settings-v1",
        provider: "akshare",
        revision: 0,
        tokenConfigured: false,
        updatedAt: null,
      }),
      post: vi.fn(),
    };

    await expect(getMarketDataSettings(client)).resolves.toMatchObject({
      provider: "akshare",
      revision: 0,
    });
    expect(client.get).toHaveBeenCalledWith("/v1/market-data/settings");
  });

  it("never sends token for KEEP/CLEAR and forwards only the validated update", async () => {
    const client: ApiClient = {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({
        schemaVersion: "market-data-settings-v1",
        provider: "akshare",
        revision: 4,
        tokenConfigured: false,
        updatedAt: "2026-09-05T00:00:00.000Z",
      }),
    };

    await updateMarketDataSettings(client, {
      schemaVersion: "market-data-settings-update-v1",
      expectedRevision: 3,
      provider: "akshare",
      tokenAction: "KEEP",
    });
    expect(client.post).toHaveBeenCalledWith("/v1/market-data/settings", {
      schemaVersion: "market-data-settings-update-v1",
      expectedRevision: 3,
      provider: "akshare",
      tokenAction: "KEEP",
    });
  });

  it("rejects secret-bearing fields for KEEP before making a request", async () => {
    const client: ApiClient = {
      get: vi.fn(),
      post: vi.fn(),
    };
    await expect(
      updateMarketDataSettings(client, {
        schemaVersion: "market-data-settings-update-v1",
        expectedRevision: 3,
        provider: "akshare",
        tokenAction: "KEEP",
        token: "secret-token",
      }),
    ).rejects.toThrow("KEEP/CLEAR 不接受 token");
    expect(client.post).not.toHaveBeenCalled();
  });
});
