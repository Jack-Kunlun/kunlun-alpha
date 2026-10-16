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

  it("uses the latest shared date when configured symbols have staggered visible dates", async () => {
    const requests: Array<{ url: URL; sql: string }> = [];
    const fetcher = async (input: string | URL, init?: RequestInit): Promise<Response> => {
      requests.push({ url: new URL(input), sql: String(init?.body ?? "") });
      return new Response(
        JSON.stringify({
          advancing_count: 1,
          declining_count: 0,
          unchanged_count: 0,
          suspended_count: 1,
          sample_size: 2,
          turnover_cny: "9007199254740993.25",
          data_time: "2026-08-25T07:00:00.000Z",
          source_versions: ["source-current-v1", "source-previous-v2"],
          evidence_ids: ["evidence-current", "evidence-previous"],
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
        dailySymbols: ["600519.SH", "000001.SZ"],
      },
      fetcher,
    );

    const result = await repository.loadMarketOverview("2026-08-25T08:00:00.000Z");

    expect(requests).toHaveLength(1);
    expect(requests[0]?.url.searchParams.get("param_asOf")).toBe("2026-08-25T08:00:00.000Z");
    expect(requests[0]?.url.searchParams.get("param_symbol0")).toBe("600519.SH");
    expect(requests[0]?.url.searchParams.get("param_symbol1")).toBe("000001.SZ");
    const sql = requests[0]?.sql ?? "";
    expect(sql).toContain("FROM bars_daily_v2");
    expect(sql).not.toContain("bars_minute_v2");
    expect(sql).not.toContain("emotion_snapshots_v1");
    expect(sql).toContain("unified_code IN ({symbol0:String}, {symbol1:String})");
    expect(sql).toContain("interval = 'DAILY' AND price_type = 'RAW'");
    expect(sql).toContain(
      "event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
    );
    expect(sql).toContain(
      "throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict')",
    );
    const pointInTimeFilter = sql.indexOf(
      "event_time <= cutoff AND available_time <= cutoff AND processing_time <= cutoff",
    );
    const sourceSelection = sql.indexOf("argMax(identity_values");
    expect(sourceSelection).toBeGreaterThan(pointInTimeFilter);
    expect(sql).toContain("tuple(identity_replacement_version, source_priority, source");
    expect(sql).toContain(".4 AS selected_event_time");
    expect(sql).not.toContain(".4 AS event_time");
    expect(sql).toContain(
      "event_amount, event_suspended, selected_event_time, event_source_version",
    );
    const commonVisibleDates = sql.indexOf("common_visible_dates AS (");
    expect(commonVisibleDates).toBeGreaterThan(sourceSelection);
    expect(sql).toContain(
      "SELECT date FROM daily_events GROUP BY date HAVING uniqExact(unified_code) = 2",
    );
    expect(sql).toContain("max(date) AS latest_common_date");
    expect(sql).toContain("FROM common_visible_dates HAVING count() > 0");
    expect(sql).toContain("indexOf(dates, latest_common_date) AS current_index");
    expect(sql).toContain("FROM sample_indices WHERE current_index > 1");
    expect(sql).toContain("tupleElement(current_record, 1) > tupleElement(previous_record, 1)");
    expect(sql).toContain("toString(sum(tupleElement(current_record, 3))) AS turnover_cny");
    expect(sql).not.toMatch(/toFloat(?:32|64)/);
    expect(result).toMatchObject({
      indices: [],
      breadth: { sampleSize: 2, suspendedCount: 1 },
      turnover: { amountCny: "9007199254740993.25", sampleSize: 2 },
      emotion: null,
      sourceVersions: ["source-current-v1", "source-previous-v2"],
      evidenceIds: ["evidence-current", "evidence-previous"],
    });
    expect(result.breadth?.dataTime).toBe("2026-08-25T07:00:00.000Z");
  });

  it("keeps daily empty samples null and propagates daily query failures", async () => {
    const dailySymbols = ["600519.SH"];
    const emptyRepository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
        dailySymbols,
      },
      async () => new Response(""),
    );
    await expect(
      emptyRepository.loadMarketOverview("2026-08-25T08:00:00.000Z"),
    ).resolves.toMatchObject({
      indices: [],
      breadth: null,
      turnover: null,
      emotion: null,
      sourceVersions: [],
      evidenceIds: [],
    });

    const failingRepository = new ClickHouseDashboardRepository(
      {
        url: "http://clickhouse.test:8123",
        database: "kunlun",
        user: "reader",
        emotionAlgorithmVersion: "emotion_score_v1",
        timeoutMs: 5_000,
        dailySymbols,
      },
      async () => new Response("unavailable", { status: 503 }),
    );
    await expect(failingRepository.loadMarketOverview("2026-08-25T08:00:00.000Z")).rejects.toThrow(
      "ClickHouse dashboard query failed (503)",
    );
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
