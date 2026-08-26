import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { ClickHouseLimitPoolRepository } from "./clickhouse-limit-pool.repository";

const payload = {
  tradingDate: "2026-08-25",
  previousTradingDate: "2026-08-24",
  completeness: "COMPLETE",
  missingReasons: [],
  limitUpCount: 1,
  limitDownCount: 0,
  sealedCount: 1,
  totalOpenCount: 0,
  ladder: [{ streakDays: 2, count: 1, previousDayEligibleCount: 2, promotedCount: 1 }],
  entries: [
    {
      instrumentId: "600000.SH",
      name: "浦发银行",
      exchange: "SH",
      listingBoard: "MAIN",
      isSt: false,
      side: "LIMIT_UP",
      state: "SEALED",
      streakDays: 2,
      previousStreakDays: 1,
      openCount: 0,
      priceCny: "11.00",
      previousCloseCny: "10.00",
      firstSealTime: "2026-08-25T01:31:00.000Z",
      lastSealTime: "2026-08-25T01:31:00.000Z",
      eventTime: "2026-08-25T01:31:00.000Z",
      availableTime: "2026-08-25T01:31:01.000Z",
      revision: 1,
      sourceVersion: "vendor-a:v7",
      evidenceId: "limit-600000-1",
    },
  ],
};

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function row(
  overrides: Record<string, unknown> = {},
  payloadValue: typeof payload = payload,
): string {
  const value = {
    trading_date: "2026-08-25",
    event_time_ms: 1787622300000,
    available_time_ms: 1787622301000,
    revision: 1,
    algorithm_version: "limit-pool-v2",
    ladder_algorithm_version: "board_ladder_v2",
    limit_rule_version: "cn-limit-rules-v1",
    materializer_version: "limit-pool-terminal-materializer-v1",
    source_versions: ["vendor-a:v7"],
    evidence_ids: ["limit-600000-1"],
    payload_json: JSON.stringify(payloadValue),
    ...overrides,
  };
  const digest = createHash("sha256")
    .update(
      canonicalJson({
        tradingDate: value.trading_date,
        eventTime: new Date(value.event_time_ms).toISOString(),
        availableTime: new Date(value.available_time_ms).toISOString(),
        revision: value.revision,
        algorithmVersion: value.algorithm_version,
        ladderAlgorithmVersion: value.ladder_algorithm_version,
        limitRuleVersion: value.limit_rule_version,
        materializerVersion: value.materializer_version,
        sourceVersions: value.source_versions,
        evidenceIds: value.evidence_ids,
        payload: payloadValue,
      }),
      "utf8",
    )
    .digest("hex");
  return JSON.stringify({ ...value, payload_digest: digest });
}

describe("ClickHouseLimitPoolRepository", () => {
  it("uses PIT parameters and parses the versioned payload", async () => {
    const fetcher = vi.fn(async () => new Response(row()));
    const repository = new ClickHouseLimitPoolRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      fetcher,
    );

    const snapshot = await repository.findSnapshot({
      asOf: "2026-08-25T06:45:00.000Z",
      algorithmVersion: "limit-pool-v2",
      ladderAlgorithmVersion: "board_ladder_v2",
      limitRuleVersion: "cn-limit-rules-v1",
      materializerVersion: "limit-pool-terminal-materializer-v1",
    });

    expect(snapshot?.payload.entries[0]?.instrumentId).toBe("600000.SH");
    expect(snapshot?.ladderAlgorithmVersion).toBe("board_ladder_v2");
    expect(snapshot?.materializerVersion).toBe("limit-pool-terminal-materializer-v1");
    const [url, init] = fetcher.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.searchParams.get("param_as_of")).toBe("2026-08-25T06:45:00.000Z");
    expect(url.searchParams.get("param_algorithm_version")).toBe("limit-pool-v2");
    expect(url.searchParams.get("param_ladder_algorithm_version")).toBe("board_ladder_v2");
    expect(url.searchParams.get("param_limit_rule_version")).toBe("cn-limit-rules-v1");
    expect(url.searchParams.get("param_materializer_version")).toBe(
      "limit-pool-terminal-materializer-v1",
    );
    expect(String(init.body)).toContain("available_time <= parseDateTime64BestEffort");
    expect(String(init.body)).toContain(
      "throwIf(uniqExact(tuple(c.trading_date, c.payload_digest, c.available_time, c.source_versions, c.evidence_ids, c.payload_json)) > 1",
    );
    expect(String(init.body)).toContain("any(c.payload_digest) AS payload_digest");
  });

  it("fails closed when algorithm versions are ambiguous", async () => {
    const repository = new ClickHouseLimitPoolRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => new Response(`${row()}\n${row({ algorithm_version: "limit-pool-v3" })}`),
    );
    await expect(repository.findSnapshot({ asOf: "2026-08-25T06:45:00.000Z" })).rejects.toThrow(
      "ambiguous limit-pool algorithm version",
    );
  });

  it("rejects malformed provider payloads without leaking their body", async () => {
    const repository = new ClickHouseLimitPoolRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => new Response('{"payload_json":"{secret}"}'),
    );
    await expect(repository.findSnapshot({ asOf: "2026-08-25T06:45:00.000Z" })).rejects.toThrow(
      "invalid ClickHouse limit-pool row",
    );
  });

  it("fails closed when the stored payload digest does not match the canonical envelope", async () => {
    const tampered = JSON.parse(row()) as Record<string, unknown>;
    tampered.payload_json = JSON.stringify({ ...payload, limitUpCount: 99 });
    const repository = new ClickHouseLimitPoolRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => new Response(JSON.stringify(tampered)),
    );
    await expect(repository.findSnapshot({ asOf: "2026-08-25T06:45:00.000Z" })).rejects.toThrow(
      "payload_digest",
    );
  });

  it.each([
    ["priceCny", "0"],
    ["priceCny", "-Infinity"],
    ["previousCloseCny", "0"],
    ["previousCloseCny", "Infinity"],
  ] as const)("rejects invalid positive decimal field %s=%s", async (field, invalidValue) => {
    const invalidPayload = {
      ...payload,
      entries: [{ ...payload.entries[0]!, [field]: invalidValue }],
    };
    const repository = new ClickHouseLimitPoolRepository(
      { url: "http://localhost:8123", database: "kunlun", user: "reader" },
      async () => new Response(row({}, invalidPayload)),
    );
    await expect(repository.findSnapshot({ asOf: "2026-08-25T06:45:00.000Z" })).rejects.toThrow(
      "invalid ClickHouse limit-pool row",
    );
  });
});
