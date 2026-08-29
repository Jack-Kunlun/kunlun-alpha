import { describe, expect, it } from "vitest";
import { ClickHouseDashboardRepository } from "./clickhouse-dashboard.repository";

describe("ClickHouseDashboardRepository", () => {
  it("loads point-in-time bars and emotion while preserving decimal money", async () => {
    const sqlBodies: string[] = [];
    const fetcher = async (_input: string | URL, init?: RequestInit): Promise<Response> => {
      const sql = String(init?.body ?? "");
      sqlBodies.push(sql);
      if (sql.includes("AS instrument_id")) {
        return new Response(
          JSON.stringify({
            instrument_id: "000001.SH",
            value: "3030.0000",
            previous_close: "3000.0000",
            data_time: "2026-08-25T06:59:00.000Z",
            source_version: "bars-v2",
            evidence_id: "a".repeat(64),
          }) + "\n",
        );
      }
      if (sql.includes("advancing_count")) {
        return new Response(
          JSON.stringify({
            advancing_count: 2,
            declining_count: 1,
            unchanged_count: 1,
            suspended_count: 0,
            sample_size: 4,
            turnover_cny: "9007199254740993.25",
            data_time: "2026-08-25T06:59:00.000Z",
            source_versions: ["bars-v2"],
            evidence_ids: ["b".repeat(64)],
          }) + "\n",
        );
      }
      return new Response(
        JSON.stringify({
          data_time: "2026-08-25T06:59:00.000Z",
          score_bps: 5100,
          confidence_bps: 8200,
          sample_size: 200,
          algorithm_version: "emotion-score-v1",
          source_versions: ["limit-v2"],
          evidence_ids: ["c".repeat(64)],
        }) + "\n",
      );
    };
    const repository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
      },
      fetcher,
    );
    const result = await repository.loadMarketOverview("2026-08-25T07:00:00.000Z");
    expect(result.indices[0]?.changeBps).toBe(100);
    expect(result.turnover?.amountCny).toBe("9007199254740993.25");
    expect(result.emotion?.scoreBps).toBe(5100);
    expect(sqlBodies).toHaveLength(3);
    expect(sqlBodies.every((sql) => sql.includes("available_time <= cutoff"))).toBe(true);
    expect(sqlBodies.every((sql) => sql.includes("processing_time <= cutoff"))).toBe(true);
    expect(sqlBodies.every((sql) => sql.includes("event_time <= cutoff"))).toBe(true);
    expect(sqlBodies.every((sql) => sql.includes("throwIf"))).toBe(true);
    expect(
      sqlBodies
        .filter((sql) => sql.includes("bars_minute_v2"))
        .every((sql) =>
          sql.includes(
            "GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version",
          ),
        ),
    ).toBe(true);
    expect(sqlBodies.some((sql) => sql.includes("toString(min(data_time))"))).toBe(true);
    expect(sqlBodies.every((sql) => !sql.includes("%3f"))).toBe(true);
    expect(
      sqlBodies.some((sql) => sql.includes("algorithm_version = {emotionVersion:String}")),
    ).toBe(true);
    expect(sqlBodies.some((sql) => sql.includes("toFloat64(identity_confidence)"))).toBe(true);
  });

  it("selects a complete winner across known sources after PIT filtering", async () => {
    const sqlBodies: string[] = [];
    const fetcher = async (_input: string | URL, init?: RequestInit): Promise<Response> => {
      sqlBodies.push(String(init?.body ?? ""));
      return new Response("");
    };
    const repository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
      },
      fetcher,
    );

    await expect(repository.loadMarketOverview("2026-08-25T07:00:00.000Z")).resolves.toMatchObject({
      indices: [],
      breadth: null,
      turnover: null,
      emotion: null,
    });

    const marketSql = sqlBodies.find((sql) => sql.includes("advancing_count"));
    const indexSql = sqlBodies.find((sql) => sql.includes("AS instrument_id"));
    expect(marketSql).toBeDefined();
    expect(indexSql).toBeDefined();
    for (const sql of [marketSql, indexSql]) {
      expect(sql).toContain("source = 'tushare-pro'");
      expect(sql).toContain("source IN ('akshare-tencent', 'akshare-sina')");
      expect(sql).toContain("source = 'akshare-eastmoney'");
      expect(sql).toContain("argMax(identity_values");
      expect(sql).toContain("tuple(identity_replacement_version, source_priority");
      expect(sql).not.toContain("tuple(source_priority, identity_replacement_version");
      expect(sql).not.toContain("bar source identity conflict");
      expect(sql).not.toContain("daily bar source identity conflict");
      expect(sql).toContain(
        "throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict')",
      );
    }

    expect(marketSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)).1 AS event_close",
    );
    expect(marketSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)).2 AS event_amount",
    );
    expect(marketSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)).3 AS event_suspended",
    );
    expect(marketSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)).4 AS event_source_version",
    );
    expect(marketSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type)).5 AS event_evidence_id",
    );
    expect(indexSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type, toString(event_time))).1 AS event_close",
    );
    expect(indexSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type, toString(event_time))).2 AS event_source_version",
    );
    expect(indexSql).toContain(
      "argMax(identity_values, tuple(identity_replacement_version, source_priority, source, source_version, data_version, interval, session, price_type, toString(event_time))).3 AS event_evidence_id",
    );
  });

  it("applies event and availability PIT filters before source selection", async () => {
    const sqlBodies: string[] = [];
    const fetcher = async (_input: string | URL, init?: RequestInit): Promise<Response> => {
      sqlBodies.push(String(init?.body ?? ""));
      return new Response("");
    };
    const repository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
      },
      fetcher,
    );

    await repository.loadMarketOverview("2026-08-25T07:00:00.000Z");

    for (const sql of sqlBodies.filter((body) => body.includes("bars_"))) {
      const pitFilter = sql.indexOf(
        "event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
      );
      const sourceSelection = sql.indexOf("argMax(identity_values");
      expect(pitFilter).toBeGreaterThanOrEqual(0);
      expect(sourceSelection).toBeGreaterThan(pitFilter);
    }
  });

  it("propagates ClickHouse disconnection instead of returning fake empties", async () => {
    const repository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
      },
      async () => new Response("unavailable", { status: 503 }),
    );
    await expect(repository.loadMarketOverview("2026-08-25T07:00:00.000Z")).rejects.toThrow(
      "ClickHouse dashboard query failed (503)",
    );
  });

  it("bounds a hanging ClickHouse request", async () => {
    const repository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5,
      },
      async (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
    );
    await expect(repository.loadMarketOverview("2026-08-25T07:00:00.000Z")).rejects.toThrow(
      "timed out after 5ms",
    );
  });
});
