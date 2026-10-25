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

function configuration(profile = [], extraFiles = [], extraEnv = {}) {
  const result = spawnSync(
    "docker",
    [
      "compose",
      ...[...files, ...extraFiles].flatMap((file) => ["-f", file]),
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
      env: { PATH: process.env.PATH, SystemRoot: process.env.SystemRoot, ...extraEnv },
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
  "quant-engine",
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

test("paper account mode starts a durable engine without publishing its write endpoints", () => {
  const { services, volumes } = configuration();
  const engine = services["quant-engine"];
  assert.ok(engine);
  assert.ok(!engine.ports?.length);
  assert.equal(engine.environment.KUNLUN_QUANT_STATE_DIR, "/var/lib/kunlun/quant-engine");
  const mount = engine.volumes.find((item) => item.target === "/var/lib/kunlun/quant-engine");
  assert.equal(volumes[mount.source].name, "kunlun-quant-state");
  assert.equal(services.server.environment.PAPER_TERMINAL_ACCOUNT_ONLY, "true");
  assert.equal(services.server.environment.PAPER_TERMINAL_CONTROLLED_BUY_ENABLED, "true");
  assert.equal(engine.environment.KUNLUN_PAPER_CONTROLLED_BUY_ENABLED, "true");
  assert.equal(services.server.depends_on["quant-engine"].condition, "service_healthy");
});

test("paper buys can be disabled on both boundaries while legacy execution and host ports stay closed", () => {
  const { services } = configuration([], [], { V1_PAPER_BUY_ENABLED: "false" });
  assert.equal(services.server.environment.PAPER_TERMINAL_CONTROLLED_BUY_ENABLED, "false");
  assert.equal(services["quant-engine"].environment.KUNLUN_PAPER_CONTROLLED_BUY_ENABLED, "false");
  assert.equal(services.server.environment.PAPER_TERMINAL_ACCOUNT_ONLY, "true");
  assert.ok(!services["quant-engine"].ports?.length);
});

test("real market sync is explicit, raw-first, daily-only and bounded to the configured sample", () => {
  const { services, volumes } = configuration(["real-market-data"]);
  assert.deepEqual(
    Object.keys(services).sort(),
    [...required, "market-data-sync", "watchlist-market-data-sync"].sort(),
  );
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
  const watchlist = services["watchlist-market-data-sync"];
  assert.deepEqual(watchlist.command, ["personal-watchlist-sync"]);
  assert.equal(watchlist.image, sync.image);
  assert.equal(watchlist.environment.MARKET_DATA_SYMBOLS, undefined);
  assert.equal(watchlist.environment.MARKET_DATA_SETTINGS_WORKER_TOKEN, undefined);
  assert.equal(
    watchlist.environment.MARKET_DATA_RAW_ROOT,
    "/workspace/var/market-raw/personal-watchlist-v1",
  );
  assert.ok(watchlist.environment.KUNLUN_POSTGRES_DSN);
  assert.ok(watchlist.volumes.some((mount) => mount.source === "kunlun-market-raw"));
  assert.ok(!services.server.volumes.some((mount) => mount.source === "kunlun-market-raw"));
});

test("task status shares sanitized metadata read-only without giving the server raw access", () => {
  const { services } = configuration(["real-market-data"]);
  const target = "/workspace/var/market-status-public";
  const reader = services.server.volumes.find((mount) => mount.target === target);
  const writer = services["market-data-sync"].volumes.find((mount) => mount.target === target);
  assert.ok(reader && writer);
  assert.equal(reader.source, writer.source);
  assert.equal(reader.read_only, true);
  assert.notEqual(writer.read_only, true);
  assert.equal(services.server.environment.MARKET_DATA_STATUS_PUBLIC_ROOT, target);
  assert.equal(services["market-data-sync"].environment.MARKET_DATA_STATUS_PUBLIC_ROOT, target);
  assert.ok(!services.server.volumes.some((mount) => mount.source === "kunlun-market-raw"));
  assert.equal(services["market-data-sync"].environment.MARKET_DATA_RUN_MODE, "once");
});

test("daily quality reads the existing sanitized evidence volume without raw access", () => {
  const { services, volumes } = configuration();
  const target = "/workspace/var/market-quality-public";
  const reader = services.server.volumes.find((mount) => mount.target === target);
  assert.equal(services.server.environment.MARKET_DATA_QUALITY_PUBLIC_ROOT, target);
  assert.ok(reader);
  assert.equal(reader.read_only, true);
  assert.equal(volumes[reader.source].name, "kunlun-market-quality-public");
  assert.ok(!services.server.volumes.some((mount) => mount.source === "kunlun-market-raw"));
  assert.ok(!Object.keys(services).includes("market-quality-evidence-export"));
});

test("optional daily scheduling reuses the v1 sample, checkpoint and public status", () => {
  const { services } = configuration(
    ["real-market-data"],
    ["infra/docker/docker-compose.v1-auto.yml"],
  );
  const sync = services["market-data-sync"];
  assert.equal(sync.environment.MARKET_DATA_RUN_MODE, "daily");
  assert.equal(sync.environment.MARKET_DATA_DAILY_AT, "09:00");
  assert.equal(sync.environment.MARKET_DATA_MINUTE_SYMBOLS, "");
  assert.equal(sync.environment.MARKET_DATA_SETTINGS_URL, "");
  assert.equal(sync.environment.MARKET_DATA_RAW_ROOT, "/workspace/var/market-raw/v1-shares-v3");
  assert.equal(
    sync.environment.MARKET_DATA_SYMBOLS,
    services.server.environment.DASHBOARD_DAILY_SYMBOLS,
  );
  assert.equal(sync.restart, "unless-stopped");
  assert.ok(sync.volumes.some((mount) => mount.source === "kunlun-market-raw"));
  assert.ok(sync.volumes.some((mount) => mount.source === "kunlun-market-status"));
  assert.ok(!sync.ports?.length);
});
