import { ApiError, type ApiClient } from "@/lib/api-client";
import { describe, expect, it } from "vitest";
import { LOCAL_TERMINAL_STOCKS } from "../instrument/local-terminal-stock-samples";
import { instrumentBarsPath, instrumentBarsQuery } from "../instrument/use-instrument-bars";
import { loadDailyComparison } from "./use-daily-comparison";

const AS_OF = "2026-10-16T16:00:00.000Z";

function emptyResponse(instrumentId: string) {
  return {
    schemaVersion: "instrument-bars-v1",
    dataMeaning: "RESEARCH_ONLY_NO_REAL_ORDER_PATH",
    instrumentId,
    mode: "HISTORICAL",
    requestedAsOf: AS_OF,
    effectiveAsOf: AS_OF,
    interval: "DAILY",
    priceType: "RAW",
    status: "EMPTY",
    barCount: 0,
    dataCutoffTime: null,
    freshnessSeconds: null,
    bars: [],
    sourceVersions: [],
    evidenceIds: [],
  };
}

describe("loadDailyComparison", () => {
  it("requests the eight configured samples at one historical point with two visible bars", async () => {
    const calls: { path: string; query: Record<string, string> | undefined }[] = [];
    const client: ApiClient = {
      async get<T>(path: string, query?: Record<string, string>): Promise<T> {
        calls.push({ path, query });
        const instrumentId = LOCAL_TERMINAL_STOCKS.find((stock) =>
          path.endsWith(encodeURIComponent(stock.instrumentId) + "/bars"),
        )?.instrumentId;
        if (instrumentId === undefined) throw new Error("unexpected path");
        return emptyResponse(instrumentId) as T;
      },
      async post<_TBody, TResponse>(): Promise<TResponse> {
        throw new Error("unexpected post");
      },
    };

    const data = await loadDailyComparison(AS_OF, client);

    expect(calls).toHaveLength(8);
    expect(calls).toEqual(
      LOCAL_TERMINAL_STOCKS.map((stock) => ({
        path: instrumentBarsPath(stock.instrumentId),
        query: instrumentBarsQuery(AS_OF, 2),
      })),
    );
    expect(data.rows.every((row) => row.status === "EMPTY")).toBe(true);
  });

  it("isolates forbidden and failed rows while keeping the other sample responses", async () => {
    const client: ApiClient = {
      async get<T>(path: string): Promise<T> {
        if (path.endsWith("000001.SZ/bars")) throw new ApiError("无权访问", 403);
        if (path.endsWith("002594.SZ/bars")) throw new Error("connection failed");
        const instrumentId = LOCAL_TERMINAL_STOCKS.find((stock) =>
          path.endsWith(encodeURIComponent(stock.instrumentId) + "/bars"),
        )?.instrumentId;
        if (instrumentId === undefined) throw new Error("unexpected path");
        return emptyResponse(instrumentId) as T;
      },
      async post<_TBody, TResponse>(): Promise<TResponse> {
        throw new Error("unexpected post");
      },
    };

    const data = await loadDailyComparison(AS_OF, client);

    expect(data.rows.map((row) => row.status)).toEqual([
      "FORBIDDEN",
      "ERROR",
      "EMPTY",
      "EMPTY",
      "EMPTY",
      "EMPTY",
      "EMPTY",
      "EMPTY",
    ]);
  });
});
