# Kunlun Alpha Repository Instructions

## 1. Project identity

This repository is **昆仑智策 (Kunlun Alpha)**, an A-share and exchange-listed precious-metals funds intelligence, quantitative research, backtesting, paper-trading, risk-control, and eventually QMT execution platform.

Brand line: **观势 · 知势 · 策势**.

The platform is developed in eight ordered phases:

- Phase 0: engineering foundation
- Phase 1: A-share data foundation
- Phase 2: market emotion and sector rotation
- Phase 3: event and hotspot intelligence
- Phase 4: seat and KOL intelligence
- Phase 5: feature store, research, and backtesting
- Phase 6: decision terminal and paper portfolio
- Phase 7: QMT, independent risk control, and live trading

Real trading is not an early milestone. Phase 0 through Phase 6 must remain incapable of placing a real broker order.

## 2. Instruction precedence and scope

These instructions apply to the entire repository.

Use this precedence when instructions conflict:

1. The user's explicit instruction for the current task.
2. The closest applicable `AGENTS.override.md` or `AGENTS.md`.
3. Approved project specifications and implementation plans.
4. Established patterns in the code being changed.
5. General preferences in this file.

A nested instruction file may add stricter or module-specific rules. It may not weaken the live-trading, credential, audit, data-integrity, or verification rules in this file.

Do not silently resolve a conflict that changes scope, architecture, data semantics, security, or real-money behavior. Stop and ask for direction.

## 3. Authoritative project documents

Read only the parts needed for the current task. Before implementing a development node, use:

- `docs/superpowers/specs/2026-08-11-kunlun-alpha-master-plan-design.md`
- `docs/superpowers/plans/2026-08-11-kunlun-alpha-master-implementation-plan.md`
- `outputs/昆仑智策项目总体规划与分阶段实施手册.docx`

For repository-agent behavior, also read:

- `docs/superpowers/specs/2026-08-11-kunlun-alpha-agents-design.md`
- `docs/superpowers/plans/2026-08-11-kunlun-alpha-agents-implementation-plan.md`

The Word handbook is the authoritative catalog for the 98 development-node cards. Do not copy all node cards into code comments or new planning files.

If a document and the current code disagree, investigate the reason. Do not automatically rewrite the code or the document. Report the mismatch and make the smallest approved correction.

For documentation or policy maintenance, read the applicable instructions and affected documents; do not invent a development node or scan the entire handbook. Product release scope is separate from phase completion: use `docs/superpowers/plans/2026-10-12-v1.0-release-plan.md` for 1.0.0 and `docs/superpowers/plans/2026-10-16-post-v1-roadmap.md` for weekly module slices. A roadmap entry does not authorize implementation or claim that a capability is available.

The lightweight workflow below, approved on 2026-10-16, governs routine execution and release acceptance when older workflow documents require broader checks or reports. Domain acceptance criteria and the security, audit, data-integrity, and live-trading rules remain mandatory.

## 4. Agent roles and collaboration

The primary agent handles bounded research, implementation, and final acceptance directly by default. Delegate only an independent task with a clear benefit; do not create an automatic research → implementation → review chain. A logical review step does not require another agent for routine changes. High-risk changes require one independent review of the final affected code; later fixes need only a finding-closure check unless they materially change the risk or scope.

### WorkBuddy and implementation agents

- Implement one approved development node at a time.
- Keep strictly to the node's objective, dependencies, file area, deliverables, acceptance criteria, and non-goals.
- Produce the concise result record defined below and resolve blocking findings before a dependent node.
- Continue within the user's already authorized scope after acceptance; do not repeatedly request human confirmation or create another report for the same evidence.

### Codex and review agents

- Review the implementation against the node card and repository rules.
- Lead with blocking findings and concrete evidence.
- Check requirements, architecture, types, data correctness, tests, security, cross-platform behavior, UI quality, operations, and scope discipline.
- Do not approve a node only because the code builds or the author reports success.
- Inspect relevant command output before making a completion claim. Reuse valid results under Section 16; re-run only evidence invalidated by a relevant change, failure, or identified gap.

### Other coding agents

Follow the implementation-agent workflow unless the user explicitly assigns a review-only or diagnosis-only role.

## 5. One-node task boundary

One implementation assignment equals one bounded development node, normally identified as `P{phase}-N{sequence}` such as `P0-N02`. Explicit documentation, policy, or release-planning maintenance is a bounded task of its own and does not require a fabricated node ID.

When the user supplies a node ID:

- Treat that node as the hard scope boundary.
- Read its direct predecessor and phase exit gate.
- Do not implement later-node conveniences preemptively.

When the user does not supply a node ID:

- Map the request to the smallest matching node in the handbook.
- State the chosen node before making changes.
- If multiple nodes would materially change the result, ask the user to choose or authorize a small decomposition.

Never treat a complete Phase, service, engine, terminal, or trading system as one implementation task.

## 6. Required execution workflow

Use one short plan in the conversation; routine changes do not need a separate planning document.

1. **Orient and inspect**: read applicable instructions and the affected node/code or documents; preserve existing worktree changes.
2. **Bound the work**: state the observable outcome, task type/risk, affected area, and finite verification budget. Existing authorization covers routine choices within that scope.
3. **Implement minimally**: use TDD for feature/defect behavior, then make the smallest correct change. Reversible documentation, copy, or styling work uses direct checks rather than artificial failing tests.
4. **Verify and review**: select checks under Section 16; inspect the final diff and the relevant architecture, data, security, and platform impacts. Complete one independent review when risk requires it.
5. **Document and deliver**: update only required documentation and give the concise result record in Section 22. Resolve blockers and continue authorized work without restarting acceptance for a completed slice.

Deliver usable core behavior first, repair actual usage blockers next, and perform release acceptance at the end. Do not move a full recovery drill or a complete release gate into every development task. Never claim a check passed without actual output or valid reusable evidence.

## 7. Worktree and change safety

- Treat existing changes as user-owned unless proven otherwise.
- Do not reset, discard, overwrite, reformat, move, or delete unrelated changes.
- Do not use destructive Git operations such as `git reset --hard` or broad checkout restoration.
- Prefer focused patches and reversible migrations.
- Before deletion or a destructive migration, resolve the exact targets, explain recovery, and obtain explicit authorization when the action is not already unambiguously requested.
- Do not initialize, rewrite, commit, push, open a PR, or alter branches unless the user requested or approved that action.

## 8. Target architecture and dependency direction

The intended repository layout is:

```text
apps/                 React terminal and NestJS control plane
services/             independently deployable engines and workers
python/packages/      reusable Python domain libraries
packages/             UI, contracts, clients, types, and configuration
infra/                local and production infrastructure
research/             notebooks, experiments, evaluations, and reports
data/                 fixtures and sanitized samples only
docs/                 architecture, ADRs, algorithms, runbooks, compliance
scripts/              cross-platform developer, CI, and operations entry points
```

Dependency rules:

- `apps` and `services` may depend on reusable packages.
- Reusable packages must not depend on deployable applications or services.
- Domain libraries expose public interfaces; consumers must not import internal implementation paths.
- NestJS is the control plane. Heavy quantitative computation belongs in Python engines.
- Strategies produce `Signal` or `OrderIntent`; they never depend on broker SDKs.
- External data sources, object storage, LLM providers, and brokers are accessed through adapters.
- Define and version contracts before implementing producers and consumers.
- Avoid circular dependencies, universal service classes, and oversized entry-point files.

## 9. Technology and dependency policy

- At the start of a setup or upgrade node, resolve the latest stable release from an official source and pin it.
- Do not use alpha, beta, release-candidate, nightly, canary, or floating versions in production paths.
- Pin Node.js, pnpm, Python, and uv at the repository root.
- Use exact JavaScript dependency versions and commit `pnpm-lock.yaml`.
- Use bounded Python dependency versions and commit `uv.lock`.
- Pin Docker images to explicit versions; never use the `latest` tag.
- A dependency upgrade is a separate node with compatibility notes, verification evidence, and rollback instructions.
- Do not add a production dependency when a small existing or standard-library solution is sufficient.
- Ask before adding a materially new production dependency or managed service.

## 10. File format and three-platform support

All source code and text configuration must be UTF-8 with LF line endings.

- Root `.editorconfig` is mandatory and must include `end_of_line = lf`.
- Root `.gitattributes` is mandatory and must normalize text to LF.
- Only explicitly Windows-specific `.bat` and `.cmd` files may use CRLF.
- Respect the approved EditorConfig exceptions for Python, Markdown, YAML, and Makefiles.
- Use platform-aware path APIs. Do not hard-code `\`, `/`, drive letters, user home paths, or `/tmp`.
- Prefer cross-platform Node.js or Python scripts over duplicated shell scripts.
- Commands and developer workflows must work on Windows, macOS, and Linux.
- CI should run the full suite on Linux and validate bootstrap, lint, type checking, and core tests on Windows and macOS.

## 11. TypeScript rules

- Enable strict TypeScript settings, including safe indexed access where practical.
- Do not use `any` without a documented reason and a narrow boundary.
- Receive untrusted external input as `unknown`, then validate it with the shared contract layer.
- Use generated or shared contract types instead of recreating API shapes by hand.
- Expose explicit package public APIs; avoid deep imports into another package.
- Separate server state, form state, and local interaction state.
- Pages and React components must not construct backend URLs or raw request payloads directly.
- Keep modules and files focused on one responsibility.

## 12. Python rules

- Public functions, classes, and domain boundaries require complete type annotations and must pass Pyright.
- Separate I/O orchestration from deterministic domain computation.
- Prefer pure functions and immutable inputs for calculations, scoring, features, and backtests.
- Use timezone-aware `datetime` values.
- Use `Decimal` or integer minor units for money and price-sensitive accounting; do not use uncontrolled binary floating point.
- Production code must not be copied directly from notebooks without extraction, typing, tests, and review.
- Services may depend on domain packages; domain packages must not depend on services.

## 13. Data, time, and version semantics

- Internal security symbols use forms such as `600519.SH` and `000001.SZ`.
- Do not allow vendor-specific symbol formats beyond adapter boundaries.
- Distinguish `event_time`, `publish_time`, `ingest_time`, `available_time`, and `processing_time`.
- Store timezone-aware timestamps and render user-facing time in `Asia/Shanghai` unless a product requirement says otherwise.
- Research, features, rankings, and backtests must use only data whose `available_time` is not later than the decision time.
- Raw data is immutable. Corrections create a new version or audit record.
- Algorithms, scores, features, prompts, schemas, datasets, and model configurations carry explicit versions.
- Never overwrite historical results with a new algorithm version.
- Every derived result must be traceable to source data, code/config version, and processing time.
- KOL public statements are `Claim` records, not broker-confirmed `Trade` records.
- Precious-metals support is limited to exchange-listed ETFs/funds classified with a precious-metals asset class and a `GOLD`, `SILVER`, or `OTHER` underlying commodity.
- NAV and iNAV are point-in-time research/reference fields, not assumed executable prices.
- Do not infer a precious-metals classification only from a product name; preserve source, effective dates, and confidence or review status.

## 14. API, jobs, and distributed processing

- API and event contracts are versioned and compatibility-checked.
- Use idempotency keys for retried commands and external side effects.
- Persist checkpoints for long-running ingestion and materialization jobs.
- Classify transient, rate-limit, validation, authorization, and permanent errors separately.
- Retries use bounded exponential backoff and must not duplicate committed work.
- Preserve rejected records with an error reason; do not silently drop malformed data.
- Use event time for market windows and define late-data behavior explicitly.
- Avoid high-cardinality Prometheus labels such as raw security symbols or account IDs.

## 15. Frontend and shadcn/ui

- Use **shadcn/ui** as the foundation for web UI primitives.
- Reuse or extend the existing primitives in `components/ui`; do not create a competing Button, Dialog, Form, Table, Toast, or navigation system.
- Keep base UI primitives, business components, and page containers separate.
- Preserve Radix/shadcn accessibility semantics when styling or composing components.
- Every page and data region must define loading, empty, error, and forbidden states.
- Support keyboard navigation, visible focus, dark mode, responsive layouts, and reduced-motion preferences.
- Dense market tables must remain readable and performant; use deliberate column widths and virtualization when evidence shows it is needed.
- Integrate TradingView Lightweight Charts through an internal adapter, not directly throughout page components.
- Display data timestamp, freshness, algorithm/model version, sample size, and confidence where relevant.
- Clearly distinguish facts, model inferences, low-confidence results, and KOL Claims in the UI.
- Keep creation forms out of the resting list view. The list owns browsing, filtering and management, with an explicit create button. Use a Dialog for short, simple forms and a drawer for longer or grouped forms; choose based on task complexity, rather than automatically creating a new page.
- Reuse the existing Dialog/Radix primitives for overlays and drawers. Keep headings, focus containment/return, keyboard dismissal, responsive scrolling and visible actions accessible. On successful save, close the overlay and update the list; on failure, keep the user's input and show an error. Do not turn a create form into a permanent side column or top section of a list.

## 16. Testing and verification

### Development checks

For features and defects, demonstrate the intended narrow failure, implement the smallest fix, and show the same behavior passing. Cover relevant normal, boundary, failure, recovery, and regression cases; do not add unrelated scenarios just to fill a checklist.

Choose checks before implementation and stop when direct evidence is sufficient:

| Change                                                                                                                                                    | Default verification budget                                                                                                                                            |
| --------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Documentation, copy, static assets, local styling                                                                                                         | Diff review plus 1–2 direct checks, such as formatting/links or the affected rendered view. No application tests, builds, or service startup solely for documentation. |
| Low-risk private logic                                                                                                                                    | Focused behavior/regression tests and only relevant static checks. No default whole-package or repository suite.                                                       |
| Shared logic, public API, multi-file business behavior, build configuration                                                                               | Focused tests, relevant format/lint/type checks, and at most one affected module/package check or build when needed.                                                   |
| Authentication/authorization, security, persistence/schema, money/data correctness, concurrency, dependencies, infrastructure/CI/CD, irreversible changes | Targeted tests plus one affected-surface validation and necessary integration evidence; one independent review of the final high-risk change.                          |

Use configured commands. Run the narrow behavior check first, then applicable format, lint, type, affected tests/build, and integration checks. Omit checks that cannot be affected by the change and state material unverified areas. `pnpm check` is the aggregate full-repository command, not the default for each task. Mandatory configured hooks, CI, and applicable node/phase gates still apply at their actual boundary; do not bypass them.

Reuse successful evidence while the relevant code, dependencies, inputs, tools, configuration, and environment remain unchanged. Documentation-only changes do not invalidate application tests or builds. Reviewers inspect the diff and existing output first, and re-run only missing, stale, conflicting, or scope-mismatched checks. Do not require a new hash manifest, packaging pass, or full test cycle merely to restate the same result.

Expand the budget only for a failed targeted check, evidence of wider impact, a changed public API/schema/lockfile/build/CI boundary, an applicable mandatory gate, or an explicit request for broader verification. Explain the trigger before expanding; do not repeat a failed attempt without new evidence.

Preserve the following domain checks when the affected behavior requires them:

- Freeze time and randomness in deterministic tests; use contract-compatible fakes instead of real external networks, accounts, or brokers in automated tests.
- Test point-in-time leakage for features/research/backtests and accounting invariants for cash, positions, fees, fills, and corporate actions.
- Test idempotency, duplicate/out-of-order delivery, restart, and reconciliation for affected jobs/orders.
- Do not change golden files or regression baselines solely to make a failure disappear; explain the intended semantic change.

### Release acceptance

Release acceptance is performed once for the frozen product scope at the end, separately from development checks:

1. Identify the actual source/build/configuration and remaining blockers. Reuse the verified final build if its inputs and target environment still match; otherwise build the affected release artifact once.
2. Walk one core user chain and the new capability being released. For 1.0.0: login → real daily data/date/source → edit/toggle a rule → receive/read an in-app reminder. Reuse valid persistence/restart evidence instead of repeating the whole flow for each documentation change.
3. Back up existing state before a risky database operation. A full backup-restore drill belongs to final release readiness, once for the relevant persistence setup; repeat only when a schema, backup/restore procedure, or storage/environment change invalidates it. It is not an early feature-development prerequisite.
4. Keep one concise release receipt with actual source/artifacts, verification results, data provenance/date, applicable migration/recovery evidence, and known limits. Reuse development output; do not produce parallel evidence packets, repeated archives, or per-file hash manifests by default.

Release blockers are broken core flows, incorrect or lost data, authentication/security failures, violated trading boundaries, and missing mandatory gates for capabilities included in that release. Cosmetic issues and deferred features go to the backlog. A constrained research release does not require completion of every P0–P6 node. Formal Phase 6 endurance/reconciliation and Phase 7 live-enablement gates remain mandatory when those capabilities or phase transitions are actually being accepted; this workflow does not waive them.

## 17. Documentation and operational readiness

Update documentation in the same node when behavior changes.

- Public contracts require examples and compatibility notes.
- Architectural choices require an ADR when they change a boundary or introduce a lasting constraint.
- Algorithms require inputs, formula/logic, missing-data behavior, version, and examples.
- Services require startup, health, shutdown, metrics, alerts, and failure-recovery documentation.
- Operationally significant alerts require a runbook.
- `.env.example` contains only non-secret, unusable example values.
- Do not include personal paths, credentials, account identifiers, cookies, tokens, or private raw data in docs or fixtures.

## 18. Git and commit discipline

Release planning uses complete `1.x.x` versions. Start at `1.0.0`, then `1.0.1`, `1.0.2`, etc. Under this project's product-release policy, patches include compatible small features and fixes; reserve `1.1.0` for a substantive milestone and major versions for material incompatibility. Do not bump the minor number every week or assign a major version automatically to QMT. API/schema compatibility remains separately versioned.

Each release delivers one usable module slice in 2–5 calendar days, with a hard planning limit of 7 calendar days from first work to delivery, including research, implementation, verification, and release preparation. By day 2, split any forecast overrun into smaller usable slices or defer an externally blocked item. Do not exclude preparation from the clock, publish an empty update, or weaken required safety/data gates to meet cadence. Keep only the current and next release detailed in the existing roadmap; record outcome, scope, dependencies, non-goals, acceptance, and time budget. Planned versions do not imply an actual package bump, tag, deployment, or release.

- Follow Conventional Commits with the exact title form `type(scope): 中文描述` or `type: 中文描述` when no scope is useful.
- Keep `type` and optional `scope` in lowercase English. Allowed types are `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, `style`, and `revert`.
- Write the subject and body primarily in Chinese. Keep product names, library names, protocols, commands, paths, identifiers, and other proper technical terms in their original English form.
- Do not mix an English prose subject with a Chinese prose subject across commits. Examples: `feat(web): 创建 React Web 基础骨架`, `fix(phase0): 修复工程基础设施验收阻断项`, `docs: 补充项目规划文档`.
- Use an imperative, concrete subject without a trailing period. Keep it concise and describe the resulting change rather than the work process.
- For development-node commits, put the node ID on the first line of the body, such as `Node: P0-N06`; add a short Chinese summary or verification note only when it materially helps review.
- Keep commits small, focused, reviewable, and reversible.
- Reference the development node ID in the commit body or task record; WorkBuddy must not invent, omit, or change the assigned node ID.
- Do not mix unrelated formatting, dependency upgrades, generated-file churn, or broad refactoring into a node.
- Review generated files before committing them.
- Do not bypass hooks or CI checks to make a node appear complete.
- Do not commit or push unless the user authorized it.

## 19. Security and privacy

- Secrets belong in approved secret storage, never in source control, examples, logs, screenshots, or test snapshots.
- Redact account identifiers, tokens, cookies, phone numbers, and sensitive raw content from logs.
- Apply least privilege to databases, object stores, queues, deployment identities, and broker access.
- Validate and sanitize every external input at the boundary.
- Treat LLM output as untrusted data: parse against a schema, retain evidence, record model/prompt version, and handle low confidence.
- Preserve content source, usage restrictions, deletion state, and evidence provenance.
- Run dependency, image, secret, and license checks when the relevant tooling exists.
- Do not download or execute unreviewed code to solve a routine task.

## 20. Real-trading safety rules

### Phase 0 through Phase 6

- Real-broker credentials, production QMT connections, and callable real-order paths are forbidden.
- Broker interfaces use fakes or simulation-only adapters.
- If real-trading code or credentials are discovered, stop work and report it immediately.
- A feature flag alone is not sufficient isolation.

### Phase 7

- Phase 7 still defaults to QMT simulation.
- Real-account work requires a separate explicit user authorization for the exact node and environment.
- Verify current broker requirements and applicable regulation from authoritative sources before live-enablement work.
- Separate simulation and live credentials, accounts, databases, deployments, networks, logs, and permissions.
- Strategies may only create `Signal` or `OrderIntent`.
- Order flow must pass portfolio construction, independent risk decisions, a persistent order state machine, and the broker adapter.
- Risk-engine failure must be fail-closed: reject new orders.
- Reconnect must reconcile account, positions, orders, and fills before order flow resumes.
- Retries must be idempotent and protected by `clientOrderId` or an equivalent key.
- A Kill Switch must work independently of the strategy service.
- Emergency liquidation requires a separate permission and explicit confirmation.
- Small-capital live pilot limits must not expand automatically.

## 21. Stop-and-ask conditions

Stop and request user direction before:

- expanding work beyond the current node;
- adding a materially new production dependency or managed service;
- changing an approved public contract incompatibly;
- performing a destructive database migration or material data deletion;
- altering the security, permission, secret, or network model;
- enabling any real-account or real-order capability;
- adding physical bullion, spot precious-metals contracts, commodity futures, margin, contract rollover, delivery, or warehouse-receipt behavior;
- using production data when sanitized fixtures are sufficient;
- choosing between interpretations that materially change behavior;
- proceeding when a required dependency node or external authorization is missing;
- continuing after repeated verification failure without a supported root cause.

Do not stop for harmless, reversible implementation details that are clearly inside the approved node. Make a reasonable choice, document it, and proceed.

## 22. Required evidence packet

An evidence packet is a concise result record, not a mandatory standalone document. Routine delivery normally fits in one paragraph or a few bullets:

- Outcome and changed files; node ID only when this is node implementation.
- Verification commands/scopes and actual results, including intended TDD failure where applicable; identify reused evidence instead of claiming it was re-run.
- Remaining blockers, material unverified areas, and relevant platform/security/data/trading implications. Include an artifact, screenshot, or migration output only when it helps assess the result.
- Actual commit/build identity when available; do not imply a commit, deployment, or release occurred without evidence.

High-risk work adds only the affected migration/recovery/concurrency evidence and independent review conclusion. A release has one receipt that links or summarizes existing results; do not create a second packet for the same checks. Never omit failed or unavailable required checks, invent output, or record deferred work as complete.

## 23. Definition of Done

A node is complete only when:

- the requested behavior and acceptance criteria are satisfied;
- no later-node scope was pulled in;
- applicable feature/defect tests were demonstrated failing first and passing afterward; documentation-only tasks use direct validation;
- checks selected under Section 16 and applicable mandatory gates pass, with actual output or valid reusable evidence;
- architecture and dependency boundaries remain valid;
- security, data, time, precision, version, and idempotency concerns are addressed;
- relevant Windows, macOS, and Linux implications were checked; native runtime claims require evidence, not a repeated three-platform run for every edit;
- documentation and runbooks were updated where required;
- the concise result record states actual results and material limitations;
- Codex has no unresolved blocking review finding.

## 24. Code Review Rules

Review findings take priority over summaries. Report actionable findings first, ordered by severity, with precise file and line references.

Always flag:

- any Phase 0–6 path that can reach a real broker;
- fail-open risk behavior or a risk-engine bypass;
- order retries without idempotency or illegal order-state transitions;
- recovery that resumes order flow before reconciliation;
- future-data leakage, survivor bias, or use of revised data before it was available;
- vendor-specific symbols outside adapters;
- money or accounting implemented with unsafe floating point;
- historical scores or features overwritten instead of versioned;
- KOL Claims represented as verified trades;
- precious-metals NAV/iNAV treated as executable prices, or spot/futures rules silently applied to exchange-listed funds;
- unvalidated LLM or external-provider output entering trusted storage;
- missing evidence provenance or audit fields;
- secrets, personal data, account identifiers, or production content in code, logs, fixtures, or screenshots;
- unbounded retries, silent data drops, and non-idempotent ingestion;
- breaking contract changes without versioning and migration;
- cross-platform failures, CRLF drift, and shell-specific scripts without alternatives;
- new UI primitives that duplicate shadcn/ui or regress accessibility;
- tests that assert implementation details while missing business invariants;
- completion claims unsupported by fresh verification output;
- unrelated refactors, dependency changes, or generated churn hidden in a node.

When a finding has a safe path, include it. Do not reduce review to formatting preferences already enforced by automated tooling.
