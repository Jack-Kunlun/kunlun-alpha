# Phase 1 与已完成 Phase 2 阻断项修复实施计划

## 截至 2026-08-15 进度摘要

- 13 项任务中，Task 1–7 为 `COMPLETED/PASS`；Task 8–13 保持 `pending`。
- Phase 1：`7/8`；整体：`7/13`。
- 代码尚待本次提交；审计报告属于本地工作区记录，不作为本次提交内容。

| Task | Status |
| --- | --- |
| Task 1 | `COMPLETED/PASS` |
| Task 2 | `COMPLETED/PASS` |
| Task 3 | `COMPLETED/PASS` |
| Task 4 | `COMPLETED/PASS` |
| Task 5 | `COMPLETED/PASS` |
| Task 6 | `COMPLETED/PASS` |
| Task 7 | `COMPLETED/PASS` |
| Task 8–13 | `pending` |

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Phase 1 及已提交 Phase 2（P2-N01 至 P2-N10）审核发现的阻断项，使数据底座和情绪/轮动链路可重放、可追溯、可持久化且严格遵守点时语义。

**Architecture:** 先修正跨语言公共契约，再修复不可变原始区和增量采集语义，随后接通 PostgreSQL/ClickHouse 持久化与调度恢复，并在同一精度和时间模型上修复 Phase 2 情绪、板块轮动和回放终端。所有变更从领域契约向算法、适配器、存储和 UI 单向传播，避免重复迁移。

**Tech Stack:** TypeScript 5.7、NestJS 11、React 19、shadcn/ui、Python 3.12、Pydantic、PostgreSQL、ClickHouse、Vitest、Pytest、Ruff、BasedPyright、Docker Compose。

## Global Constraints

- 内部证券代码统一为 `600519.SH`、`000001.SZ`；供应商格式只能存在于 Provider adapter 边界。
- 贵金属范围仅限交易所上市 ETF/基金；`fundAssetClass = PRECIOUS_METALS`，`underlyingCommodity` 为 `GOLD`、`SILVER` 或 `OTHER`。
- NAV/iNAV 是点时参考字段，绝不能标记或用作可成交价格。
- 每条外部数据保留 `event_time`、`publish_time`、`ingest_time`、`available_time`、`processing_time` 中适用的时间，并使用带时区的值。
- 金额、价格、NAV、费率和复权因子在 Python 领域模型中使用 `Decimal`；数据库使用显式 Decimal/Numeric 精度。
- 原始对象内容不可变；每次请求响应必须拥有独立采集 manifest，即使响应内容完全相同。
- Phase 0 至 Phase 6 不得出现真实券商凭据、QMT 连接或真实订单路径。
- 所有文本文件使用 UTF-8 与 LF；脚本和路径必须兼容 Windows、macOS、Linux。
- 每个修复节点必须遵循 RED → GREEN → refactor，并单独接受审核。
- Phase 2 的修复仅覆盖已提交 P2-N01 至 P2-N10，不提前实现 Phase 3，也不扩大算法产品定义。

---

### Task 1: P1-R01 统一证券代码迁移

**Files:**
- Modify: `packages/contracts/schemas/instrument/*.json`
- Modify: `packages/contracts/instrument/*.json`
- Modify: `packages/contracts/src/instrument/code-parser.ts`
- Modify: `packages/contracts/src/instrument/code-parser.test.ts`
- Modify: `python/packages/market-core/src/market_core/instrument/code_parser.py`
- Modify: `python/packages/market-core/tests/test_code_parser.py`
- Modify: all Phase 1/2 fixtures and tests containing the obsolete exchange-prefix form

**Interfaces:**
- Produces: `parseInstrumentCode("600519") -> unifiedCode "600519.SH"` and `toUnifiedCode("SH", "600519") -> "600519.SH"`.
- Constraint: schemas use `^\\d{6}\\.(SH|SZ|BJ)$` and validate the suffix against `exchange`.

- [x] Add cross-language regression tests asserting suffix-form output and rejection of `SH.600519` at domain boundaries.
- [x] Run focused Vitest and Pytest tests and record the expected RED failure.
- [x] Update schemas, parsers, generated types/models and repository fixtures with the suffix form.
- [x] Mechanically migrate Phase 2 fixture/test references without changing algorithms.
- [x] Regenerate TypeScript/Python contracts and run focused tests GREEN.
- [x] Run `git diff --check` and verify no obsolete domain-form symbol remains outside explicit adapter tests.

### Task 2: P1-R02 贵金属基金与点时精度契约

**Files:**
- Modify: `packages/contracts/schemas/funds/precious-metal-fund.json`
- Create: `packages/contracts/schemas/funds/fund-nav.json`
- Modify: `packages/contracts/funds/fixtures.json`
- Modify: `packages/contracts/src/funds/validator.ts`
- Modify: `python/packages/market-core/src/market_core/funds/validator.py`
- Modify: `python/packages/market-core/src/market_core/funds/validation/nav.py`
- Modify: related TS/Python tests and generated contract files

**Interfaces:**
- Produces: metadata with `assetType`, `fundAssetClass: "PRECIOUS_METALS"`, `underlyingCommodity`, `tradingCurrency`, `navCurrency`, benchmark, recurring fees, effective interval, source, confidence and review status.
- Produces: `FundNav` carrying `Decimal` NAV/iNAV plus event/publish/ingest/available/processing timestamps and raw evidence id.

- [x] Add failing fixtures/tests for exact classification, currency separation, missing provenance, invalid effective intervals and future availability.
- [x] Add failing precision tests proving decimal inputs such as `0.1 + 0.2` are not represented through binary float.
- [x] Update schemas and validators minimally; regenerate shared TypeScript and Python models.
- [x] Replace price-sensitive Python float fields in Phase 1 market models with `Decimal` and update conversion helpers.
- [x] Verify premium/discount calculation returns `Decimal` and rejects non-positive NAV instead of fabricating zero.
- [x] Run contract, market-core and generated-file synchronization checks GREEN.

### Task 3: P1-R03 原始数据采集事件与校验重放

**Files:**
- Modify: `services/data-worker/src/data_worker/raw/manifest.py`
- Modify: `services/data-worker/src/data_worker/raw/storage.py`
- Modify: `services/data-worker/src/data_worker/raw/replay.py`
- Modify: `services/data-worker/tests/test_raw_storage.py`

**Interfaces:**
- Produces: content-addressed immutable object id plus a unique `capture_id` per response.
- Manifest fields include source, sanitized request identity, response checksum, byte size, content type, ingest/available times and object id.

- [x] Add a failing test that stores identical bytes for two request identities and expects two manifests referencing one immutable object.
- [x] Add failing checksum-corruption and deterministic replay-order tests.
- [x] Separate object storage keys from capture manifest keys and use atomic exclusive file creation.
- [x] Validate checksum and size on `get`/replay; reject path traversal in source/date/capture identifiers.
- [x] Run raw-storage tests GREEN and verify all created files use platform-aware paths.

### Task 4: P1-R04 版本化日历与分页检查点恢复

**Files:**
- Modify: `services/data-worker/src/data_worker/jobs/calendars/repository.py`
- Modify: `services/data-worker/src/data_worker/jobs/calendars/collector.py`
- Modify: `services/data-worker/tests/test_calendar_collector.py`
- Modify: `services/data-worker/src/data_worker/jobs/instruments/collector.py`
- Modify: `services/data-worker/src/data_worker/jobs/instruments/repository.py`
- Modify: `services/data-worker/tests/test_instrument_collector.py`

**Interfaces:**
- Calendar repository retrieves immutable snapshots by `version_id` and exposes a separately audited correction overlay.
- Instrument checkpoint records exchange, next cursor, run id and partial-page state; only a fully reconciled snapshot may mark missing instruments delisted.

- [x] Add failing tests that retrieve two historical calendar versions after a second collection.
- [x] Add a failing multi-page crash/restart test proving the next cursor is persisted after each accepted page.
- [x] Add a failing test proving a partial resumed run cannot delist instruments omitted from already-consumed pages.
- [x] Implement immutable version storage and run-scoped checkpoint accumulation.
- [x] Run calendar and instrument collector tests GREEN.

### Task 5: P1-R05 PostgreSQL 迁移与持久化调度

**Files:**
- Create: `packages/db/src/postgres-driver.ts`
- Modify: `packages/db/src/migrations.ts`
- Modify: `packages/db/src/index.ts`
- Modify: `apps/api/src/migrations/001-initial.ts`
- Create/Modify: database integration tests under `packages/db` and `apps/api`
- Create: `services/data-worker/src/data_worker/scheduler/postgres_store.py`
- Modify: `services/data-worker/src/data_worker/scheduler/scheduler.py`
- Modify: scheduler tests and environment documentation

**Interfaces:**
- Node driver executes parameterized PostgreSQL DDL/DML in transactions and records/removes migration versions correctly.
- Python store implements atomic lease acquisition, persistent status, attempts, next-run time, checkpoint and dead-letter detail.

- [x] After dependency approval, pin stable `pg` and `psycopg` versions and update both lockfiles.
- [x] Add failing migration tests for transactional rollback and removal of migration records during rollback.
- [x] Add failing scheduler-store tests for process restart, expired lease takeover and compare-and-set lease acquisition.
- [x] Implement PostgreSQL adapters without changing in-memory fakes used by unit tests.
- [x] Run integration tests against the Compose PostgreSQL service and document setup/rollback commands.

### Task 6: P1-R06 ClickHouse 可执行迁移与行情版本键

**Files:**
- Modify: `infra/clickhouse/migrations/001_bars.sql`
- Modify: `infra/clickhouse/migrations/002_corporate_actions.sql`
- Modify: `infra/docker/docker-compose.yml`
- Modify/Delete replacement schema in `infra/docker/init/clickhouse/01-init.sql`
- Modify: `python/packages/market-core/src/market_core/storage/storage.py`
- Modify: `python/packages/market-core/tests/test_bar_storage.py`
- Create: ClickHouse migration smoke test/script under `scripts/ci`

**Interfaces:**
- Bar identity includes instrument, interval, timestamp, price type, data version and source version as required to preserve raw and adjusted histories.
- ReplacingMergeTree uses an explicit version column; queries select deterministic latest rows without collapsing distinct semantic series.

- [x] Add failing storage tests proving RAW/FORWARD_ADJUSTED/BACKWARD_ADJUSTED and different intervals coexist at one timestamp.
- [x] Add a failing Compose/migration assertion showing the active init path does not currently load Phase 1 migrations.
- [x] Replace the obsolete Float schema and mount/copy the canonical migration directory into initialization.
- [x] Add available/ingest/processing time and provenance/version columns with Decimal price types.
- [x] Run SQL syntax/smoke checks against Compose ClickHouse and focused storage tests GREEN.

### Task 7: P1-R07 贵金属 metadata 与 NAV/iNAV 端到端管道

**Files:**
- Modify/Create: `services/data-worker/src/data_worker/jobs/precious_metals_funds/*`
- Create: normalized persistence ports/adapters under `services/data-worker/src/data_worker/storage/`
- Modify: `services/data-worker/tests/test_nav_collector.py`
- Add metadata and end-to-end pipeline tests

**Interfaces:**
- Provider capabilities distinguish fund metadata, NAV/iNAV, benchmark metadata and fee metadata.
- Pipeline is `Provider -> raw capture -> normalization -> validation -> deduplication -> storage -> quality event`.

- [x] Add failing tests for metadata capture, raw evidence linkage, point-in-time availability, source conflict, stale value and idempotent re-run.
- [x] Add a failing test proving conflicting records are preserved and no arbitrary “last source wins” value is accepted.
- [x] Implement metadata and NAV collectors using the shared raw store and persistence ports.
- [x] Persist accepted and rejected records with algorithm/schema version and all time fields.
- [x] Run focused end-to-end tests GREEN and demonstrate replay from raw data.

### Task 8: P1-R08 数据质量 API、告警与 shadcn/ui 终端接通

**Files:**
- Modify: `apps/api/src/modules/data-quality/*`
- Modify: `apps/web/src/features/data-quality/*`
- Create: web API client/query hook and route/page files
- Modify: `apps/web/src/App.tsx`
- Modify: API/web tests and operational docs

**Interfaces:**
- API reads persisted quality events and validates date/source/symbol filters.
- Web route renders loading, empty, error, forbidden and success states and links only to a safe internal evidence endpoint.

- [ ] Add failing API tests against a repository port rather than an injected constant array.
- [ ] Add failing UI tests for route reachability, loading/error/forbidden states and suffix-form security filters.
- [ ] Implement persisted repository injection, DTO validation and safe evidence lookup.
- [ ] Connect the shadcn/ui panel through the shared API client without duplicating primitives.
- [ ] Run API/web tests, accessibility checks and production builds GREEN.

### Task 9: P2-R01 情绪事实、乱序增量与点时样本修复

**Files:**
- Modify: `python/packages/emotion-core/src/emotion_core/models/limit.py`
- Modify: `python/packages/emotion-core/src/emotion_core/limit_pool/calculator.py`
- Modify: `python/packages/emotion-core/src/emotion_core/ladder/ladder.py`
- Modify: `python/packages/emotion-core/src/emotion_core/premium/premium.py`
- Modify: `python/packages/emotion-core/src/emotion_core/scoring/v1/score.py`
- Modify: corresponding emotion-core tests and emotion schemas

**Interfaces:**
- Prices and price-limit rounding use `Decimal` and the exchange tick-size rule.
- Batch and incremental limit-pool APIs produce identical facts for the same data, including out-of-order arrivals, corrections, duplicate timestamps, limit-down facts, first/last seal and open counts.
- Premium/drawdown inputs carry observation and availability times; samples unavailable at decision time are rejected.

- [ ] Add failing tests reproducing shuffled incremental input differing from batch output.
- [ ] Add failing tests for duplicate/corrected timestamps, limit-down pool, first/last seal, open count and exchange price rounding.
- [ ] Add failing point-in-time tests where a same-day close/high becomes available after the observation time.
- [ ] Implement deterministic event-time buffering/recomputation with explicit correction semantics.
- [ ] Add sample/exclusion reason fields and version/provenance to ladder, premium and emotion-score outputs.
- [ ] Run emotion-core tests GREEN and demonstrate batch/stream replay equality.

### Task 10: P2-R02 板块历史、Snapshot 与生命周期修复

**Files:**
- Modify: `packages/contracts/schemas/sector/*`
- Modify: `python/packages/rotation-core/src/rotation_core/taxonomy/sector.py`
- Modify: `python/packages/rotation-core/src/rotation_core/snapshot/snapshot.py`
- Modify: `python/packages/rotation-core/src/rotation_core/lifecycle/v1/state.py`
- Modify: corresponding rotation-core tests and algorithm documentation

**Interfaces:**
- Source-priority resolution keeps non-overlapping historical membership intervals; it only resolves overlapping conflicting records at the queried point in time.
- Snapshot accepts a taxonomy/membership resolver and decision timestamp instead of trusting a caller-supplied unversioned member list.
- Snapshot contains change, speed, turnover, breadth, leader, strength, sample/freshness, algorithm version and evidence provenance.
- Lifecycle thresholds are an explicit versioned configuration and transitions retain evidence fields.

- [ ] Add a failing test proving two non-overlapping histories from one source are both queryable.
- [ ] Add failing point-in-time membership and unavailable-bar tests.
- [ ] Add failing tests for speed, freshness/sample count and batch/stream corrections.
- [ ] Implement interval-aware source resolution and versioned snapshot evidence.
- [ ] Extract lifecycle thresholds into immutable V1 configuration and persist complete transition evidence.
- [ ] Run rotation taxonomy/snapshot/lifecycle tests GREEN.

### Task 11: P2-R03 RotationEvent 顺序、去抖与幂等修复

**Files:**
- Modify: `python/packages/rotation-core/src/rotation_core/events/events.py`
- Modify: `python/packages/rotation-core/tests/test_rotation_events.py`

**Interfaces:**
- Input points require timezone-aware, monotonic event timestamps or are deterministically sorted/deduplicated before detection.
- Empty strength maps create a quality issue or are explicitly skipped; they never raise `max()` errors.
- Event identity/version makes repeated overlapping-window execution idempotent.

- [ ] Add failing tests for empty strengths, reverse chronological input, duplicate timestamps and overlapping replay windows.
- [ ] Add failing tests for a brief lead between two sustained runs so ignored jitter does not fabricate a direct historical transition.
- [ ] Implement ordered normalization, tie policy, event identity and versioned evidence window boundaries.
- [ ] Run focused RotationEvent tests GREEN.

### Task 12: P2-R04 情绪与轮动持久化回放终端

**Files:**
- Modify: `apps/api/src/modules/emotion/*`
- Modify/Create: emotion/rotation repository adapters and persistence schemas
- Modify: `apps/web/src/features/market-regime/*`
- Create: web page, API client/query hook and route
- Modify: `apps/web/src/App.tsx`
- Modify: API/web tests and runbooks

**Interfaces:**
- Historical and real-time endpoints share a versioned contract and both read persisted snapshots/events.
- Queries validate trading date, algorithm version and optional sector filters.
- UI renders loading, empty, error, forbidden and success states and shows freshness, sample size, version and evidence confidence.

- [ ] Add failing repository-backed API tests for arbitrary historical trading dates and multiple coexisting algorithm versions.
- [ ] Add failing UI tests proving the route is reachable and all required states render.
- [ ] Replace the injected empty array with a persistent repository port and adapter.
- [ ] Connect the shadcn/ui page through the shared API client and add rotation-event display/filtering.
- [ ] Run API/web tests, accessibility checks and production builds GREEN.

### Task 13: P1/P2-R05 阶段退出门禁与文档收口

**Files:**
- Modify: relevant runbooks, contracts and Phase 1 evidence documentation
- Create: `docs/reviews/phase1-repair-evidence.md`
- Modify: cross-platform CI only where required by new integration checks

**Interfaces:**
- Produces one traceable evidence packet mapping every Phase 1/2 blocking finding to tests, commands and implementation files.

- [ ] Run format check, lint, type checking, generated-contract checks, focused tests, full tests and builds.
- [ ] Start PostgreSQL/ClickHouse through Compose and execute migration, restart and replay smoke tests.
- [ ] Scan for obsolete `SH.600000`-style domain codes, price-sensitive floats, missing point-in-time fields, unmounted migrations and broker/QMT paths.
- [ ] Replay one complete historical trading day and compare batch versus streaming emotion/rotation outputs byte-for-byte.
- [ ] Verify LF normalization and cross-platform path behavior.
- [ ] Record actual outputs, remaining limitations and commit hashes; request independent final audit.

## Self-review result

- All nine Phase 1 audit blockers and the confirmed Phase 2 blockers map to at least one task.
- Contract changes precede their storage and UI consumers.
- Persistence and Compose integration are isolated from domain calculations.
- No placeholder implementation steps or Phase 3/live-trading scope are included.
- New production dependencies are gated on explicit user approval before Task 5.
