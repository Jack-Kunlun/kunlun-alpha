import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "@/lib/api-client";
import {
  refreshIntervalForMode,
  requestLimitPoolTerminal,
  type LimitPoolTerminalQuery,
} from "./use-limit-pool-terminal";

describe("limit-pool request policy", () => {
  it("joins the endpoint to the shared /api base exactly once", async () => {
    const get = vi.fn();
    const client: ApiClient = {
      get: <T>(path: string, query?: Record<string, string>) => {
        get(path, query);
        return Promise.resolve({} as T);
      },
      post: <TBody, TResponse>(_path: string, _body: TBody) => Promise.resolve({} as TResponse),
    };
    await requestLimitPoolTerminal(client, {
      mode: "CURRENT",
      algorithmVersion: "limit-pool-v2",
      ladderAlgorithmVersion: "board_ladder_v2",
      limitRuleVersion: "limit_rules_v1",
      materializerVersion: "limit-pool-terminal-materializer-v1",
    });
    expect(get).toHaveBeenCalledWith("/v1/limit-pool", {
      mode: "CURRENT",
      algorithmVersion: "limit-pool-v2",
      ladderAlgorithmVersion: "board_ladder_v2",
      limitRuleVersion: "limit_rules_v1",
      materializerVersion: "limit-pool-terminal-materializer-v1",
    });
  });

  it("polls current data but never historical snapshots", () => {
    expect(refreshIntervalForMode("CURRENT")).toBe(30_000);
    expect(refreshIntervalForMode("HISTORICAL")).toBeNull();
  });

  it("rejects a partial version vector without issuing a request", async () => {
    const get = vi.fn();
    const client: ApiClient = {
      get: <T>(path: string, query?: Record<string, string>) => {
        get(path, query);
        return Promise.resolve({} as T);
      },
      post: <TBody, TResponse>(_path: string, _body: TBody) => Promise.resolve({} as TResponse),
    };
    const partial = {
      mode: "CURRENT",
      algorithmVersion: "limit-pool-v2",
    } as LimitPoolTerminalQuery;

    await expect(requestLimitPoolTerminal(client, partial)).rejects.toThrow(
      "limit-pool version vector must be complete",
    );
    expect(get).not.toHaveBeenCalled();
  });
});
