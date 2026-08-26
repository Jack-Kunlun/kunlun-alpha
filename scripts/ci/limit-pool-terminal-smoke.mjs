#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const endpoint = process.env.CLICKHOUSE_URL ?? "http://127.0.0.1:8123";
const user = process.env.CLICKHOUSE_USER ?? "default";
const password = process.env.CLICKHOUSE_PASSWORD;
const database = `kunlun_p6n03_${randomUUID().replaceAll("-", "")}`;
let owned = false;

function headers() {
  return {
    "content-type": "text/plain; charset=utf-8",
    "x-clickhouse-user": user,
    ...(password ? { "x-clickhouse-key": password } : {}),
  };
}

async function request(sql, target = database) {
  const url = new URL(endpoint);
  url.searchParams.set("database", target);
  const response = await fetch(url, { method: "POST", headers: headers(), body: sql });
  return { response, body: await response.text() };
}

async function must(sql, target = database) {
  const result = await request(sql, target);
  if (!result.response.ok)
    throw new Error(`ClickHouse smoke query failed (${result.response.status})`);
  return result.body.trim();
}

function payload(limitUpCount = 1) {
  return {
    tradingDate: "2026-08-25",
    previousTradingDate: "2026-08-24",
    completeness: "COMPLETE",
    missingReasons: [],
    limitUpCount,
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
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object")
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  return JSON.stringify(value);
}

function clickhouseTimeToIso(value) {
  return `${value.replace(" ", "T")}Z`;
}

function row(revision, availableTime, value, overrides = {}) {
  const result = {
    snapshot_id: "p6n03-smoke",
    trading_date: "2026-08-25",
    event_time: "2026-08-25 06:40:00.000",
    available_time: availableTime,
    revision,
    algorithm_version: "limit_pool_v2",
    ladder_algorithm_version: "board_ladder_v2",
    limit_rule_version: "limit_rules_v1",
    materializer_version: "limit-pool-terminal-materializer-v1",
    source_versions: ["vendor-a:v7"],
    evidence_ids: ["limit-600000-1"],
    payload_json: JSON.stringify(value),
    processing_time: "2026-08-25 06:40:02.000",
    replacement_version: revision + 1,
    ...overrides,
  };
  result.payload_digest = createHash("sha256")
    .update(
      canonicalJson({
        tradingDate: result.trading_date,
        eventTime: clickhouseTimeToIso(result.event_time),
        availableTime: clickhouseTimeToIso(result.available_time),
        revision: result.revision,
        algorithmVersion: result.algorithm_version,
        ladderAlgorithmVersion: result.ladder_algorithm_version,
        limitRuleVersion: result.limit_rule_version,
        materializerVersion: result.materializer_version,
        sourceVersions: result.source_versions,
        evidenceIds: result.evidence_ids,
        payload: value,
      }),
      "utf8",
    )
    .digest("hex");
  return JSON.stringify(result);
}

const pitQuery = `WITH
  toDateTime64('2026-08-25 06:42:00.000', 3, 'UTC') AS cutoff,
  candidates AS (SELECT * FROM limit_pool_terminal_snapshots_v2 WHERE event_time <= cutoff AND available_time <= cutoff),
  latest_event AS (SELECT max(event_time) AS value FROM candidates),
  latest_revision AS (SELECT algorithm_version, ladder_algorithm_version, limit_rule_version, materializer_version, max(revision) AS value FROM candidates WHERE event_time = (SELECT value FROM latest_event) GROUP BY algorithm_version, ladder_algorithm_version, limit_rule_version, materializer_version)
SELECT c.revision, throwIf(uniqExact(tuple(c.trading_date, c.payload_digest, c.available_time, c.source_versions, c.evidence_ids, c.payload_json)) > 1, 'conflicting limit-pool immutable snapshot')
FROM candidates c INNER JOIN latest_revision r ON c.algorithm_version = r.algorithm_version AND c.ladder_algorithm_version = r.ladder_algorithm_version AND c.limit_rule_version = r.limit_rule_version AND c.materializer_version = r.materializer_version AND c.revision = r.value
WHERE c.event_time = (SELECT value FROM latest_event)
GROUP BY c.event_time, c.revision, c.algorithm_version, c.ladder_algorithm_version, c.limit_rule_version, c.materializer_version`;

try {
  await must(`CREATE DATABASE \`${database}\``, "default");
  owned = true;
  const migration = await readFile(
    resolve(root, "infra/clickhouse/migrations/005_limit_pool_terminal.sql"),
    "utf8",
  );
  for (const statement of migration
    .replace(/^--.*$/gm, "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean))
    await must(statement);
  await must(
    `INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n${row(1, "2026-08-25 06:40:01.000", payload())}`,
  );
  await must(
    `INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n${row(1, "2026-08-25 06:40:01.000", payload(), { algorithm_version: "limit_pool_v3" })}`,
  );
  await must(
    `INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n${row(2, "2026-08-25 07:00:00.000", payload(9))}`,
  );
  await must("OPTIMIZE TABLE limit_pool_terminal_snapshots_v2 FINAL");
  const survivingVectors = await must(
    "SELECT count() FROM limit_pool_terminal_snapshots_v2 WHERE event_time = toDateTime64('2026-08-25 06:40:00.000', 3, 'UTC') AND revision = 1",
  );
  if (survivingVectors !== "2")
    throw new Error("distinct complete version vectors were deduplicated");
  const early = await must(pitQuery);
  const earlyRows = early.split(/\r?\n/).filter(Boolean);
  if (earlyRows.length !== 2 || earlyRows.some((line) => !line.startsWith("1\t"))) {
    throw new Error("future revision leaked into PIT snapshot");
  }
  await must(
    `INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n${row(1, "2026-08-25 06:40:01.000", payload(), { source_versions: ["vendor-b:v1"], evidence_ids: ["limit-600000-b"] })}`,
  );
  await must("OPTIMIZE TABLE limit_pool_terminal_snapshots_v2 FINAL");
  const conflict = await request(pitQuery);
  if (conflict.response.ok)
    throw new Error("same-revision immutable metadata conflict returned a winner");
  process.stdout.write(`Limit-pool terminal smoke passed (${database})\n`);
} finally {
  if (owned) await must(`DROP DATABASE \`${database}\``, "default");
}
