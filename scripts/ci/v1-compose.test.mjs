import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const root = fileURLToPath(new URL("../../", import.meta.url));
const files = [
  "infra/docker/docker-compose.yml",
  "infra/docker/docker-compose.apps.yml",
  "infra/docker/docker-compose.v1.yml",
];

function configuration(profile = []) {
  const result = spawnSync(
    "docker",
    [
      "compose",
      ...files.flatMap((file) => ["-f", file]),
      "--env-file",
      "infra/docker/.env.example",
      ...profile.flatMap((name) => ["--profile", name]),
      "config",
      "--format",
      "json",
    ],
    {
      cwd: root,
      encoding: "utf8",
      env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot },
    },
  );
  assert.equal(result.status, 0, result.stderr || result.error?.message);
  return JSON.parse(result.stdout);
}

const required = [
  "clickhouse",
  "clickhouse-migrate",
  "data-worker-migrate",
  "local-terminal-reference-materialize",
  "postgres",
  "server",
  "server-migrate",
  "web",
];

test("dashboard and market sync share a single v1 daily symbol override", () => {
  const overlay = readFileSync(
    new URL("../../infra/docker/docker-compose.v1.yml", import.meta.url),
    "utf8",
  );
  const expressionFor = (name) => {
    const match = overlay.match(new RegExp(`^\\s+${name}:\\s*(\\$\\{[^\\n]+\\})\\s*$`, "m"));
    assert.ok(match, `${name} must use the v1 symbol override`);
    return match[1];
  };
  assert.equal(expressionFor("DASHBOARD_DAILY_SYMBOLS"), expressionFor("MARKET_DATA_SYMBOLS"));
});

test("default v1 startup contains only the research terminal and required dependencies", () => {
  const { services } = configuration();
  assert.deepEqual(Object.keys(services).sort(), required);
  for (const [name, service] of Object.entries(services)) {
    for (const dependency of Object.keys(service.depends_on ?? {})) {
      assert.ok(required.includes(dependency), `${name} starts deferred ${dependency}`);
    }
    assert.ok(!JSON.stringify(service).includes("data/fixtures"), `${name} imports fixtures`);
  }
});

test("v1 host ports are loopback-only and existing persistence is retained", () => {
  const { services, volumes } = configuration();
  for (const service of Object.values(services)) {
    for (const port of service.ports ?? []) assert.equal(port.host_ip, "127.0.0.1");
  }
  assert.equal(volumes["kunlun-clickhouse-data"].name, "kunlun-clickhouse-data");
  assert.ok(
    services.postgres.volumes.some(
      (mount) => mount.type === "bind" && mount.target === "/var/lib/postgresql/data",
    ),
  );
});

test("real market sync is explicit, raw-first, daily-only and bounded to the configured sample", () => {
  const { services, volumes } = configuration(["real-market-data"]);
  assert.deepEqual(Object.keys(services).sort(), [...required, "market-data-sync"].sort());
  const sync = services["market-data-sync"];
  assert.deepEqual(sync.command, ["market-data-sync"]);
  assert.equal(sync.environment.MARKET_DATA_PROVIDER, "akshare");
  assert.equal(
    services.server.environment.DASHBOARD_DAILY_SYMBOLS,
    sync.environment.MARKET_DATA_SYMBOLS,
  );
  assert.equal(sync.environment.MARKET_DATA_RUN_MODE, "once");
  assert.equal(sync.environment.MARKET_DATA_MINUTE_SYMBOLS, "");
  assert.equal(
    sync.environment.MARKET_DATA_SYMBOLS,
    "000001.SZ,002594.SZ,300750.SZ,301236.SZ,600000.SH,600519.SH,601318.SH,688981.SH",
  );
  assert.equal(sync.environment.MARKET_DATA_SETTINGS_URL, "");
  assert.equal(sync.environment.MARKET_DATA_RAW_ROOT, "/workspace/var/market-raw/v1-shares-v3");
  assert.equal(sync.environment.TUSHARE_TOKEN, "");
  assert.ok(sync.volumes.some((mount) => mount.source === "kunlun-market-raw"));
  assert.equal(volumes["kunlun-market-raw"].name, "kunlun-market-raw");
  assert.deepEqual(Object.keys(sync.depends_on), ["clickhouse-migrate"]);
});
