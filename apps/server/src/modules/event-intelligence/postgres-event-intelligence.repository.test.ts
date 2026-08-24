import type { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { PostgresEventIntelligenceRepository } from "./postgres-event-intelligence.repository";

describe("PostgresEventIntelligenceRepository", () => {
  it("uses bounded parameterized event filters", async () => {
    const calls: unknown[][] = [];
    const pool = {
      query: async (_sql: string, params: unknown[]) => {
        calls.push(params);
        return { rows: [] };
      },
    } as unknown as Pool;
    const repository = new PostgresEventIntelligenceRepository(pool);
    await repository.queryEvents({
      instrumentId: "600519.SH",
      minimumConfidenceBps: 7000,
      limit: 20,
    });
    expect(calls[0]).toEqual([null, null, null, "600519.SH", 7000, 20]);
  });

  it("binds the required point-in-time topic cutoff", async () => {
    const calls: unknown[][] = [];
    const pool = {
      query: async (_sql: string, params: unknown[]) => {
        calls.push(params);
        return { rows: [] };
      },
    } as unknown as Pool;
    const repository = new PostgresEventIntelligenceRepository(pool);
    await repository.queryHotTopics({ asOf: "2026-08-24T03:00:00.000Z", limit: 10 });
    expect(calls[0]).toEqual(["2026-08-24T03:00:00.000Z", null, null, 10]);
  });
});
