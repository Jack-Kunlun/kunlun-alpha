# ClickHouse Phase 1 migrations

The canonical Phase 1 V2 schema is under `infra/clickhouse/migrations/`:

- `001_bars.sql` creates `bars_minute_v2` and `bars_daily_v2`.
- `002_corporate_actions.sql` creates `corporate_actions_v2`.

Both tables use `ReplacingMergeTree(replacement_version)`, `Decimal` price and
amount columns, and millisecond UTC `DateTime64` event/PIT timestamps.  The
bar identity includes instrument, interval, event time, session, price type,
data version, source, and source version.  `raw_capture_id` is provenance and
is deliberately not part of identity.  `available_time` is the final physical
sorting-key component so revisions with different availability survive
`OPTIMIZE FINAL`; PIT grouping still uses the semantic identity without that
column.  There is no TTL or automatic history deletion policy.

Each V2 table also materializes a versioned `revision_fingerprint` as
`FixedString(64)` using SHA-256 over an explicit, unambiguous framing.  The
fixed prefix is `kunlun-p1-r06-fingerprint-v2|`; every persisted field has a
label and type tag, String/LowCardinality values use `hex(value)`, UTC
`DateTime64` uses `toUnixTimestamp64Milli`, `Date` uses `toYYYYMMDD`, UInts use
`toString`, Decimals are cast to their schema precision/scale before
`toString`, and Nullable values use explicit N/V markers.  The fingerprint
does not include itself and never uses `toJSONString` or native reinterpret
serialization.  It follows `available_time` in `ORDER BY`: an exact
full-envelope replay has the same physical key, while a same-identity/version
payload, availability, or provenance conflict remains physically observable.
This node has no production ClickHouse writer; the fingerprint and canonical
reader are therefore the durable safety boundary.  A future writer must add a
CAS/uniqueness check before accepting a same-identity/version conflict.

## Fresh Compose volume

Compose stores ClickHouse data in the explicitly named Docker volume
`kunlun-clickhouse-data` by default and mounts the canonical directory at
`/opt/kunlun/clickhouse/migrations`.  The small
`infra/docker/init/clickhouse/01-init.sh` wrapper, mounted under
`/docker-entrypoint-initdb.d`, executes both canonical files on a fresh data
directory.  The wrapper validates the database identifier before using it in a
ClickHouse identifier.

## Existing Compose volume

Start only the existing ClickHouse service, then run the explicit idempotent
migrator from the repository root:

```text
docker compose -f infra/docker/docker-compose.yml up -d clickhouse
node scripts/ci/clickhouse-migration-smoke.mjs --migrate kunlun
```

The migrator creates `_kunlun_schema_migrations`, records V2 versions under the
`v2/` namespace, verifies the V2 columns,
types, partition/sorting keys, and `ReplacingMergeTree(replacement_version)`,
then records a checksum only after verification succeeds.  A partial or drifted
V2 table fails closed and is not marked as applied.  Verification compares the
exact V2 column set, types, default kinds/expressions, compression codec
metadata, engine/version, partition key, and sorting key.  Existing `bars_minute`,
`bars_daily`, `corporate_actions`, `kunlun.market_bars`, and the legacy host
directory `infra/docker/data/clickhouse` are never altered, copied, renamed, or
dropped.  The default named volume is intentionally separate from that Windows
bind mount because MergeTree part renames are not reliable on 9p bind mounts.

If the legacy bind data must be inspected or migrated, stop the service and
opt in to the checked-in override explicitly:

```text
docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.clickhouse-bind.yml up -d clickhouse
```

Back up the host directory before any manual inspection.  The override is a
legacy compatibility path only; it never copies, deletes, renames, or
automatically imports data into `kunlun-clickhouse-data`.  V2 migration does
not alter the old tables.  Any future data transfer requires a separately
approved shadow-table/cutover procedure, then return to the default named-volume
Compose file.

## Isolated smoke test

Use the smoke command to run the full migration/replay/PIT/restart check:

```text
node scripts/ci/clickhouse-migration-smoke.mjs --smoke
```

It creates a random `kunlun_p1_r06_*` database, creates legacy table fixtures
(`bars_minute`, `bars_daily`, `corporate_actions`, and `market_bars`) with
sentinel rows, runs the V2 migrations twice, proves the complete legacy
`SHOW CREATE TABLE`, columns/defaults/codecs, engine, and rows are unchanged,
checks V2 schema metadata, inserts distinct raw/adjusted intervals and
versions, checks `available_time <= as_of` before selecting the maximum
replacement version, preserves exact replay fingerprints, and verifies that
same-version fingerprint conflicts throw instead of returning a winner.  It
restarts ClickHouse without deleting its data directory, reruns the V2
migrator, and drops only an actually owned random test database in a `finally`
cleanup.  Database creation uses a full UUID and plain `CREATE DATABASE`; a
collision fails before fixture writes and never drops an unowned database.

Point-in-time readers must preserve this ordering explicitly; background
merges are not a substitute:

```sql
WITH revision_groups AS (
  SELECT
    unified_code, interval, event_time, session, price_type,
    data_version, source, source_version, replacement_version,
    any(close) AS close,
    uniqExact(revision_fingerprint) AS revision_count
  FROM bars_minute_v2
  WHERE available_time <= {as_of:DateTime64(3, 'UTC')}
  GROUP BY unified_code, interval, event_time, session, price_type,
           data_version, source, source_version, replacement_version
  HAVING throwIf(uniqExact(revision_fingerprint) > 1,
                 'revision_fingerprint conflict') = 0
)
SELECT unified_code, interval, event_time, session, price_type,
       data_version, source, source_version,
       argMax(close, replacement_version) AS close
FROM revision_groups
GROUP BY unified_code, interval, event_time, session, price_type,
         data_version, source, source_version
HAVING max(revision_count) = 1;
```

The `available_time` predicate is intentionally inside the first grouped
query, so a future conflict does not contaminate an earlier as-of read.  The
`throwIf` is in a forced `HAVING` context; conflicting rows are retained as
evidence but no arbitrary winner is returned.

The smoke also replays one complete bar and one complete corporate-action row
under opposite JSON quote/tuple/date-time output settings.  The framing must
produce one fingerprint and one physical revision regardless of session
settings; a same-version changed payload still produces multiple fingerprints
and makes the late PIT query throw.  This V2 schema is pre-release and remains
empty in the existing `kunlun` database.  After changing `001_bars.sql` or
`002_corporate_actions.sql`, the controller may safely remove only this
node's newly created zero-row V2 objects and `v2/` metadata before rebuilding
from the final SQL.  A deployed table with data must never have its checksum
rewritten or be rebuilt in place; use a separately approved shadow/CAS
migration.
