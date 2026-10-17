import { describe, expect, it, vi } from "vitest";
import type { PersonalWatchlistResponse } from "@kunlun/shared-types";
import type { ApiClient } from "@/lib/api-client";
import {
  importPersonalWatchlist,
  loadPersonalWatchlist,
  personalWatchlistQuoteQuery,
  personalWatchlistQuotePath,
} from "./use-personal-watchlist";

const items = [
  { code: "600519.SH", name: "示例股票" },
  { code: "HK:09618", name: "观察项" },
];

function response(names = ["示例股票", "观察项"]): PersonalWatchlistResponse {
  return {
    schemaVersion: "personal-watchlist-response-v1",
    items: items.map((item, index) => ({
      ...item,
      name: names[index] ?? item.name,
      addedAt: "2026-10-17T01:00:00.000Z",
      market: {
        status: "PENDING",
        lastAttemptAt: null,
        lastSuccessAt: null,
        errorCode: null,
      },
    })),
  };
}

describe("personal watchlist server client", () => {
  it("loads the authenticated server list and validates its contract", async () => {
    const get = vi.fn().mockResolvedValue(response());
    const client = { get } as unknown as ApiClient;
    await expect(loadPersonalWatchlist(client)).resolves.toEqual(response());
    expect(get).toHaveBeenCalledWith("/v1/personal-watchlist");
    await expect(
      loadPersonalWatchlist({
        get: vi.fn().mockResolvedValue({ items: [] }),
      } as unknown as ApiClient),
    ).rejects.toThrow("响应格式无效");
  });

  it("sends the versioned import with a stable caller-provided id and verifies all codes", async () => {
    const post = vi.fn().mockResolvedValue(response());
    const client = { post } as unknown as ApiClient;
    const result = await importPersonalWatchlist(
      client,
      items,
      "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1",
    );

    expect(post).toHaveBeenCalledWith("/v1/personal-watchlist/import", {
      schemaVersion: "personal-watchlist-import-v1",
      clientRequestId: "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1",
      items,
    });
    expect(result.nameConflicts).toEqual([]);
  });

  it("treats a retained server name as acknowledged and reports the difference", async () => {
    const client = {
      post: vi.fn().mockResolvedValue(response(["服务端原名称", "观察项"])),
    } as unknown as ApiClient;
    await expect(
      importPersonalWatchlist(client, items, "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1"),
    ).resolves.toMatchObject({ nameConflicts: [{ code: "600519.SH", name: "服务端原名称" }] });
  });

  it("rejects a partial acknowledgement so the caller can retain and retry its source", async () => {
    const partial = response();
    partial.items.pop();
    const client = { post: vi.fn().mockResolvedValue(partial) } as unknown as ApiClient;
    await expect(
      importPersonalWatchlist(client, items, "18a8a7e4-6f46-4f60-9e90-05f48e6fe2b1"),
    ).rejects.toThrow("HK:09618");
  });

  it("requests one latest daily bar using the existing instrument bars endpoint", () => {
    expect(personalWatchlistQuotePath("600519.SH")).toBe(
      "/v1/instrument-intelligence/600519.SH/bars",
    );
    expect(personalWatchlistQuoteQuery()).toEqual({ mode: "CURRENT", limit: "1" });
  });
});
