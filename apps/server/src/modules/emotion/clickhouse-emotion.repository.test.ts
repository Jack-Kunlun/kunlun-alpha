import { describe, expect, it, vi } from "vitest";
import { ClickHouseEmotionRepository } from "./clickhouse-emotion.repository";

function response(body: string, status = 200): Response {
  return new Response(body, { status });
}

describe("ClickHouseEmotionRepository", () => {
  it("uses parameterized filters and validates snapshot rows", async () => {
    const fetcher = vi.fn(async () =>
      response(
        JSON.stringify({
          date: "2026-08-13",
          timestamp: "2026-08-13T01:30:00.000Z",
          score: 0.4,
          algorithm_version: "emotion_score_v1",
          ladder_json: JSON.stringify([{ board: 2, count: 3 }]),
          freshness_seconds: 12,
          sample_size: 100,
          confidence: 0.9,
          source_versions: ["limit-v2"],
          evidence_ids: ["snapshot-1"],
        }),
      ),
    );
    const repository = new ClickHouseEmotionRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      fetcher,
    );
    const rows = await repository.querySnapshots({
      date: "2026-08-13",
      asOf: "2026-08-13T15:59:59.999Z",
      algorithmVersion: "emotion_score_v1",
    });
    expect(rows[0]?.algorithmVersion).toBe("emotion_score_v1");
    const url = (fetcher.mock.calls as unknown as [[URL]])[0][0];
    expect(url.searchParams.get("param_date")).toBe("2026-08-13");
    expect(url.searchParams.get("param_version")).toBe("emotion_score_v1");
  });

  it("applies the persisted available_time cutoff to both replay sources", async () => {
    const fetcher = vi.fn(async () => response(""));
    const repository = new ClickHouseEmotionRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      fetcher,
    );
    const query = { date: "2026-08-13", asOf: "2026-08-13T02:00:00.000Z" };
    await repository.querySnapshots(query);
    await repository.queryRotationEvents(query);

    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetcher.mock.calls as unknown as [
      [URL, RequestInit],
      [URL, RequestInit],
    ]) {
      expect(url.searchParams.get("param_asOf")).toBe(query.asOf);
      expect(init.body).toContain("available_time <= parseDateTime64BestEffort");
    }
  });

  it("fails closed on invalid provider output", async () => {
    const repository = new ClickHouseEmotionRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => response('{"score":"not-a-number"}'),
    );
    await expect(
      repository.querySnapshots({
        date: "2026-08-13",
        asOf: "2026-08-13T15:59:59.999Z",
      }),
    ).rejects.toThrow("invalid ClickHouse replay field");
  });

  it("reports only controlled status on ClickHouse failure", async () => {
    const repository = new ClickHouseEmotionRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => response("secret backend detail", 503),
    );
    await expect(repository.listVersions()).rejects.toThrow("ClickHouse replay query failed (503)");
  });
});
