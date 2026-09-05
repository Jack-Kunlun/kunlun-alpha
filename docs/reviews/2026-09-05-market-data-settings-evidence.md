# P1-N04 provider configuration evidence

## Scope

This record covers the approved P1-N04 provider-configuration extension: instance-level AKShare/Tushare
settings, administrator UI, encrypted storage, and the dedicated worker read route/runtime refresh.
It does not close other P0–P6 gaps or change the conditional P6 endurance acceptance. No commit,
deployment, running migration, restart, or new endurance run was authorized or performed here.

## Changed areas

- Contracts: `packages/contracts/schemas/market-data/settings.json`, its schema test, generated
  `packages/shared-types/src/index.ts`, and generated `ashare_contracts/market_data_settings.py` exports.
- Server: new `apps/server/src/modules/market-data-settings/`, narrow auth configuration/guard/decorator
  changes and tests, migration 011/index, `migrate.ts`/test, and `app.module.ts` registration.
- Web: new `apps/web/src/features/market-data-settings/`, route contract/elements/tests, and the existing
  `Layout.tsx` navigation icon map. No replacement UI primitive or dependency was added.
- Worker: `services/data-worker/src/data_worker/jobs/market_data/remote_settings.py`, `runtime.py`,
  and `services/data-worker/tests/test_market_data_remote_settings.py`.
- Operations: `infra/docker/.env.example`, `docker-compose.apps.yml`,
  `docs/adr/0011-instance-market-data-settings-secret-boundary.md`,
  `docs/runbooks/market-data-source.md`, and this evidence record.
- No files were deleted. Pre-existing P6/handbook/README changes were preserved, not included in this
  implementation's scope. No broker adapter or real-order capability was added.

## Implemented evidence

- `packages/contracts/schemas/market-data/settings.json` is the source schema; generated TypeScript
  and Python outputs are checked with the contract generator.
- Migration `011-market-data-settings` separates the encrypted singleton row from a secret-free audit
  table. The repository uses a transaction, advisory lock, revision CAS, parameterized SQL, and
  rollback on audit failure.
- AES-256-GCM uses a randomized 96-bit nonce, explicit envelope/key versions, instance-bound AAD,
  strict base64/length validation, and no fallback key.
- Browser GET/POST routes return only the safe response fields. The worker route returns only the
  effective provider/revision/token shape and is guarded by the dedicated internal credential.
- The in-process HTTP boundary test exercises Nest controller registration, the global guard, DI,
  browser session/CSRF checks, internal Bearer isolation, `Cache-Control: no-store`, and generic
  unconfigured 503 responses using fake repository/key providers; it does not bind a listening port.
- Settings PostgreSQL pools use bounded connection, statement, lock, and idle-transaction timeouts;
  idle pool errors are handled with a generic message that excludes driver details; the settings-only
  migration flag selects migration 011 rather than applying unrelated app tables.
- Worker checkpoints are isolated by provider/revision without moving raw archives. A shared OS lock
  serializes the monotonic revision marker; atomic replacement is followed by POSIX directory fsync
  with generic failure propagation. The marker uses HMAC-SHA256 keyed by the separate worker credential,
  not an unkeyed token hash or plaintext secret. No extra persisted key was introduced.
- The administrator form preserves an edited draft's original revision until explicit refresh/cancel;
  refreshing clears the token draft and loads the latest provider, preventing silent revision rebases.

## Checks run

### Fail-first and limitations of test evidence

- The web feature/route checks initially failed for missing implementation; the later refresh regression
  failed two added tests before the draft synchronization repair.
- The worker remote-settings test initially failed collection for the absent module. Three later
  regressions demonstrated concurrent marker downgrade, missing shared-lock rejection, and missing
  parent-directory fsync; a separate EIO regression demonstrated a swallowed durability error.
  The final fingerprint regression failed on the old plain-SHA implementation before HMAC replacement.
- Backend initial typechecking failed before shared-type generation/build. This is integration failure
  evidence, not a claim that every backend behavior had a demonstrated failing test first.
- Initial plain `uv run --no-sync pytest services/data-worker/tests/test_market_data_runtime.py -q`
  was blocked by the sandbox's home-cache permissions. The same baseline using `uv --no-cache` passed
  16 tests; subsequent focused tests disable unrelated coverage collection with `--no-cov`.
- A TCP-based HTTP test encountered sandbox `EPERM`; the replacement exercises the real Nest request
  pipeline in-process without binding a port. It is not a deployed-network end-to-end test.

### Root final bounded checks

- `pnpm --filter @kunlun/server exec vitest run src/modules/market-data-settings src/modules/auth/auth.guard.test.ts src/modules/auth/auth-security.test.ts src/migrations/011-market-data-settings.test.ts src/migrate.test.ts`
  — 9 files, 38 tests passed. The generic storage-error line is expected fault-injection output.
- `pnpm --filter @kunlun/server typecheck` and `pnpm --filter @kunlun/server build` — passed.
- `pnpm --filter @kunlun/web exec vitest run src/features/market-data-settings src/app/route-contract.test.ts src/app/route-elements.test.tsx`
  — 5 files, 33 tests passed after the refresh correction.
- `pnpm --filter @kunlun/web build` — passed after the refresh correction.
- `uv --no-cache run --no-sync pytest --no-cov services/data-worker/tests/test_market_data_remote_settings.py services/data-worker/tests/test_market_data_runtime.py -q`
  — 45 tests passed after the shared-lock, directory-fsync, and HMAC repairs.
- `pnpm --filter @kunlun/contracts gen:check` — TypeScript and Python generated outputs in sync.
- `pnpm exec prettier --check docs/runbooks/market-data-source.md docs/reviews/2026-09-05-market-data-settings-evidence.md docs/adr/0011-instance-market-data-settings-secret-boundary.md`
  — passed.
- `git diff --check` — passed.

### Additional execution-agent checks

- `pnpm --filter @kunlun/contracts test -- src/market-data/settings-schema.test.ts` — passed.
- `pnpm --filter @kunlun/contracts gen:check` — passed for TypeScript and Python generated outputs.
- `pnpm --filter @kunlun/server lint` — passed.
- `pnpm --filter @kunlun/server typecheck` — passed after rebuilding shared types.
- `pnpm exec vitest run src/modules/market-data-settings src/modules/auth/auth.guard.test.ts
src/modules/auth/auth-security.test.ts src/migrations/011-market-data-settings.test.ts src/migrate.test.ts`
  from `apps/server` — 9 files/38 tests passed.
- UI typechecking, lint, scoped formatting, and 16 route accessibility checks passed. These are bounded
  checks, not a repository-wide suite or interactive browser verification claim.
- `uv --no-cache run --no-sync pytest --no-cov services/data-worker/tests/test_market_data_*.py -q`
  — worker owner reported 81 market-data tests passed after the HMAC correction.
- `uv --no-cache run --no-sync ruff check services/data-worker/src/data_worker/jobs/market_data/remote_settings.py services/data-worker/src/data_worker/jobs/market_data/runtime.py services/data-worker/tests/test_market_data_remote_settings.py services/data-worker/tests/test_market_data_runtime.py`
  — passed; the same paths passed `ruff format --check`.
- `uv --no-cache run --no-sync basedpyright services/data-worker/src/data_worker/jobs/market_data/remote_settings.py services/data-worker/src/data_worker/jobs/market_data/runtime.py services/data-worker/tests/test_market_data_remote_settings.py`
  — zero errors, warnings, or notes.
- `pnpm exec vitest run src/modules/market-data-settings/market-data-settings.http.integration.test.ts
src/modules/market-data-settings/market-data-settings.module.test.ts` from `apps/server` — 2 files/5
  tests passed without a database or external HTTP call (included in the 9-file result above).

## Independent audit outcome

The independent Terra Max review found and then verified repairs for shared-marker concurrency and
directory durability, the settings pool's unhandled idle error, and the unkeyed token fingerprint.
It also verified the settings-only migration selection and inspected the admin/auth/crypto/internal
worker secret boundaries. Its final narrow HMAC confirmation reported no remaining blocking code
finding. This approval covers the reviewed undeployed implementation, not a live-provider, real-DB,
cross-platform, or endurance qualification.

## Limitations

No running PostgreSQL migration, external provider request, production secret, deployment, restart, or
live HTTP worker integration was used. Python runtime and web UI changes are owned and validated by their
respective agents; runtime release acceptance still requires provisioned integration environment checks.
No Windows or Linux host was used for this macOS execution; cross-platform paths/locking were reviewed,
but platform-specific runtime behavior remains unverified here. Generated `ashare-contracts` DTO exports were updated for
the new contract; no backtest regression baseline was regenerated or approved to mask that provenance
change.
