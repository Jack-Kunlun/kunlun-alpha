import type { RankingTerminalSnapshot } from "@kunlun/shared-types";

export interface RankingEngineClient {
  latest(asOf: string | null): Promise<RankingTerminalSnapshot>;
}

export class RankingEngineHttpError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "RankingEngineHttpError";
  }
}

export class HttpRankingEngineClient implements RankingEngineClient {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
  ) {}

  async latest(asOf: string | null): Promise<RankingTerminalSnapshot> {
    const url = new URL("/v1/ranking/snapshots/latest", this.baseUrl);
    if (asOf !== null) url.searchParams.set("asOf", asOf);
    let response: Response;
    try {
      response = await fetch(url, { signal: AbortSignal.timeout(this.timeoutMs) });
    } catch (error) {
      throw new RankingEngineHttpError(
        error instanceof Error ? error.message : "quant-engine unavailable",
        503,
      );
    }
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { message?: unknown } | null;
      throw new RankingEngineHttpError(
        typeof payload?.message === "string" ? payload.message : `HTTP ${response.status}`,
        response.status,
      );
    }
    return (await response.json()) as RankingTerminalSnapshot;
  }
}
