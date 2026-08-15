# P1-R07 precious-metals fund ingestion

This runbook describes the Phase 1 ingestion boundary for exchange-listed
precious-metals funds.  It is a reference-data pipeline only: NAV and iNAV are
point-in-time research values and never executable prices.

## Pipeline and boundaries

The collector requires an independently advertised provider capability for
each endpoint:

- `FETCH_FUND_METADATA`
- `FETCH_FUND_NAV`
- `FETCH_FUND_INAV`
- `FETCH_FUND_BENCHMARK`
- `FETCH_FUND_FEES`

An unsupported endpoint fails before a request is treated as trusted data; the
collector never invents an empty field or derives iNAV from NAV.  A successful
provider returns `RawFundProviderResponse` (bytes plus safe transport
metadata); the collector does not accept a separately reconstructed
`Page/items` value.  A successful page follows this order:

```text
provider -> RawStorage.put -> normalize -> validate -> conflict-aware persist
         -> quality/evidence links -> checkpoint
```

Raw bytes and a response manifest are written before normalization.  The
evidence envelope links `raw_capture_id`, `raw_object_id`, checksum, source,
versions, payload digest, item ordinal, and the applicable event/publish/
ingest/available/processing timestamps.  Record identity is
`capture_id:item_ordinal`.  A logical observation identity is a stable hash of
kind, source, semantic key, source revision, and canonical content digest.
Replaying the same capture is idempotent, while changed content under one
evidence id raises a conflict.  Separate captures remain separate evidence
links even when their bytes are equal, while equal logical content is stored
once.  Benchmark and fee observations use independent tables; fee rates stay
`Decimal` values and are never promoted to complete metadata.

After `RawStorage.put`, the collector reads the manifest back with checksum
and size verification and decodes that verified copy.  A
`TrustedFundContext` then binds source, capture/object identity, ingest time,
transport availability floor, processing time, route, run, and source
revision to the manifest.  Payload availability may move later but never
earlier; a payload `rawObjectId`, when present, must match the manifest.  The
five routes (`metadata`, `nav`, `inav`, `benchmark`, and `fees`) are validated
before capture and replay, so payload fields cannot forge provenance.

## Trust-chain audit repair controls

The persistence adapters expose the same fail-closed contract in memory and
in PostgreSQL.  A stored candidate keeps its canonical semantic key/value;
metadata reads use the database row's logical `observation_id`, not its
evidence `record_id`.  A checkpoint rejects `next_cursor` and
`consumed_cursors` at the boundary, and the PostgreSQL compatibility column
`checkpoints.cursor` is always written as `NULL`.

Evidence is a first-write claim: one `record_id` cannot move between accepted
and rejected state or claim another accepted logical kind.  Conflicts are
validated before page/checkpoint commit, so a rejected second page leaves no
partial logical, evidence, rejection, quality, or checkpoint mutation.
Quality events persist only a controlled value-free digest of the detail.
Their kind, semantic key, sorted evidence IDs, and digest are immutable;
`created_at` is first-write metadata, so a replay with a different collector
clock is idempotent while changed fields or links fail closed.  Logical
observation `created_at` and evidence `processing_time` follow the same
first-write rule.

Raw provider and manifest `content_type` values are normalized to a bounded
ASCII MIME type/subtype.  Only a controlled `charset` parameter is accepted;
Bearer/Basic/Cookie/credential/token/DSN-like values and arbitrary parameters
are rejected before capture or durable storage.

## PostgreSQL setup

Run the existing Phase 1 migrations first, then explicitly apply
`data_worker.storage.apply_precious_metals_migration(connection)`.  The
migration is additive and creates evidence, metadata, NAV, iNAV, rejection and
quality-event link tables.  It does not rewrite version 1 tables or historical
rows.  Price/reference values use PostgreSQL `NUMERIC(30,12)`; floating-point
columns are not permitted.  The canonical SQL is loaded as one package
resource and its SHA-256 is recorded in the `data_worker_schema_migrations`
ledger.  Migration takes the transaction-scoped advisory lock
`kunlun-alpha.schema-migrations`, verifies the existing Phase 1 base schema,
and fails closed on partial tables, rogue columns, or checksum/name drift.

`PostgresFundStorage.commit_page` requires a scheduler lease context.  It
locks and verifies the current task token and
`lease_expires_at > CURRENT_TIMESTAMP` in the same transaction, then commits
observations, rejected records, quality/evidence links, and the checkpoint as
one unit.  A stale or expired context raises `LeaseFenceError` and writes
nothing.  Evidence, rejection, logical-observation and quality-event IDs are
serialized with transaction-scoped advisory locks before exact-equality
compare/insert, so concurrent equal retries are no-ops and changed content
rolls back the complete page.

Example (the DSN is supplied by the caller and must not be written to logs):

```python
import psycopg

from data_worker.storage import PostgresFundStorage

with psycopg.connect(dsn) as connection:
    storage = PostgresFundStorage(connection)
    storage.migrate()
```

For local integration verification, set the non-production environment
variable `KUNLUN_TEST_POSTGRES_DSN`.  The test creates a unique `task7_*`
schema, runs the migration twice, verifies exact NUMERIC/evidence joins and a
restart, tests stale-lease zero writes, then rolls back any open transaction
and commits schema teardown.  Do not start privileged Docker commands as part
of this runbook; the Compose PostgreSQL instance is an optional caller-owned
precondition.

The verifier compares the complete task-owned catalog state before the
migration ledger advances: ordered columns and types, defaults and
collations, primary/unique/check/foreign-key definitions and actions, and
indexes including order, access method, expressions, opclasses, collations,
predicates, and `NULLS NOT DISTINCT`.  Missing, changed, or extra task-owned
metadata fails closed.  A catalog or checksum failure rolls back the same
transaction and leaves no migration-ledger advancement.

## Recovery and replay

Raw capture may succeed before a process crashes.  Call
`FundCollector.replay_captures(kind, source, collection_date, run_id=...,
source_revision=...)` to verify and replay only manifests on that route
through the normal normalization and persistence path.  Legacy manifests
without route fields are rejected rather than mixed into a replay.  A database
commit followed by a crash before returning is safe to replay because evidence
and observations use stable identities and conflict checks.  Recovery is an
at-least-once rescan from page one: remote cursors are process-local only.  A
new collect attempt receives a fresh immutable `attempt_id`; each captured
page has a zero-based `page_ordinal`.  Checkpoints contain the route, active
attempt, committed page count, last capture id, a one-way cursor-lineage hash,
and `complete`; plaintext cursors are never persisted.  Replay selects one
explicit attempt, requires a contiguous ordinal sequence, rejects duplicate or
unknown cursor transitions, and never falls back to page zero.  A provider
without a source revision uses the controlled `source-revision-absent`
sentinel; providers cannot claim that reserved value.  Only the final page is
complete, and repeated cursors raise `CursorLoopError`.

Rejected records retain bounded, redacted payloads and an evidence envelope.
Request identities use the P1-R03 sanitization rules; headers, bodies,
credentials, cookies, opaque provider tokens, and unbounded exception text are
not persisted.  Scheduler jobs accept the smallest backward-compatible lease
context extension: existing zero-argument jobs continue to run, while an
ingestion job can receive the owner task id, token, and expiry.

Provider failures are translated at the real fetch boundary.  Timeout,
rate-limit, and unavailable errors are transient; authentication, not-found,
and data errors are permanent; unknown exceptions are recorded as controlled
`internal` failures and never leave a task in `RUNNING`.  Durable details keep
the category/message contract and never copy provider exception text.

## Operational checks

Run the focused tests before a broader data-worker suite:

```powershell
$env:PYTHONPATH = "python/packages/ashare-contracts/src;python/packages/market-core/src;services/data-worker/src"
.venv\Scripts\python.exe -m pytest services/data-worker/tests/test_precious_metals_*.py -q --no-cov
.venv\Scripts\python.exe -m pytest services/data-worker/tests -q --no-cov
.venv\Scripts\ruff.exe check services/data-worker/src/data_worker/jobs/precious_metals_funds services/data-worker/src/data_worker/storage services/data-worker/src/data_worker/scheduler
.venv\Scripts\basedpyright.exe services/data-worker/src/data_worker/jobs/precious_metals_funds services/data-worker/src/data_worker/storage services/data-worker/src/data_worker/scheduler
```

The live PostgreSQL selectors are skipped when `KUNLUN_TEST_POSTGRES_DSN` is
absent; when it is present, the migration, restart, stale-lease, exact-conflict
and concurrent-idempotency checks must pass and leave no `task7_*` schema
behind.  Never use production credentials or production data for this check.

For the final P1-R07 closure, also run the full data-worker and market-core
suites, the PostgreSQL migration/storage/scheduler selectors, the `@kunlun/db`
and `@kunlun/api` test/lint/typecheck/build matrix, and the packaged-SQL
resource test.  Use a short `--basetemp` path on Windows and inject the local
DSN only through a temporary environment variable; never print or persist the
DSN.  The closure gate additionally checks LF/UTF-8 hygiene, the absence of a
public legacy `NavCollector`/`Page` fund path, the absence of broker/QMT/live
order symbols, zero isolated-schema residue, and `git diff --check`.
