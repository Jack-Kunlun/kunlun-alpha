#!/usr/bin/env node

import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const composeFile = join(repoRoot, "infra", "docker", "docker-compose.yml");
const legacyComposeFile = join(repoRoot, "infra", "docker", "docker-compose.clickhouse-bind.yml");
const migrationDir = join(repoRoot, "infra", "clickhouse", "migrations");
const initDir = join(repoRoot, "infra", "docker", "init", "clickhouse");

const migrationFiles = ["001_bars.sql", "002_corporate_actions.sql"];
const migrationNamespace = "v2";
const canonicalTableNames = ["bars_minute_v2", "bars_daily_v2", "corporate_actions_v2"];
const barsColumns = {
  unified_code: "String",
  exchange: "LowCardinality(String)",
  interval: "LowCardinality(String)",
  event_time: "DateTime64(3,'UTC')",
  session: "LowCardinality(String)",
  price_type: "LowCardinality(String)",
  data_version: "LowCardinality(String)",
  source: "LowCardinality(String)",
  source_version: "String",
  raw_capture_id: "String",
  available_time: "DateTime64(3,'UTC')",
  ingest_time: "DateTime64(3,'UTC')",
  processing_time: "DateTime64(3,'UTC')",
  replacement_version: "UInt64",
  date: "Date",
  open: "Decimal(20,4)",
  high: "Decimal(20,4)",
  low: "Decimal(20,4)",
  close: "Decimal(20,4)",
  volume: "UInt64",
  amount: "Decimal(30,2)",
  suspended: "UInt8",
  revision_fingerprint: "FixedString(64)",
};
const barsSortingKey =
  "unified_code,interval,event_time,session,price_type,data_version,source,source_version,available_time,revision_fingerprint";
const barRevisionFingerprintExpression =
  "toFixedString(hex(SHA256(concat('kunlun-p1-r06-fingerprint-v2|','unified_code:S:',hex(unified_code),'|','exchange:S:',hex(exchange),'|','interval:S:',hex(interval),'|','event_time:T64:',toString(toUnixTimestamp64Milli(event_time)),'|','session:S:',hex(session),'|','price_type:S:',hex(price_type),'|','data_version:S:',hex(data_version),'|','source:S:',hex(source),'|','source_version:S:',hex(source_version),'|','raw_capture_id:S:',hex(raw_capture_id),'|','available_time:T64:',toString(toUnixTimestamp64Milli(available_time)),'|','ingest_time:T64:',toString(toUnixTimestamp64Milli(ingest_time)),'|','processing_time:T64:',toString(toUnixTimestamp64Milli(processing_time)),'|','replacement_version:U64:',toString(replacement_version),'|','date:D:',toString(toYYYYMMDD(date)),'|','open:D20,4:',toString(CAST(open,'Decimal(20,4)')),'|','high:D20,4:',toString(CAST(high,'Decimal(20,4)')),'|','low:D20,4:',toString(CAST(low,'Decimal(20,4)')),'|','close:D20,4:',toString(CAST(close,'Decimal(20,4)')),'|','volume:U64:',toString(volume),'|','amount:D30,2:',toString(CAST(amount,'Decimal(30,2)')),'|','suspended:U8:',toString(suspended),'|'))),64)";
const corporateRevisionFingerprintExpression =
  "toFixedString(hex(SHA256(concat('kunlun-p1-r06-fingerprint-v2|','unified_code:S:',hex(unified_code),'|','exchange:S:',hex(exchange),'|','ex_date:D:',toString(toYYYYMMDD(ex_date)),'|','event_time:T64:',toString(toUnixTimestamp64Milli(event_time)),'|','action_type:S:',hex(action_type),'|','source:S:',hex(source),'|','source_event_id:S:',hex(source_event_id),'|','data_version:S:',hex(data_version),'|','source_version:S:',hex(source_version),'|','raw_capture_id:S:',hex(raw_capture_id),'|','available_time:T64:',toString(toUnixTimestamp64Milli(available_time)),'|','ingest_time:T64:',toString(toUnixTimestamp64Milli(ingest_time)),'|','processing_time:T64:',toString(toUnixTimestamp64Milli(processing_time)),'|','replacement_version:U64:',toString(replacement_version),'|','description:S:',hex(description),'|','per_share_cash:',if(isNull(per_share_cash),'N',concat('V:D20,8:',toString(CAST(assumeNotNull(per_share_cash),'Decimal(20,8)')))),'|','per_share_stock:',if(isNull(per_share_stock),'N',concat('V:D20,8:',toString(CAST(assumeNotNull(per_share_stock),'Decimal(20,8)')))),'|','ratio:',if(isNull(ratio),'N',concat('V:D20,8:',toString(CAST(assumeNotNull(ratio),'Decimal(20,8)')))),'|'))),64)";
function toColumnMetadata(columns) {
  return Object.fromEntries(
    Object.entries(columns).map(([name, type]) => [
      name,
      { type, defaultKind: "", defaultExpression: "", compressionCodec: "" },
    ]),
  );
}

function withFingerprintMetadata(columns, expression) {
  return {
    ...toColumnMetadata(columns),
    revision_fingerprint: {
      type: "FixedString(64)",
      defaultKind: "MATERIALIZED",
      defaultExpression: expression,
      compressionCodec: "",
    },
  };
}

const schemaExpectations = {
  "001_bars.sql": {
    bars_minute_v2: { columns: withFingerprintMetadata(barsColumns, barRevisionFingerprintExpression), sortingKey: barsSortingKey },
    bars_daily_v2: { columns: withFingerprintMetadata(barsColumns, barRevisionFingerprintExpression), sortingKey: barsSortingKey },
  },
  "002_corporate_actions.sql": {
    corporate_actions_v2: {
      columns: withFingerprintMetadata({
        unified_code: "String",
        exchange: "LowCardinality(String)",
        ex_date: "Date",
        event_time: "DateTime64(3,'UTC')",
        action_type: "LowCardinality(String)",
        source: "LowCardinality(String)",
        source_event_id: "String",
        data_version: "LowCardinality(String)",
        source_version: "String",
        raw_capture_id: "String",
        available_time: "DateTime64(3,'UTC')",
        ingest_time: "DateTime64(3,'UTC')",
        processing_time: "DateTime64(3,'UTC')",
        replacement_version: "UInt64",
        description: "String",
        per_share_cash: "Nullable(Decimal(20,8))",
        per_share_stock: "Nullable(Decimal(20,8))",
        ratio: "Nullable(Decimal(20,8))",
      }, corporateRevisionFingerprintExpression),
      sortingKey:
        "unified_code,ex_date,action_type,source,source_event_id,data_version,source_version,available_time,revision_fingerprint",
    },
  },
};

function fail(message) {
  throw new Error(message);
}

function read(path) {
  return readFileSync(path, "utf8");
}

function assertDatabaseIdentifier(database) {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(database)) {
    fail(`invalid ClickHouse database identifier: ${database}`);
  }
}

function runDockerCompose(args, input = "") {
  const result = spawnSync(
    "docker",
    ["compose", "-f", composeFile, ...args],
    { cwd: repoRoot, encoding: "utf8", input },
  );
  if (result.error) {
    fail(`docker compose failed to start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    fail(
      `docker compose ${args.join(" ")} failed (${result.status}):\n${
        result.stderr || result.stdout
      }`,
    );
  }
  return result.stdout.trim();
}

function assertComposeWiring() {
  const compose = read(composeFile);
  if (!existsSync(legacyComposeFile)) {
    fail("explicit legacy ClickHouse bind override is missing");
  }
  const legacyCompose = read(legacyComposeFile);
  const initWrapperPath = join(initDir, "01-init.sh");
  const initEntries = existsSync(initWrapperPath) ? readFileSync(initWrapperPath, "utf8") : "";

  if (!compose.includes("../clickhouse/migrations:/opt/kunlun/clickhouse/migrations:ro")) {
    fail("ClickHouse service must mount canonical migrations outside docker-entrypoint-initdb.d");
  }
  if (!compose.includes("./init/clickhouse:/docker-entrypoint-initdb.d:ro")) {
    fail("ClickHouse service must retain the fresh-init wrapper mount");
  }
  if (!compose.includes("kunlun-clickhouse-data:/var/lib/clickhouse")) {
    fail("ClickHouse default data mount must use the named volume kunlun-clickhouse-data");
  }
  if (/\.\/data\/clickhouse:\/var\/lib\/clickhouse/.test(compose)) {
    fail("ClickHouse base Compose file must not bind-mount the Windows data directory");
  }
  if (!compose.includes("kunlun-clickhouse-data:")) {
    fail("ClickHouse named volume declaration is missing");
  }
  if (!legacyCompose.includes("./data/clickhouse:/var/lib/clickhouse")) {
    fail("legacy ClickHouse bind override must retain the explicit host-data path");
  }
  if (!existsSync(initWrapperPath)) {
    fail("fresh-init wrapper infra/docker/init/clickhouse/01-init.sh is missing");
  }
  if (!initEntries.includes("/opt/kunlun/clickhouse/migrations")) {
    fail("fresh-init wrapper must execute canonical migrations");
  }

  for (const filename of migrationFiles) {
    const path = join(migrationDir, filename);
    if (!existsSync(path)) fail(`canonical migration is missing: ${filename}`);
    const sql = read(path);
    const executableSql = sql.replace(/--.*$/gm, "");
    if (/\bTTL\b/i.test(executableSql)) fail(`TTL is forbidden in ${filename}`);
    if (/\bFloat(?:32|64)\b/i.test(executableSql)) {
      fail(`Float types are forbidden in canonical market schema: ${filename}`);
    }
  }

  assertCanonicalV2Tables();

  const obsoleteInit = join(initDir, "01-init.sql");
  if (existsSync(obsoleteInit) && /\bFloat(?:32|64)\b/i.test(read(obsoleteInit))) {
    fail("obsolete Float64 ClickHouse init schema is still active");
  }
}

function assertCanonicalV2Tables() {
  const canonicalSql = migrationFiles.map((filename) => read(join(migrationDir, filename))).join("\n");
  for (const table of canonicalTableNames) {
    if (!new RegExp(`CREATE TABLE IF NOT EXISTS\\s+${table}\\b`).test(canonicalSql)) {
      fail(`canonical migrations must create ${table}`);
    }
  }
  if (/CREATE TABLE IF NOT EXISTS\s+(bars_minute|bars_daily|corporate_actions)\b/.test(canonicalSql)) {
    fail("canonical migrations must not target legacy ClickHouse table names");
  }
}

function clickhouseArgs(database, query) {
  assertDatabaseIdentifier(database);
  return [
    "exec",
    "-T",
    "clickhouse",
    "clickhouse-client",
    "--user",
    process.env.CLICKHOUSE_USER || "kunlun",
    "--password",
    process.env.CLICKHOUSE_PASSWORD || "kunlun-local-dev",
    "--database",
    database,
    "--multiquery",
    "--format",
    "TSVRaw",
    "--query",
    query,
  ];
}

function query(database, sql) {
  return runDockerCompose(clickhouseArgs(database, sql));
}

function runOwnedLifecycle(create, drop, operation) {
  let owned = false;
  try {
    create();
    owned = true;
    return operation();
  } finally {
    if (owned) drop();
  }
}

function withOwnedDatabase(database, operation) {
  assertDatabaseIdentifier(database);
  return runOwnedLifecycle(
    () => query("default", `CREATE DATABASE \`${database}\``),
    () => query("default", `DROP DATABASE IF EXISTS \`${database}\``),
    operation,
  );
}

function normalizeSchemaValue(value) {
  let normalized = value.replace(/\s+/g, "").replaceAll("`", "");
  normalized = normalized.replace(
    /isNull\(([A-Za-z_][A-Za-z0-9_]*)\)/g,
    "$1ISNULL",
  );
  normalized = normalized.replace(
    /CAST\(([^,]+),('?)(Decimal\(\d+,\d+\))\2\)/g,
    "CAST($1,Decimal($3))",
  );
  return normalized.startsWith("(") && normalized.endsWith(")")
    ? normalized.slice(1, -1)
    : normalized;
}

function normalizeOptionalSchemaValue(value) {
  return normalizeSchemaValue(value || "");
}

function validateColumnMetadata(expectedColumns, actualColumns) {
  const expectedNames = Object.keys(expectedColumns).sort();
  const actualNames = Object.keys(actualColumns).sort();
  if (expectedNames.join("\0") !== actualNames.join("\0")) {
    return `column set drift: expected [${expectedNames.join(", ")}] got [${actualNames.join(", ")}]`;
  }
  for (const name of expectedNames) {
    const expected = typeof expectedColumns[name] === "string"
      ? { type: expectedColumns[name], defaultKind: "", defaultExpression: "", compressionCodec: "" }
      : expectedColumns[name];
    const actual = actualColumns[name];
    if (normalizeSchemaValue(actual.type) !== normalizeSchemaValue(expected.type)) {
      return `${name} type drift: expected ${expected.type} got ${actual.type}`;
    }
    for (const field of ["defaultKind", "defaultExpression", "compressionCodec"]) {
      if (normalizeOptionalSchemaValue(actual[field]) !== normalizeOptionalSchemaValue(expected[field])) {
        return `${name} ${field} drift: expected ${expected[field] || "<empty>"} got ${actual[field] || "<empty>"}`;
      }
    }
  }
  return null;
}

function extractReplacingMergeTreeVersion(engineFull) {
  const match = normalizeSchemaValue(engineFull).match(/^ReplacingMergeTree\(([^)]*)\)/i);
  return match ? match[1] : "";
}

function runSelfTest() {
  assertCanonicalV2Tables();
  const actual =
    "ReplacingMergeTree(replacement_version) PARTITION BY toYYYYMM(event_time) ORDER BY (unified_code, event_time) SETTINGS index_granularity = 8192";
  if (extractReplacingMergeTreeVersion(actual) !== "replacement_version") {
    fail("engine_full parser self-test failed to isolate replacement_version");
  }
  if (!barsSortingKey.endsWith(",available_time,revision_fingerprint")) {
    fail("bar physical sorting key must end in available_time,revision_fingerprint");
  }
  const expectedColumns = toColumnMetadata(barsColumns);
  const rogueColumns = { ...expectedColumns, rogue_column: { type: "String", defaultKind: "", defaultExpression: "", compressionCodec: "" } };
  const driftedColumns = {
    ...expectedColumns,
    open: { ...expectedColumns.open, defaultKind: "DEFAULT", defaultExpression: "0", compressionCodec: "LZ4" },
  };
  if (!validateColumnMetadata(expectedColumns, rogueColumns) || !validateColumnMetadata(expectedColumns, driftedColumns)) {
    fail("schema drift fixture with rogue/default/codec metadata was accepted before metadata write");
  }
  const canonicalSql = migrationFiles.map((filename) => read(join(migrationDir, filename))).join("\n");
  const jsonSerializer = ["to", "JSONString"].join("");
  if (canonicalSql.includes(jsonSerializer)) {
    fail(`canonical fingerprint must not use ${jsonSerializer}`);
  }
  if (!/revision_fingerprint\s+FixedString\(64\)\s+MATERIALIZED/i.test(canonicalSql)) {
    fail("canonical V2 schema is missing MATERIALIZED revision_fingerprint");
  }
  if (!barsSortingKey.endsWith(",available_time,revision_fingerprint")) {
    fail("revision_fingerprint must follow available_time in the physical key");
  }
  if (!schemaExpectations["002_corporate_actions.sql"].corporate_actions_v2.sortingKey.endsWith(",available_time,revision_fingerprint")) {
    fail("corporate revision_fingerprint must follow available_time in the physical key");
  }
  const normalizedCanonicalSql = normalizeSchemaValue(canonicalSql);
  if (!normalizedCanonicalSql.includes(normalizeSchemaValue(barRevisionFingerprintExpression)) ||
      !normalizedCanonicalSql.includes(normalizeSchemaValue(corporateRevisionFingerprintExpression))) {
    fail("canonical revision_fingerprint expression does not match the fixed versioned serialization");
  }
  const serverNullExpression = corporateRevisionFingerprintExpression
    .replaceAll("isNull(per_share_cash)", "per_share_cash IS NULL")
    .replaceAll("isNull(per_share_stock)", "per_share_stock IS NULL")
    .replaceAll("isNull(ratio)", "ratio IS NULL");
  const serverDecimalCastExpression = corporateRevisionFingerprintExpression.replaceAll(
    ",'Decimal(20,8)'",
    ",Decimal(20,8)",
  );
  if (normalizeSchemaValue(serverNullExpression) !== normalizeSchemaValue(corporateRevisionFingerprintExpression)) {
    fail("schema expression normalization must equate isNull(identifier) and identifier IS NULL");
  }
  if (normalizeSchemaValue(serverDecimalCastExpression) !== normalizeSchemaValue(corporateRevisionFingerprintExpression)) {
    fail("schema expression normalization must equate CAST Decimal(P,S) quote forms");
  }
  const unsafeCreateClause = ["CREATE", "DATABASE", "IF", "NOT", "EXISTS"].join(" ");
  const smokeSource = read(fileURLToPath(import.meta.url));
  if (smokeSource.includes(unsafeCreateClause)) {
    fail("smoke database collision can reuse an existing database and drop it during cleanup");
  }
  const conflictThrowFunction = ["throw", "If"].join("");
  if (!smokeSource.includes(conflictThrowFunction)) {
    fail(`PIT conflict reader must ${conflictThrowFunction} instead of silently dropping a conflicting identity`);
  }
  const legacyCreateProbe = ["SHOW", "CREATE", "TABLE"].join(" ");
  if (!smokeSource.includes(legacyCreateProbe)) {
    fail(`legacy fixture verification must compare ${legacyCreateProbe} and complete column metadata`);
  }
  const fixtureCanonicalBarsSql = read(join(migrationDir, "001_bars.sql"));
  const fixtureRogueBarsSql = fixtureCanonicalBarsSql.replace(
    /    revision_fingerprint FixedString\(64\) MATERIALIZED/g,
    "    rogue_column String DEFAULT 'rogue' CODEC(LZ4),\n    revision_fingerprint FixedString(64) MATERIALIZED",
  );
  if (fixtureRogueBarsSql === fixtureCanonicalBarsSql || !fixtureRogueBarsSql.includes("rogue_column")) {
    fail("schema drift fixture did not inject its rogue column");
  }
  const compressionCodecColumn = ["compression", "codec"].join("_");
  if (!smokeSource.includes(compressionCodecColumn)) {
    fail(`ClickHouse column metadata must use ${compressionCodecColumn}`);
  }
  if (typeof runOwnedLifecycle !== "function") {
    fail("smoke database ownership lifecycle helper is missing");
  }
  let collisionError = false;
  let collisionDropCalls = 0;
  let collisionFixtureCalls = 0;
  try {
    runOwnedLifecycle(
      () => fail("database already exists"),
      () => { collisionDropCalls += 1; },
      () => { collisionFixtureCalls += 1; },
    );
  } catch (error) {
    collisionError = String(error).includes("database already exists");
  }
  if (!collisionError || collisionDropCalls !== 0 || collisionFixtureCalls !== 0) {
    fail("database collision must fail before fixture writes and without cleanup");
  }
  process.stdout.write("ClickHouse migration smoke self-test passed\n");
}

function verifyMigrationSchema(database, filename) {
  const tables = schemaExpectations[filename];
  for (const [table, expectation] of Object.entries(tables)) {
    const tableRow = query(
      database,
      `SELECT engine, engine_full, sorting_key, partition_key FROM system.tables WHERE database = currentDatabase() AND name = '${table}' LIMIT 1`,
    );
    if (!tableRow) fail(`schema verification found no table ${table} for ${filename}`);
    let [engine, engineFull, sortingKey, partitionKey] = tableRow.split("\t");
    if (engine !== "ReplacingMergeTree" || extractReplacingMergeTreeVersion(engineFull) !== "replacement_version") {
      fail(`${table} engine/version is ${engineFull}, expected ReplacingMergeTree(replacement_version)`);
    }
    if (normalizeSchemaValue(partitionKey) !== "toYYYYMM(event_time)" && table !== "corporate_actions_v2") {
      fail(`${table} partition key is ${partitionKey}, expected toYYYYMM(event_time)`);
    }
    if (table === "corporate_actions_v2" && normalizeSchemaValue(partitionKey) !== "toYYYYMM(ex_date)") {
      fail(`${table} partition key is ${partitionKey}, expected toYYYYMM(ex_date)`);
    }
    const normalizedSortingKey = normalizeSchemaValue(sortingKey);
    const normalizedExpectedSortingKey = normalizeSchemaValue(expectation.sortingKey);
    if (normalizedSortingKey !== normalizedExpectedSortingKey) {
      fail(`${table} sorting key is ${sortingKey}, expected ${expectation.sortingKey}`);
    }
    const columns = query(
      database,
      `SELECT name, type, default_kind, default_expression, compression_codec FROM system.columns WHERE database = currentDatabase() AND table = '${table}' ORDER BY name`,
    )
      .split(/\r?\n/)
      .filter(Boolean)
      .reduce((result, line) => {
        const [name, type, defaultKind, defaultExpression, compressionCodec] = line.split("\t");
        result[name] = { type, defaultKind, defaultExpression, compressionCodec };
        return result;
      }, {});
    const columnError = validateColumnMetadata(expectation.columns, columns);
    if (columnError) {
      fail(`${table} schema drift: ${columnError}`);
    }
  }
}

function verifyMigrationMetadata(database) {
  const columns = query(
    database,
    "SELECT name, type FROM system.columns WHERE database = currentDatabase() AND table = '_kunlun_schema_migrations' ORDER BY name",
  )
    .split(/\r?\n/)
    .filter(Boolean)
    .reduce((result, line) => {
      const [name, type] = line.split("\t");
      result[name] = normalizeSchemaValue(type);
      return result;
    }, {});
  for (const [name, expectedType] of Object.entries({
    version: "String",
    checksum: "String",
    applied_at: "DateTime64(3,'UTC')",
  })) {
    if (!(name in columns)) fail(`_kunlun_schema_migrations.${name} is missing`);
    if (columns[name] !== normalizeSchemaValue(expectedType)) {
      fail(`_kunlun_schema_migrations.${name} type is ${columns[name]}, expected ${expectedType}`);
    }
  }
}

function applyMigration(database, filename) {
  const sql = read(join(migrationDir, filename));
  const checksum = createHash("sha256").update(sql).digest("hex");
  const version = `${migrationNamespace}/${filename}`;
  const escapedVersion = version.replaceAll("'", "''");
  const escapedChecksum = checksum.replaceAll("'", "''");
  const rows = query(
    database,
    `SELECT checksum FROM _kunlun_schema_migrations WHERE version = '${escapedVersion}' LIMIT 1`,
  );
  if (rows) {
    verifyMigrationSchema(database, filename);
    if (rows !== checksum) {
      fail(`migration checksum changed for ${filename}`);
    }
    return;
  }

  runDockerCompose(clickhouseArgs(database, sql));
  verifyMigrationSchema(database, filename);
  query(
    database,
    `INSERT INTO _kunlun_schema_migrations (version, checksum, applied_at) VALUES ('${escapedVersion}', '${escapedChecksum}', now64(3))`,
  );
}

function migrate(database) {
  assertDatabaseIdentifier(database);
  query(
    database,
    "CREATE TABLE IF NOT EXISTS _kunlun_schema_migrations (version String, checksum String, applied_at DateTime64(3, 'UTC')) ENGINE = MergeTree ORDER BY version",
  );
  verifyMigrationMetadata(database);
  for (const filename of migrationFiles) applyMigration(database, filename);
}

function schemaDriftSmoke() {
  const database = `kunlun_p1_r06_schema_drift_${randomUUID().replaceAll("-", "")}`;
  return withOwnedDatabase(database, () => {
    const canonicalBarsSql = read(join(migrationDir, "001_bars.sql"));
    const rogueBarsSql = canonicalBarsSql.replace(
      /    revision_fingerprint FixedString\(64\) MATERIALIZED/g,
      "    rogue_column String DEFAULT 'rogue' CODEC(LZ4),\n    revision_fingerprint FixedString(64) MATERIALIZED",
    );
    if (rogueBarsSql === canonicalBarsSql || !rogueBarsSql.includes("rogue_column")) {
      fail("schema drift fixture did not inject its rogue column");
    }
    runDockerCompose(clickhouseArgs(database, rogueBarsSql));
    let failedClosed = false;
    try {
      migrate(database);
    } catch (error) {
      failedClosed = String(error).includes("schema drift");
    }
    if (!failedClosed) {
      fail("schema drift fixture was accepted or failed for an unrelated reason");
    }
    if (query(database, "SELECT count() FROM _kunlun_schema_migrations") !== "0") {
      fail("schema drift wrote migration metadata before verification");
    }
  });
}

function waitForClickHouse() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const result = spawnSync(
      "docker",
      [
        "compose",
        "-f",
        composeFile,
        "exec",
        "-T",
        "clickhouse",
        "clickhouse-client",
        "--user",
        process.env.CLICKHOUSE_USER || "kunlun",
        "--password",
        process.env.CLICKHOUSE_PASSWORD || "kunlun-local-dev",
        "--query",
        "SELECT 1",
      ],
      { cwd: repoRoot, encoding: "utf8" },
    );
    if (result.status === 0) return;
    const delay = Math.min(1000 * (attempt + 1), 5000);
    spawnSync(process.platform === "win32" ? "ping" : "sleep", process.platform === "win32" ? ["-n", "2", "127.0.0.1"] : [String(delay / 1000)]);
  }
  fail("ClickHouse did not become ready within 30 attempts");
}

const legacyTableDefinitions = [
  ["bars_minute", "legacy-bars-minute"],
  ["bars_daily", "legacy-bars-daily"],
  ["corporate_actions", "legacy-corporate-actions"],
  ["market_bars", "legacy-market-bars"],
];

function createLegacyTables(database) {
  for (const [table, marker] of legacyTableDefinitions) {
    query(
      database,
      `CREATE TABLE IF NOT EXISTS \`${table}\` (legacy_marker String) ENGINE = MergeTree ORDER BY legacy_marker`,
    );
    query(database, `INSERT INTO \`${table}\` (legacy_marker) VALUES ('${marker}')`);
  }
}

function captureLegacyTableState(database) {
  return legacyTableDefinitions.map(([table]) => ({
    table,
    count: query(database, `SELECT count() FROM \`${table}\``),
    marker: query(database, `SELECT groupArray(legacy_marker) FROM \`${table}\``),
    showCreate: query(database, `SHOW CREATE TABLE \`${table}\``),
    columns: query(
      database,
      `SELECT name, type, default_kind, default_expression, compression_codec FROM system.columns WHERE database = currentDatabase() AND table = '${table}' ORDER BY name`,
    ),
    engine: query(
      database,
      `SELECT engine, engine_full, partition_key, sorting_key FROM system.tables WHERE database = currentDatabase() AND name = '${table}' LIMIT 1`,
    ),
  }));
}

function assertLegacyTableState(database, expected, phase) {
  const actual = captureLegacyTableState(database);
  for (let index = 0; index < expected.length; index += 1) {
    const before = expected[index];
    const after = actual[index];
    if (before.count !== after.count || before.marker !== after.marker || before.showCreate !== after.showCreate || before.columns !== after.columns || before.engine !== after.engine) {
      fail(`legacy table ${before.table} changed during ${phase}`);
    }
  }
}

function smoke() {
  assertComposeWiring();
  runDockerCompose(["up", "-d", "clickhouse"]);
  waitForClickHouse();
  const database = `kunlun_p1_r06_${randomUUID().replaceAll("-", "")}`;
  return withOwnedDatabase(database, () => {
    createLegacyTables(database);
    const legacyBeforeMigration = captureLegacyTableState(database);
    migrate(database);
    migrate(database);
    assertLegacyTableState(database, legacyBeforeMigration, "initial and replay migrations");
    const schema = query(
      database,
      "SELECT name FROM system.tables WHERE database = currentDatabase() AND name IN ('bars_minute_v2', 'bars_daily_v2', 'corporate_actions_v2') ORDER BY name",
    );
    if (schema.split(/\r?\n/).filter(Boolean).length !== 3) {
      fail(`unexpected schema after migration: ${schema}`);
    }
    query(
      database,
      `INSERT INTO bars_minute_v2 (unified_code, exchange, interval, event_time, session, price_type, data_version, source, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, date, open, high, low, close, volume, amount, suspended) VALUES
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v1', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, '2026-08-13', 10.0000, 10.5000, 9.8000, 10.2000, 1000, 10200.00, 0),
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v2', toDateTime64('2026-08-13 04:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 03:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:01:00.000', 3, 'UTC'), 2, '2026-08-13', 10.0000, 10.7000, 9.8000, 10.4000, 1000, 10400.00, 0),
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v2b', toDateTime64('2026-08-13 04:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 03:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:01:00.000', 3, 'UTC'), 3, '2026-08-13', 10.0000, 10.9000, 9.8000, 10.6000, 1000, 10600.00, 0),
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'FORWARD_ADJUSTED', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v3', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, '2026-08-13', 9.8000, 10.3000, 9.6000, 10.0000, 1000, 10000.00, 0),
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'BACKWARD_ADJUSTED', 'bar-v2', 'vendor-b', '2026-08-14', 'raw-smoke-v4', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, '2026-08-13', 10.1000, 10.6000, 9.9000, 10.4000, 1000, 10400.00, 0),
      ('600000.SH', 'SH', 'MINUTE_5', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v5', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, '2026-08-13', 10.2000, 10.8000, 10.0000, 10.5000, 5000, 52500.00, 0),
      ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-v1', 'vendor-a', '2026-08-13', 'raw-smoke-v1', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, '2026-08-13', 10.0000, 10.5000, 9.8000, 10.2000, 1000, 10200.00, 0)`,
    );
    query(database, "OPTIMIZE TABLE bars_minute_v2 FINAL");
    if (query(database, "SELECT count() FROM bars_minute_v2") !== "6") {
      fail("exact replay did not collapse to one logical revision");
    }
    const pitQuery = (asOf) =>
      `WITH revision_groups AS (SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version, any(close) AS close, uniqExact(revision_fingerprint) AS revision_count FROM bars_minute_v2 WHERE available_time <= toDateTime64('${asOf}', 3, 'UTC') GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0) SELECT unified_code, interval, price_type, data_version, source, source_version, toString(argMax(close, replacement_version)), toString(argMax(replacement_version, replacement_version)) FROM revision_groups GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version HAVING max(revision_count) = 1 ORDER BY unified_code, interval, price_type, data_version, source, source_version`;
    const barConflictCount = (asOf) =>
      query(database, `SELECT count() FROM (SELECT unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version FROM bars_minute_v2 WHERE available_time <= toDateTime64('${asOf}', 3, 'UTC') GROUP BY unified_code, interval, event_time, session, price_type, data_version, source, source_version, replacement_version HAVING uniqExact(revision_fingerprint) > 1)`);
    const pitAtThree = query(database, pitQuery("2026-08-13 03:00:00.000"));
    const pitRowsAtThree = pitAtThree.split(/\r?\n/).filter(Boolean);
    if (pitRowsAtThree.length !== 4) {
      fail(`PIT selection exposed ${pitRowsAtThree.length} semantic rows, expected 4`);
    }
    const rawAtThree = pitRowsAtThree.find((row) => row.includes("\tMINUTE_1\tRAW\tbar-v1\tvendor-a\t2026-08-13\t"));
    if (!rawAtThree || !rawAtThree.endsWith("\t1")) {
      fail(`PIT-before-argMax failed for the replacement row: ${rawAtThree || "missing"}`);
    }
    const pitAtFive = query(database, pitQuery("2026-08-13 05:00:00.000"));
    const rawAtFive = pitAtFive
      .split(/\r?\n/)
      .find((row) => row.includes("\tMINUTE_1\tRAW\tbar-v1\tvendor-a\t2026-08-13\t"));
    if (!rawAtFive || !rawAtFive.endsWith("\t3")) {
      fail(`replacement_version=3 did not win for the same available revision: ${rawAtFive || "missing"}`);
    }
    const settingsMatrixBarInsert = (quoteIntegers, quoteDecimals, namedTuplesAsObjects, dateTimeOutputFormat) =>
      query(
        database,
        `SET output_format_json_quote_64bit_integers = ${quoteIntegers}; SET output_format_json_quote_decimals = ${quoteDecimals}; SET output_format_json_named_tuples_as_objects = ${namedTuplesAsObjects}; SET date_time_output_format = '${dateTimeOutputFormat}'; INSERT INTO bars_minute_v2 (unified_code, exchange, interval, event_time, session, price_type, data_version, source, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, date, open, high, low, close, volume, amount, suspended) VALUES ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-settings', 'vendor-a', '2026-08-13', 'raw-settings', toDateTime64('2026-08-13 06:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 06:01:00.000', 3, 'UTC'), 1, '2026-08-13', 12.0000, 12.5000, 11.8000, 12.2000, 1000, 12200.00, 0)`,
      );
    settingsMatrixBarInsert(0, 0, 0, "simple");
    settingsMatrixBarInsert(1, 1, 1, "iso");
    query(database, "OPTIMIZE TABLE bars_minute_v2 FINAL");
    if (query(database, "SELECT uniqExact(revision_fingerprint) FROM bars_minute_v2 WHERE data_version = 'bar-settings'") !== "1") {
      fail("settings-dependent bar fingerprint changed for an exact replay");
    }
    if (query(database, "SELECT count() FROM bars_minute_v2") !== "7") {
      fail("settings-matrix bar replay did not collapse to one physical revision");
    }
    query(
      database,
      "INSERT INTO bars_minute_v2 (unified_code, exchange, interval, event_time, session, price_type, data_version, source, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, date, open, high, low, close, volume, amount, suspended) VALUES ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-conflict', 'vendor-a', '2026-08-13', 'raw-conflict-a', toDateTime64('2026-08-13 05:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:01:00.000', 3, 'UTC'), 1, '2026-08-13', 11.0000, 11.5000, 10.8000, 11.2000, 1000, 11200.00, 0), ('600000.SH', 'SH', 'MINUTE_1', toDateTime64('2026-08-13 01:30:00.000', 3, 'UTC'), 'CONTINUOUS', 'RAW', 'bar-conflict', 'vendor-a', '2026-08-13', 'raw-conflict-b', toDateTime64('2026-08-13 05:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:01:00.000', 3, 'UTC'), 1, '2026-08-13', 11.0000, 11.7000, 10.8000, 11.4000, 1000, 11400.00, 0)",
    );
    query(database, "OPTIMIZE TABLE bars_minute_v2 FINAL");
    if (query(database, "SELECT uniqExact(revision_fingerprint) FROM bars_minute_v2 WHERE data_version = 'bar-conflict'") !== "2") {
      fail("bar conflict fingerprints were merged or not materialized");
    }
    if (barConflictCount("2026-08-13 03:00:00.000") !== "0") {
      fail("future bar conflict polluted an earlier PIT");
    }
    if (barConflictCount("2026-08-13 05:00:00.000") !== "1") {
      fail("bar PIT conflict was not detected after availability");
    }
    query(
      database,
      "INSERT INTO corporate_actions_v2 (unified_code, exchange, ex_date, event_time, action_type, source, source_event_id, data_version, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, description, per_share_cash, per_share_stock, ratio) VALUES ('600000.SH', 'SH', '2026-08-13', toDateTime64('2026-08-13 00:00:00.000', 3, 'UTC'), 'DIVIDEND', 'vendor-a', 'event-a', 'ca-v1', '2026-08-13', 'ca-raw-a', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, 'cash', 0.50, NULL, NULL), ('600000.SH', 'SH', '2026-08-13', toDateTime64('2026-08-13 00:00:00.000', 3, 'UTC'), 'SPLIT', 'vendor-a', 'event-b', 'ca-v1', '2026-08-13', 'ca-raw-b', toDateTime64('2026-08-13 02:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 01:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 02:01:00.000', 3, 'UTC'), 1, 'split', NULL, 1.00, 2.00)",
    );
    if (query(database, "SELECT count() FROM corporate_actions_v2") !== "2") {
      fail("corporate-action semantic identity collapsed distinct source events");
    }
    query(database, "OPTIMIZE TABLE corporate_actions_v2 FINAL");
    const settingsMatrixCorporateInsert = (quoteIntegers, quoteDecimals, namedTuplesAsObjects, dateTimeOutputFormat) =>
      query(
        database,
        `SET output_format_json_quote_64bit_integers = ${quoteIntegers}; SET output_format_json_quote_decimals = ${quoteDecimals}; SET output_format_json_named_tuples_as_objects = ${namedTuplesAsObjects}; SET date_time_output_format = '${dateTimeOutputFormat}'; INSERT INTO corporate_actions_v2 (unified_code, exchange, ex_date, event_time, action_type, source, source_event_id, data_version, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, description, per_share_cash, per_share_stock, ratio) VALUES ('600000.SH', 'SH', '2026-08-13', toDateTime64('2026-08-13 00:00:00.000', 3, 'UTC'), 'DIVIDEND', 'vendor-a', 'event-settings', 'ca-settings', '2026-08-13', 'ca-settings', toDateTime64('2026-08-13 06:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 06:01:00.000', 3, 'UTC'), 1, 'settings', 0.70, NULL, NULL)`,
      );
    settingsMatrixCorporateInsert(0, 0, 0, "simple");
    settingsMatrixCorporateInsert(1, 1, 1, "iso");
    query(database, "OPTIMIZE TABLE corporate_actions_v2 FINAL");
    if (query(database, "SELECT uniqExact(revision_fingerprint) FROM corporate_actions_v2 WHERE source_event_id = 'event-settings'") !== "1") {
      fail("settings-dependent corporate fingerprint changed for an exact replay");
    }
    if (query(database, "SELECT count() FROM corporate_actions_v2") !== "3") {
      fail("settings-matrix corporate replay did not collapse to one physical revision");
    }
    const corporateConflictCount = (asOf) =>
      query(database, `SELECT count() FROM (SELECT unified_code, ex_date, action_type, source, source_event_id, data_version, source_version, replacement_version FROM corporate_actions_v2 WHERE available_time <= toDateTime64('${asOf}', 3, 'UTC') GROUP BY unified_code, ex_date, action_type, source, source_event_id, data_version, source_version, replacement_version HAVING uniqExact(revision_fingerprint) > 1)`);
    const corporatePitQuery = (asOf) =>
      `WITH revision_groups AS (SELECT unified_code, ex_date, action_type, source, source_event_id, data_version, source_version, replacement_version, any(description) AS description, uniqExact(revision_fingerprint) AS revision_count FROM corporate_actions_v2 WHERE available_time <= toDateTime64('${asOf}', 3, 'UTC') GROUP BY unified_code, ex_date, action_type, source, source_event_id, data_version, source_version, replacement_version HAVING throwIf(uniqExact(revision_fingerprint) > 1, 'revision_fingerprint conflict') = 0) SELECT unified_code, ex_date, action_type, source_event_id, toString(argMax(description, replacement_version)) FROM revision_groups GROUP BY unified_code, ex_date, action_type, source_event_id HAVING max(revision_count) = 1 ORDER BY unified_code, ex_date, action_type, source_event_id`;
    const corporatePitAtThree = query(database, corporatePitQuery("2026-08-13 03:00:00.000"));
    if (corporatePitAtThree.split(/\r?\n/).filter(Boolean).length !== 2) {
      fail("corporate-action early PIT selection returned an unexpected row count");
    }
    query(
      database,
      "INSERT INTO corporate_actions_v2 (unified_code, exchange, ex_date, event_time, action_type, source, source_event_id, data_version, source_version, raw_capture_id, available_time, ingest_time, processing_time, replacement_version, description, per_share_cash, per_share_stock, ratio) VALUES ('600000.SH', 'SH', '2026-08-13', toDateTime64('2026-08-13 00:00:00.000', 3, 'UTC'), 'DIVIDEND', 'vendor-a', 'event-conflict', 'ca-conflict', '2026-08-13', 'ca-conflict-a', toDateTime64('2026-08-13 05:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:01:00.000', 3, 'UTC'), 1, 'cash-a', 0.50, NULL, NULL), ('600000.SH', 'SH', '2026-08-13', toDateTime64('2026-08-13 00:00:00.000', 3, 'UTC'), 'DIVIDEND', 'vendor-a', 'event-conflict', 'ca-conflict', '2026-08-13', 'ca-conflict-b', toDateTime64('2026-08-13 05:00:00.000', 3, 'UTC'), toDateTime64('2026-08-13 04:45:00.000', 3, 'UTC'), toDateTime64('2026-08-13 05:01:00.000', 3, 'UTC'), 1, 'cash-b', 0.60, NULL, NULL)",
    );
    query(database, "OPTIMIZE TABLE corporate_actions_v2 FINAL");
    if (query(database, "SELECT uniqExact(revision_fingerprint) FROM corporate_actions_v2 WHERE source_event_id = 'event-conflict'") !== "2") {
      fail("corporate-action conflict fingerprints were merged or not materialized");
    }
    if (corporateConflictCount("2026-08-13 03:00:00.000") !== "0" || corporateConflictCount("2026-08-13 05:00:00.000") !== "1") {
      fail("corporate-action PIT conflict availability filtering is incorrect");
    }
    const assertCorporateConflictThrows = (phase) => {
      try {
        query(database, corporatePitQuery("2026-08-13 05:00:00.000"));
      } catch (error) {
        if (String(error).includes("revision_fingerprint conflict")) return;
        fail(`corporate conflict ${phase} failed for an unrelated reason: ${String(error)}`);
      }
      fail(`corporate conflict ${phase} returned an arbitrary winner`);
    };
    assertCorporateConflictThrows("before restart");
    const assertBarConflictThrows = (phase) => {
      try {
        query(database, pitQuery("2026-08-13 05:00:00.000"));
      } catch (error) {
        if (String(error).includes("revision_fingerprint conflict")) return;
        fail(`bar conflict ${phase} failed for an unrelated reason: ${String(error)}`);
      }
      fail(`bar conflict ${phase} returned an arbitrary winner`);
    };
    assertBarConflictThrows("before restart");
    const countBeforeRestart = query(database, "SELECT count() FROM bars_minute_v2");
    const corporateCountBeforeRestart = query(database, "SELECT count() FROM corporate_actions_v2");
    if (countBeforeRestart !== "9" || corporateCountBeforeRestart !== "5") {
      fail(`unexpected physical revision counts before restart: bars=${countBeforeRestart}, corporate=${corporateCountBeforeRestart}`);
    }
    const barConflictBeforeRestart = barConflictCount("2026-08-13 05:00:00.000");
    const corporateConflictBeforeRestart = corporateConflictCount("2026-08-13 05:00:00.000");
    runDockerCompose(["restart", "clickhouse"]);
    waitForClickHouse();
    migrate(database);
    const countAfterRestart = query(database, "SELECT count() FROM bars_minute_v2");
    const corporateCountAfterRestart = query(database, "SELECT count() FROM corporate_actions_v2");
    if (countAfterRestart !== countBeforeRestart || corporateCountAfterRestart !== corporateCountBeforeRestart) {
      fail(`restart lost semantic rows: before=${countBeforeRestart}, after=${countAfterRestart}`);
    }
    if (query(database, pitQuery("2026-08-13 03:00:00.000")) !== pitAtThree) {
      fail("restart changed deterministic PIT selection");
    }
    if (query(database, corporatePitQuery("2026-08-13 03:00:00.000")) !== corporatePitAtThree) {
      fail("restart changed corporate-action PIT selection");
    }
    assertBarConflictThrows("after restart");
    assertCorporateConflictThrows("after restart");
    if (barConflictCount("2026-08-13 05:00:00.000") !== barConflictBeforeRestart ||
        corporateConflictCount("2026-08-13 05:00:00.000") !== corporateConflictBeforeRestart) {
      fail("restart changed conflict evidence");
    }
    assertLegacyTableState(database, legacyBeforeMigration, "ClickHouse restart and V2 replay");
    schemaDriftSmoke();
    process.stdout.write(`ClickHouse smoke passed for ${database}\n`);
  });
}

const command = process.argv[2] || "--check-config";
if (command === "--check-config") {
  assertComposeWiring();
  process.stdout.write("ClickHouse migration wiring passed\n");
} else if (command === "--migrate") {
  assertComposeWiring();
  const database = process.argv[3] || process.env.CLICKHOUSE_DB || "kunlun";
  migrate(database);
  process.stdout.write(`ClickHouse migrations applied to ${database}\n`);
} else if (command === "--smoke") {
  smoke();
} else if (command === "--self-test") {
  runSelfTest();
} else {
  fail(`unknown command ${command}; expected --check-config, --migrate, --smoke, or --self-test`);
}
