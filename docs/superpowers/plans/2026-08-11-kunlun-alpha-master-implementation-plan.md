# Kunlun Alpha Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Kunlun Alpha as an A-share and exchange-listed precious-metals funds intelligence, quantitative research, simulation, and finally risk-controlled QMT trading platform.

**Architecture:** Use a Turborepo/pnpm/uv monorepo with React and shadcn/ui for the terminal, NestJS for the control plane, independently testable Python domain engines, and adapter-based integrations. PostgreSQL stores business state, ClickHouse stores analytical time series, Redis stores live state, and MinIO/COS stores immutable raw and research artifacts. Real broker execution is physically and logically excluded until Phase 7.

**Tech Stack:** React, TypeScript, Vite, shadcn/ui, Tailwind CSS, NestJS, Python, PostgreSQL, ClickHouse, Redis, MinIO/COS, DuckDB, Polars, Parquet, Docker Compose, OpenTelemetry, Prometheus, Grafana, Loki, Turborepo, pnpm, uv.

## Global Constraints

- Resolve and pin the latest stable release of each technology when its setup node begins; do not use prerelease or floating versions.
- All text and source files use UTF-8 and LF, except explicitly identified Windows batch files.
- The repository must work on Windows, macOS, and Linux; never hard-code platform paths or shell-only assumptions.
- The root `.editorconfig` and `.gitattributes` are mandatory and enforced in CI.
- TypeScript uses strict mode; Python uses full type annotations and Pyright.
- shadcn/ui is the default web component system; do not create competing primitive components.
- Use TDD for features and fixes; every node covers success, boundary, and failure behavior.
- Contracts are defined before producers and consumers; modules depend only on published interfaces.
- Internal symbols use `600519.SH` / `000001.SZ`; timestamps are timezone-aware; money and prices use decimal-safe types.
- Scores, factors, features, schemas, prompts, and algorithms are versioned and historical results are immutable.
- Phase 0–6 cannot contain a callable path that creates a real broker order.
- Precious-metals scope is limited to exchange-listed ETFs/funds; physical bullion, spot contracts, futures, margin, rollover, and delivery require a separate approved project.
- One WorkBuddy assignment equals one node; every node ends with tests, checks, documentation, and a focused Conventional Commit.

---

## Execution Protocol

For every node:

- [ ] Read the node card and its dependencies in the Word implementation handbook.
- [ ] Write the smallest failing test or validation fixture that demonstrates the required behavior.
- [ ] Run the narrow test and record the expected failure.
- [ ] Implement only the node scope; do not pull work from later nodes.
- [ ] Run formatting, static analysis, narrow tests, then the affected package test suite.
- [ ] Update contracts, examples, ADRs, and operational notes named by the node.
- [ ] Commit with the node ID in the body and provide the review evidence packet.
- [ ] Stop for Codex review before starting the next node.

## Phase Plans

The authoritative node cards, file areas, acceptance checks, review risks, and phase exit gates are maintained in `outputs/昆仑智策项目总体规划与分阶段实施手册.docx`.

### Phase 0 — Engineering Foundation

Creates repository policy, workspace roots, web/API/Python skeletons, contracts, local infrastructure, observability, CI, and developer documentation. Exit requires a clean three-platform bootstrap path and zero real-trading capability.

### Phase 1 — A-share Data Foundation

Creates instrument/calendar schemas, provider contracts, raw-zone storage, ingestion and validation pipelines, PostgreSQL/ClickHouse models, recovery, reconciliation, and data-quality dashboards. Adds `P1-N13` for precious-metals fund classification/contracts and `P1-N14` for metadata, NAV/iNAV ingestion, validation, storage, and monitoring.

### Phase 2 — Market Emotion and Rotation

Creates limit-pool facts, board-ladder metrics, deterministic versioned emotion scoring, sector snapshots, lifecycle classification, rotation-event detection, replay, APIs, and visualizations.

### Phase 3 — Event and Hotspot Intelligence

Creates immutable content ingestion, normalization, deduplication, entity/event extraction, evidence and prompt registries, stock/topic resolution, hotspot aggregation, feedback, evaluation, APIs, and terminal views.

### Phase 4 — Seat and KOL Intelligence

Creates seat alias resolution and performance features, KOL content/ASR/OCR pipelines, claim/evidence modeling, performance tracking, consensus features, audit tools, APIs, and UI views.

### Phase 5 — Feature Store, Research, and Backtest

Creates a shared feature registry, online/offline materialization, point-in-time correctness, datasets, factor research, event studies, realistic A-share order simulation, accounting, metrics, reproducibility, and regression suites. Adds `P5-N14` for point-in-time precious-metals fund premium/discount, tracking, liquidity, and benchmark features.

### Phase 6 — Decision Terminal and Paper Portfolio

Creates the intelligence terminal, watchlists, rankings, drill-downs, alerts, paper accounts, signal-to-intent flow, simulated fills, risk preview, reconciliation, recovery, reporting, and endurance tests. Adds `P6-N13` for the precious-metals funds view, comparisons, event timeline, stale-data states, and alerts.

### Phase 7 — QMT, Risk, and Live Trading

Creates a separately deployable execution boundary, QMT adapter, paper-first lifecycle, independent risk engine, idempotent order state machine, reconciliation, kill switch, approvals, observability, disaster drills, and small-capital live gates.

## Handoff

Implementation covers 98 nodes and must proceed node-by-node from the Word handbook. Do not dispatch an entire phase as one assignment. A later node may start only after its declared predecessors pass Codex review.
