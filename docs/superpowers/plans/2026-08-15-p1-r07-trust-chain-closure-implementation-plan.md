# P1-R07 Trust-Chain Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five remaining P1-R07 trust-chain, replay, security, error-classification, and migration-verification blockers.

**Architecture:** Keep raw bytes, manifests, logical observations, evidence links, lease-fenced page commits, and the independent migration ledger as the established boundaries. Add one trusted normalization context, controlled rejection diagnostics, explicit replay attempt lineage, wired provider error translation, and exact PostgreSQL catalog comparison.

**Tech Stack:** Python 3.12.13, psycopg 3.3.4, PostgreSQL 17, Pytest, Ruff, BasedPyright, TypeScript/Vitest for affected DB/API verification.

## Global Constraints

- Work only inside P1-R07; do not start P1-R08.
- Do not add dependencies, broker/QMT paths, API/Web behavior, ClickHouse, or Phase 2 changes.
- Preserve all unrelated worktree changes; do not commit or push.
- Use UTF-8 and LF.
- Write and run each focused RED before its production change.
- Money/reference values remain Decimal/NUMERIC; NAV/iNAV remain non-executable.

---

### Task 1: Bind normalization to the trusted manifest context

**Files:**
- Modify: `services/data-worker/src/data_worker/jobs/precious_metals_funds/collector.py`
- Modify: `services/data-worker/src/data_worker/raw/manifest.py`
- Modify: `services/data-worker/src/data_worker/raw/storage.py`
- Test: `services/data-worker/tests/test_precious_metals_audit_raw.py`
- Test: `services/data-worker/tests/test_precious_metals_pipeline.py`

**Interfaces:**
- Consumes: verified `RawObjectManifest` and decoded item mappings.
- Produces: immutable `TrustedFundContext` used by every normalization path.

- [ ] **Step 1: Add failing provenance regressions**

  Add tests proving payload `source`, early `ingestTime`/`availableTime`, forged
  `processingTime`, and mismatched `rawObjectId` cannot override the manifest.
  Add an endpoint-kind allowlist test.

- [ ] **Step 2: Run the RED tests**

  Run:
  `python -m pytest services/data-worker/tests/test_precious_metals_audit_raw.py -q --no-cov --basetemp .pytest-tmp-p1-r07c-raw-red`

  Expected: focused assertion failures showing payload values are currently
  accepted.

- [ ] **Step 3: Implement `TrustedFundContext`**

  Build it only after `RawStorage.get(object_id, checksum, size)` succeeds.
  Force manifest source/ingest/object values, use `max(payload_available,
  manifest.available_time)`, set processing time from the collector clock, and
  reject a mismatched payload raw object ID.

- [ ] **Step 4: Run GREEN and raw compatibility tests**

  Run the RED command again plus `test_raw_storage.py`; expect all selected
  tests to pass.

### Task 2: Replace raw rejection text with controlled diagnostics

**Files:**
- Modify: `services/data-worker/src/data_worker/jobs/precious_metals_funds/collector.py`
- Modify: `services/data-worker/src/data_worker/storage/precious_metals.py`
- Test: `services/data-worker/tests/test_precious_metals_audit_semantics.py`
- Test: `services/data-worker/tests/test_precious_metals_postgres_adapter.py`

**Interfaces:**
- Consumes: failed decoded item, controlled reason code, item digest, evidence.
- Produces: `RejectedObservation` without raw values or exception text.

- [ ] **Step 1: Add failing leakage tests**

  Exercise the real collector with a nested bearer token, PostgreSQL DSN,
  cookie, non-mapping value, and Pydantic validation error containing an input
  value. Assert none appears in the in-memory rejection, SQL parameters, or
  persisted PostgreSQL row.

- [ ] **Step 2: Run RED**

  Run the two focused test files and verify failures expose the current
  `repr(item)`/`str(exc)` behavior.

- [ ] **Step 3: Implement controlled rejection codes**

  Persist only reason code, bounded safe field names, digest, and evidence.
  Remove raw `repr` and exception strings from production construction paths.

- [ ] **Step 4: Run GREEN and live adapter tests**

  Re-run the focused tests with the local test DSN; expect safe exact rows and
  no leaked values.

### Task 3: Wire provider error taxonomy into the scheduler path

**Files:**
- Modify: `services/data-worker/src/data_worker/jobs/precious_metals_funds/collector.py`
- Modify: `services/data-worker/src/data_worker/scheduler/scheduler.py` only if the existing controlled category interface is insufficient
- Test: `services/data-worker/tests/test_precious_metals_audit_recovery.py`
- Test: `services/data-worker/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `ProviderTimeoutError`, `ProviderRateLimitError`,
  `ProviderUnavailableError`, `ProviderAuthError`, `ProviderNotFoundError`, and
  `ProviderDataError` from the real provider fetch call.
- Produces: controlled transient/permanent scheduler errors with no raw message.

- [ ] **Step 1: Add real-path RED tests**

  Invoke `TaskScheduler.run()` with a job that calls `FundCollector.collect()`
  against providers raising each error. Assert durable status, category,
  backoff/dead-letter behavior, and safe detail.

- [ ] **Step 2: Run RED and confirm helper-only wiring fails**

- [ ] **Step 3: Translate errors at `_fetch_page`**

  Call the controlled mapping at the provider boundary. Preserve the unknown
  exception `internal` behavior without storing its text.

- [ ] **Step 4: Run GREEN scheduler and provider tests**

### Task 4: Make rescan replay deterministic by attempt and page ordinal

**Files:**
- Modify: `services/data-worker/src/data_worker/raw/manifest.py`
- Modify: `services/data-worker/src/data_worker/raw/storage.py`
- Modify: `services/data-worker/src/data_worker/jobs/precious_metals_funds/collector.py`
- Modify: `services/data-worker/src/data_worker/storage/precious_metals.py`
- Test: `services/data-worker/tests/test_precious_metals_audit_recovery.py`
- Test: `services/data-worker/tests/test_precious_metals_recovery.py`
- Test: `services/data-worker/tests/test_raw_storage.py`

**Interfaces:**
- Consumes: trusted `run_id`, generated `attempt_id`, zero-based
  `page_ordinal`, endpoint kind, controlled source-revision sentinel.
- Produces: a contiguous, explicitly selected replay attempt.

- [ ] **Step 1: Add failing restart/replay tests**

  Capture page 0, crash, rescan page 0 under a new attempt, finish page 1, then
  replay each attempt explicitly. Add duplicate/missing ordinal, unknown
  cursor, absent source revision, and all-five-endpoint cases.

- [ ] **Step 2: Run RED**

  Confirm current run-wide manifest selection produces duplicate cursor or
  fallback behavior.

- [ ] **Step 3: Add immutable attempt lineage**

  Write attempt ID and page ordinal atomically in each new manifest without
  changing legacy canonicalization. Persist the active attempt in the safe
  checkpoint. Replay requires an explicit attempt and contiguous page order;
  remove fallback-to-page-zero behavior.

- [ ] **Step 4: Run GREEN recovery/raw tests**

### Task 5: Verify complete PostgreSQL migration catalog state

**Files:**
- Modify: `services/data-worker/src/data_worker/storage/migrations.py`
- Test: `services/data-worker/tests/test_precious_metals_migration_audit.py`

**Interfaces:**
- Consumes: canonical SQL checksum and `pg_catalog` metadata.
- Produces: exact pass/fail result for columns, constraints, foreign keys, and indexes.

- [ ] **Step 1: Add one RED per missing catalog dimension**

  Add live tests for changed index order/method/predicate, extra index, missing
  and extra PK/unique/check/FK constraints, changed FK actions, and each
  non-negative check declared by canonical SQL.

- [ ] **Step 2: Run RED against the local random-schema fixture**

- [ ] **Step 3: Implement structured catalog comparison**

  Query normalized `pg_catalog` fields and compare exact expected sets. Do not
  use substring matching. Reject any task-owned extra or missing metadata
  before ledger advancement.

- [ ] **Step 4: Run GREEN migration tests**

  Include migrate twice, two-connection concurrency, checksum drift, rollback,
  restart, package-resource, and isolated-schema cleanup assertions.

### Task 6: Final documentation and acceptance matrix

**Files:**
- Modify: `.superpowers/sdd/2026-08-14-phase1-repair-implementation-plan/task-7-brief.md`
- Modify: `.superpowers/sdd/2026-08-14-phase1-repair-implementation-plan/task-7-report.md`
- Modify: `docs/development/precious-metals-fund-ingestion.md`

**Interfaces:**
- Consumes: actual RED/GREEN outputs from Tasks 1-5.
- Produces: final evidence packet for independent review.

- [ ] **Step 1: Run formatting and static checks**

  Run Ruff format/check and BasedPyright on all changed Python files.

- [ ] **Step 2: Run affected and broad tests**

  Run all precious-metals/raw/scheduler tests, full data-worker, full
  market-core, live PostgreSQL tests, and DB/API tests, lint, typecheck, and
  builds.

- [ ] **Step 3: Run hygiene checks**

  Verify package SQL resource, isolated schema cleanup, LF, no legacy public
  `NavCollector`/`Page` bypass, no broker path, and `git diff --check`.

- [ ] **Step 4: Update evidence documents**

  Record every actual command/result, deviations, remaining risks, and the fact
  that no commit or push was performed.

- [ ] **Step 5: Request a fresh independent Terra audit**

  Do not mark P1-R07 complete until the audit reports no correctness blocker.
