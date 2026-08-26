#!/usr/bin/env node

import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const endpoint = process.env.CLICKHOUSE_URL ?? "http://127.0.0.1:8123";
const user = process.env.CLICKHOUSE_USER ?? "default";
const password = process.env.CLICKHOUSE_PASSWORD;
const database = `kunlun_p6n03_runtime_${randomUUID().replaceAll("-", "")}`;
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
  if (!result.response.ok) {
    throw new Error(`ClickHouse runtime smoke query failed (${result.response.status})`);
  }
  return result.body.trim();
}

async function runMaterializer() {
  await new Promise((resolvePromise, reject) => {
    let diagnostics = "";
    const child = spawn(
      "uv",
      ["run", "--offline", "--package", "data-worker", "limit-pool-terminal-materialize"],
      {
        cwd: root,
        env: {
          ...process.env,
          LIMIT_POOL_TERMINAL_REQUEST_FILE: resolve(
            root,
            "data/fixtures/limit-pool-terminal-local.json",
          ),
          CLICKHOUSE_URL: endpoint,
          CLICKHOUSE_DATABASE: database,
          CLICKHOUSE_USER: user,
          ...(password ? { CLICKHOUSE_PASSWORD: password } : {}),
          CLICKHOUSE_TIMEOUT_SECONDS: "5",
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    const collect = (chunk) => {
      diagnostics = `${diagnostics}${String(chunk)}`.slice(-4000);
    };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.once("error", () => reject(new Error("limit-pool materializer failed to start")));
    child.once("exit", (code) => {
      if (code === 0) resolvePromise();
      else {
        const safeDiagnostics = password
          ? diagnostics.replaceAll(password, "[redacted]")
          : diagnostics;
        reject(
          new Error(
            `limit-pool materializer failed (${code ?? "signal"}): ${safeDiagnostics.trim() || "no diagnostics"}`,
          ),
        );
      }
    });
  });
}

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
    .filter(Boolean)) {
    await must(statement);
  }

  await runMaterializer();
  const result = await must(
    "SELECT count(), any(algorithm_version), any(ladder_algorithm_version), any(limit_rule_version), any(materializer_version), any(source_versions[1]), any(evidence_ids[1]) FROM limit_pool_terminal_snapshots_v2",
  );
  const expected =
    "1\tlimit_pool_v2\tboard_ladder_v2\tcn-equity-limit-rules-v1\tlimit-pool-terminal-materializer-v1\tsanitized-local-fixture:v1\tfixture-limit-600000-1";
  if (result !== expected)
    throw new Error("materialized runtime row did not match canonical fixture");
  process.stdout.write(`Limit-pool runtime smoke passed (${database})\n`);
} finally {
  if (owned) await must(`DROP DATABASE \`${database}\``, "default");
}
