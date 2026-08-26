import type { Pool } from "pg";
import { describe, expect, it } from "vitest";
import { PostgresEventIntelligenceRepository } from "./postgres-event-intelligence.repository";

describe("PostgresEventIntelligenceRepository", () => {
  it("uses bounded parameterized event filters", async () => {
    const calls: Array<{ sql: string; params: unknown[] }> = [];
    const pool = {
      query: async (sql: string, params: unknown[]) => {
        calls.push({ sql, params });
        return { rows: [] };
      },
    } as unknown as Pool;
    const repository = new PostgresEventIntelligenceRepository(pool);
    await repository.queryEvents({
      instrumentId: "600519.SH",
      minimumConfidenceBps: 7000,
      eventIds: ["a".repeat(64)],
      asOf: "2026-08-24T03:00:00.000Z",
      limit: 20,
    });
    expect(calls[0]?.params).toEqual([
      null,
      null,
      null,
      "600519.SH",
      7000,
      ["a".repeat(64)],
      "2026-08-24T03:00:00.000Z",
      20,
    ]);
    expect(calls[0]?.sql).toContain("AT TIME ZONE 'Asia/Shanghai'");
    expect(calls[0]?.sql).toContain("event_id = ANY($6::text[])");
    expect(calls[0]?.sql).toContain("available_time <= $7::timestamptz");
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

  it("fails closed on incomplete persisted event and hotspot payloads", async () => {
    const pool = {
      query: async () => ({ rows: [{ payload: { schemaVersion: "market-event-v1" } }] }),
    } as unknown as Pool;
    const repository = new PostgresEventIntelligenceRepository(pool);
    await expect(repository.queryEvents({ limit: 1 })).rejects.toThrow(
      "persisted MarketEvent payload is invalid",
    );
    await expect(
      repository.queryHotTopics({ asOf: "2026-08-24T03:00:00.000Z", limit: 1 }),
    ).rejects.toThrow("persisted HotTopicSnapshot payload is invalid");
  });
});
