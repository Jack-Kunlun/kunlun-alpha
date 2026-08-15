# PostgreSQL migration and scheduler development

P1-R05 stores control-plane task state in PostgreSQL. The scheduler uses
database `CURRENT_TIMESTAMP` for lease expiry and an opaque `lease_token` for
every owner-guarded transition. A process restart can therefore recover a
checkpoint or take over an expired lease without trusting a process-local
monotonic clock.

## Local setup

Start only the existing PostgreSQL Compose service:

```powershell
docker compose -f infra/docker/docker-compose.yml --env-file infra/docker/.env up -d postgres
```

The checked-in `.env.example` values are local development examples only.
Never put a real credential in source control or test output.

## Explicit migrations

Migrations are not run on API import or application boot. Invoke the migration
runner from an explicit maintenance command with a configured
`KUNLUN_POSTGRES_DSN`, and use the same command with a target version to roll
back. Each migration's DDL and `schema_migrations` metadata change are one
transaction; a failed transaction rolls back both. A successful rollback
deletes its metadata record so a later migrate can apply it again.

## PostgreSQL integration tests

Set `KUNLUN_TEST_POSTGRES_DSN` to a local, disposable database and run:

```powershell
$env:KUNLUN_TEST_POSTGRES_DSN = "postgresql://kunlun:kunlun-local-dev@localhost:5432/kunlun"
\.venv\Scripts\python.exe -m pytest services/data-worker/tests/test_postgres_store.py -q --no-cov
pnpm.cmd --filter @kunlun/db test -- src/postgres-driver.integration.test.ts
pnpm.cmd --filter @kunlun/api test -- src/migrations/001-initial.integration.test.ts
```

Each TypeScript integration suite and the Python fixture creates a unique
schema per test and drops only that schema. They never remove Compose volumes.
Without the opt-in DSN the tests are skipped; unit tests continue to use the
contract-compatible `InMemoryTaskStore` and `MemorySqlDriver`.

The PostgreSQL adapter is synchronous by design. Checkpoint and error payloads
must be bounded JSON-compatible values; sensitive keys such as passwords,
secrets, credentials, or API keys are rejected before persistence.

## Retry budgets

The scheduler has two deliberately separate bounded retry budgets:

- the store's `max_attempts` is the durable lease-acquisition budget persisted
  with the task and enforced across process restarts;
- `TaskScheduler.run(max_inline_attempts=...)` is the process-local transient
  retry budget inside one acquired lease.

Both values must be positive. The total number of job function invocations is
therefore bounded by their product. Keep the inline value small so a worker
does not hold a lease through excessive retries; a crashed final persisted
attempt is atomically dead-lettered after its lease expires.

Migration locking uses a stable PostgreSQL advisory lock and passes a
lock-scoped driver into the callback. The callback and each transaction reuse
the same checked-out client, so a pool configured with `max=1` does not
deadlock. A failed rollback or unlock destroys the client via
`PoolClient.release(error)` rather than returning it to the healthy pool.

Lease acquisition is also the persisted retry-limit gate. If a restarted or
crashed task is already at `max_attempts` and its lease is unowned/expired, the
single CAS statement clears the lease and `next_run_at`, writes a bounded
`retry limit reached` dead-letter detail, and returns `DEAD` to the scheduler.
Stored `error_category` values are limited to the controlled scheduler/provider
taxonomy (`transient`, `permanent`, `timeout`, `rate_limit`, `auth`,
`authorization`, `not_found`, `data_error`, `validation`, `unavailable`,
`conflict`, or `internal`).
