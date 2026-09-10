from __future__ import annotations

import hashlib
import os
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

import pytest
from ashare_contracts.calendar_holiday import Holiday, Reason
from data_worker.jobs.calendars import (
    CalendarOperationConflictError,
    CalendarPersistenceError,
    CalendarRepositoryTransactionError,
    CalendarScopeAmbiguityError,
    CalendarScopeError,
    PostgresCalendarRepository,
)
from data_worker.storage import (
    CALENDAR_SNAPSHOT_MIGRATION,
    apply_calendar_snapshot_migration,
    apply_data_worker_migrations,
)
from data_worker.storage import migrations as worker_migrations
from psycopg import errors as psycopg_errors
from psycopg.pq import TransactionStatus


def _holiday(value: str, *, exchange: str = "SH", note: str | None = None) -> Holiday:
    return Holiday.model_validate(
        {
            "date": value,
            "exchange": exchange,
            "reason": Reason.public_holiday.value,
            "note": note,
        }
    )


def _create_worker_base_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          max_attempts INTEGER NOT NULL,
          lease_token TEXT,
          lease_expires_at TIMESTAMPTZ,
          next_run_at TIMESTAMPTZ,
          last_error_category TEXT,
          last_error_detail JSONB,
          dead_letter_detail JSONB,
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE checkpoints (
          task_id TEXT PRIMARY KEY,
          cursor TEXT,
          state JSONB,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE quality_events (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          unified_code TEXT,
          date DATE,
          detail TEXT
        );
        """
    )


@pytest.fixture()
def postgres_repositories() -> Generator[tuple[Any, Any, str], None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn)
    except Exception:
        pytest.skip("PostgreSQL unavailable")

    schema = f"calendar_p1n07_{uuid4().hex}"
    first: Any = None
    second: Any = None
    try:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
        first = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with first.transaction(), first.cursor() as cursor:
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(first)
        second = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        yield PostgresCalendarRepository(first), PostgresCalendarRepository(second), schema
    finally:
        if second is not None:
            second.close()
        if first is not None:
            first.close()
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def _count(connection: Any, table: str) -> int:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return int(cursor.fetchone()[0])


def test_calendar_snapshot_migration_is_one_packaged_resource() -> None:
    resource = worker_migrations.load_calendar_snapshot_migration()
    assert resource
    assert CALENDAR_SNAPSHOT_MIGRATION.encode("utf-8") == resource
    assert hashlib.sha256(resource).hexdigest()


def test_postgres_repository_round_trips_order_duplicates_and_empty_scope(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    rows = [_holiday("2026-01-01", note="first"), _holiday("2026-01-01", note="second")]

    version_id = repository.save_version("calendar-source", 2026, rows, exchange="SH")
    empty_version = repository.save_version("calendar-source", 2026, [], exchange="SZ")

    assert UUID(version_id)
    assert UUID(empty_version)
    assert repository.get_version(version_id) == rows
    assert reopened.get_version(version_id) == rows
    assert repository.source_holidays("calendar-source", exchange="SZ", year=2026) == []
    assert repository.latest_version_id("calendar-source", "SZ", 2026) == empty_version
    with pytest.raises(CalendarScopeAmbiguityError):
        repository.source_holidays("calendar-source")


@pytest.mark.parametrize("malformed_field", ["reason", "note", "missing_reason", "missing_note"])
def test_postgres_rejects_malformed_fingerprint_fields_before_database_write(
    postgres_repositories: tuple[Any, Any, str], malformed_field: str
) -> None:
    repository, _reopened, _schema = postgres_repositories
    row = _holiday("2026-01-01")
    if malformed_field == "reason":
        object.__setattr__(row, "reason", "PUBLIC_HOLIDAY")
    elif malformed_field == "note":
        object.__setattr__(row, "note", object())
    elif malformed_field == "missing_reason":
        row = Holiday.model_construct(date="2026-01-01", exchange="SH")
    else:
        row = Holiday.model_construct(
            date="2026-01-01", exchange="SH", reason=Reason.public_holiday
        )
        object.__delattr__(row, "note")

    with pytest.raises(CalendarScopeError, match="calendar scope is invalid"):
        repository.save_version("calendar-source", 2026, [row], exchange="SH")

    for table in (
        "calendar_snapshot_versions",
        "calendar_snapshot_holidays",
        "calendar_snapshot_latest",
        "calendar_snapshot_corrections",
        "calendar_snapshot_audit",
    ):
        assert _count(repository._connection, table) == 0


def test_operation_id_is_opaque_idempotent_and_does_not_roll_latest_back(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, schema = postgres_repositories
    first_rows = [_holiday("2026-01-01")]
    second_rows = [_holiday("2026-02-17")]

    first = repository.save_version(
        "calendar-source", 2026, first_rows, exchange="SH", operation_id="operation-1"
    )
    assert (
        repository.save_version(
            "calendar-source", 2026, first_rows, exchange="SH", operation_id="operation-1"
        )
        == first
    )
    second = repository.save_version("calendar-source", 2026, second_rows, exchange="SH")
    assert repository.latest_version_id("calendar-source", "SH", 2026) == second

    assert (
        repository.save_version(
            "calendar-source", 2026, first_rows, exchange="SH", operation_id="operation-1"
        )
        == first
    )
    assert repository.latest_version_id("calendar-source", "SH", 2026) == second
    with pytest.raises(CalendarOperationConflictError):
        repository.save_version(
            "calendar-source", 2026, second_rows, exchange="SH", operation_id="operation-1"
        )
    with repository._connection.transaction(), repository._connection.cursor() as cursor:
        cursor.execute(
            f"SELECT operation_key_hash FROM {schema}.calendar_snapshot_versions "
            "WHERE version_id = %s",
            (UUID(first),),
        )
        stored_hash = cursor.fetchone()[0]
    assert bytes(stored_hash) == hashlib.sha256(b"operation-1").digest()


def test_concurrent_same_operation_id_creates_one_version(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    rows = [_holiday("2026-01-01")]

    def save(repository: PostgresCalendarRepository) -> str:
        return repository.save_version(
            "calendar-source", 2026, rows, exchange="SH", operation_id="concurrent"
        )

    repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository] = (
        repository,
        reopened,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        values: list[str] = list(executor.map(save, repositories))

    assert values[0] == values[1]
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_audit") == 1


def test_same_operation_id_across_scopes_is_a_conflict(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, reopened, _schema = postgres_repositories

    def save(repository: PostgresCalendarRepository, exchange: str) -> tuple[str, str]:
        try:
            return (
                "ok",
                repository.save_version(
                    "calendar-source", 2026, [], exchange=exchange, operation_id="cross-scope"
                ),
            )
        except CalendarOperationConflictError:
            return ("conflict", "")

    scope_arguments: tuple[tuple[PostgresCalendarRepository, str], ...] = (
        (repository, "SH"),
        (reopened, "SZ"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, *arguments) for arguments in scope_arguments]
        outcomes = [future.result() for future in futures]

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "ok"]
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_audit") == 1


def test_without_operation_id_same_payload_creates_new_versions(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    first = repository.save_version("calendar-source", 2026, [], exchange="SH")
    second = repository.save_version("calendar-source", 2026, [], exchange="SH")

    assert first != second
    assert repository.latest_version_id("calendar-source", "SH", 2026) == second
    assert _count(repository._connection, "calendar_snapshot_versions") == 2
    assert _count(repository._connection, "calendar_snapshot_audit") == 2


def test_exact_corrections_are_version_bound_and_implicit_is_ambiguous(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    first = repository.save_version("calendar-source", 2026, [], exchange="SH")
    second = repository.save_version("calendar-source", 2027, [], exchange="SH")
    before_audit = repository.audit_log()

    with pytest.raises(CalendarScopeAmbiguityError):
        repository.apply_correction("2026-01-01", "reason", "note", "author")
    assert repository.audit_log() == before_audit

    repository.apply_correction("2026-01-01", "reason", "note", "author", version_id=first)
    correction = repository.correction_overlay(first)[0]
    assert correction.date == "2026-01-01"
    assert correction.reason == "reason"
    assert correction.note == "note"
    assert correction.author == "author"
    assert correction.version_id == first
    assert repository.correction_overlay(second) == []
    with pytest.raises(KeyError, match="unknown calendar version"):
        repository.correction_overlay("not-a-uuid")


def test_repository_rejects_caller_transaction_without_touching_it(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    version_id = repository.save_version("calendar-source", 2026, [], exchange="SH")
    connection = repository._connection
    calls = [
        lambda: repository.initialize(),
        lambda: repository.save_version("calendar-source", 2026, [], exchange="SH"),
        lambda: repository.source_holidays("calendar-source", exchange="SH", year=2026),
        lambda: repository.latest_version_id("calendar-source", "SH", 2026),
        lambda: repository.get_version(version_id),
        lambda: repository.correction_overlay(version_id),
        lambda: repository.apply_correction(
            "2026-01-01", "reason", "note", "author", version_id=version_id
        ),
        lambda: repository.audit_log(),
    ]
    for call in calls:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            with pytest.raises(CalendarRepositoryTransactionError):
                call()
            cursor.execute("SELECT 2")
        assert connection.info.transaction_status == TransactionStatus.IDLE


def test_public_operations_leave_borrowed_connection_idle(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    version_id = repository.save_version("calendar-source", 2026, [], exchange="SH")
    operations = [
        lambda: repository.initialize(),
        lambda: repository.save_version("calendar-source", 2026, [], exchange="SH"),
        lambda: repository.source_holidays("calendar-source", exchange="SH", year=2026),
        lambda: repository.latest_version_id("calendar-source", "SH", 2026),
        lambda: repository.get_version(version_id),
        lambda: repository.correction_overlay(version_id),
        lambda: repository.apply_correction(
            "2026-01-01", "reason", "note", "author", version_id=version_id
        ),
        lambda: repository.audit_log(),
    ]

    for operation in operations:
        operation()
        assert repository._connection.info.transaction_status == TransactionStatus.IDLE


def test_initialize_wraps_unexpected_migration_failures(
    postgres_repositories: tuple[Any, Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, _reopened, _schema = postgres_repositories

    def fail(_connection: Any) -> None:
        raise RuntimeError("untrusted migration detail")

    monkeypatch.setattr(worker_migrations, "apply_data_worker_migrations", fail)
    with pytest.raises(CalendarPersistenceError, match="calendar persistence failed") as caught:
        repository.initialize()
    assert "untrusted migration detail" not in str(caught.value)
    assert repository._connection.info.transaction_status == TransactionStatus.IDLE


def test_database_failure_is_controlled_and_rolls_back(
    postgres_repositories: tuple[Any, Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, _reopened, _schema = postgres_repositories
    original = repository._save

    def save_then_fail(*args: Any, **kwargs: Any) -> str:
        original(*args, **kwargs)
        raise RuntimeError("untrusted database detail")

    monkeypatch.setattr(repository, "_save", save_then_fail)
    with pytest.raises(CalendarPersistenceError, match="calendar persistence failed"):
        repository.save_version("calendar-source", 2026, [], exchange="SH")
    assert _count(repository._connection, "calendar_snapshot_versions") == 0
    assert _count(repository._connection, "calendar_snapshot_holidays") == 0
    assert _count(repository._connection, "calendar_snapshot_latest") == 0
    assert _count(repository._connection, "calendar_snapshot_audit") == 0


def test_historical_tables_reject_update_and_delete(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    version_id = repository.save_version(
        "calendar-source", 2026, [_holiday("2026-01-01")], exchange="SH"
    )
    repository.apply_correction("2026-01-02", "reason", "note", "author", version_id=version_id)
    with repository._connection.transaction(), repository._connection.cursor() as cursor:
        cursor.execute(
            "SELECT correction_id FROM calendar_snapshot_corrections WHERE version_id = %s",
            (UUID(version_id),),
        )
        correction_id = cursor.fetchone()[0]
        cursor.execute(
            "SELECT audit_id FROM calendar_snapshot_audit WHERE version_id = %s LIMIT 1",
            (UUID(version_id),),
        )
        audit_id = cursor.fetchone()[0]

    operations = [
        (
            "UPDATE calendar_snapshot_versions SET source = %s WHERE version_id = %s",
            ("other", UUID(version_id)),
        ),
        (
            "DELETE FROM calendar_snapshot_versions WHERE version_id = %s",
            (UUID(version_id),),
        ),
        (
            "UPDATE calendar_snapshot_holidays SET note = %s WHERE version_id = %s",
            ("other", UUID(version_id)),
        ),
        (
            "DELETE FROM calendar_snapshot_holidays WHERE version_id = %s AND ordinal = %s",
            (UUID(version_id), 0),
        ),
        (
            "UPDATE calendar_snapshot_corrections SET reason = %s WHERE correction_id = %s",
            ("other", correction_id),
        ),
        (
            "DELETE FROM calendar_snapshot_corrections WHERE correction_id = %s",
            (correction_id,),
        ),
        (
            "UPDATE calendar_snapshot_audit SET entry = %s WHERE audit_id = %s",
            ("other", audit_id),
        ),
        (
            "DELETE FROM calendar_snapshot_audit WHERE audit_id = %s",
            (audit_id,),
        ),
    ]
    for query, params in operations:
        with (
            pytest.raises(psycopg_errors.RaiseException),
            repository._connection.transaction(),
            repository._connection.cursor() as cursor,
        ):
            cursor.execute(query, params)

    assert repository.latest_version_id("calendar-source", "SH", 2026) == version_id


def test_correction_boundaries_distinguish_empty_and_missing_scopes(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    assert repository.correction_overlay() == []
    assert repository.source_holidays("missing-source", exchange="SH", year=1) == []
    assert repository.latest_version_id("missing-source", "SH", 1) is None
    with pytest.raises(CalendarScopeError):
        repository.apply_correction("0001-01-01", "reason", "note", "author")

    first = repository.save_version("calendar-source", 1, [], exchange="SH")
    last = repository.save_version("calendar-source", 9999, [], exchange="SZ")
    assert repository.source_holidays("calendar-source", exchange="SH", year=1) == []
    assert repository.latest_version_id("calendar-source", "SH", 1) == first
    assert repository.correction_overlay(first) == []

    repository.apply_correction("0001-01-01", "first", "note", "author", version_id=first)
    repository.apply_correction("9999-12-31", "last", "note", "author", version_id=last)
    before_audit = repository.audit_log()
    with pytest.raises(CalendarScopeError):
        repository.apply_correction("0002-01-01", "bad", "note", "author", version_id=first)
    with pytest.raises(CalendarScopeError):
        repository.apply_correction("0000-12-31", "bad", "note", "author", version_id=first)
    with pytest.raises(CalendarScopeError):
        repository.apply_correction("10000-01-01", "bad", "note", "author", version_id=last)
    assert repository.audit_log() == before_audit


def test_existing_v3_schema_is_verified_for_drift(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    with repository._connection.transaction(), repository._connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE calendar_snapshot_versions "
            "DROP CONSTRAINT calendar_snapshot_versions_year_ck"
        )
    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(repository._connection)


@pytest.mark.parametrize(
    "weakening", ["foreign_key", "foreign_key_action", "check", "unique", "default"]
)
def test_v3_schema_verifier_rejects_same_name_or_default_drift_and_preserves_ledger(
    postgres_repositories: tuple[Any, Any, str], weakening: str
) -> None:
    repository, _reopened, _schema = postgres_repositories
    connection = repository._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations ORDER BY version"
        )
        before_ledger = cursor.fetchall()
        if weakening == "foreign_key":
            cursor.execute(
                "ALTER TABLE calendar_snapshot_holidays "
                "DROP CONSTRAINT calendar_snapshot_holidays_version_scope_fkey"
            )
            cursor.execute(
                "ALTER TABLE calendar_snapshot_holidays "
                "ADD CONSTRAINT calendar_snapshot_holidays_version_scope_fkey "
                "FOREIGN KEY (version_id) REFERENCES calendar_snapshot_versions(version_id)"
            )
        elif weakening == "foreign_key_action":
            cursor.execute(
                "ALTER TABLE calendar_snapshot_holidays "
                "DROP CONSTRAINT calendar_snapshot_holidays_version_scope_fkey"
            )
            cursor.execute(
                "ALTER TABLE calendar_snapshot_holidays "
                "ADD CONSTRAINT calendar_snapshot_holidays_version_scope_fkey "
                "FOREIGN KEY (version_id, source, exchange, year) "
                "REFERENCES calendar_snapshot_versions(version_id, source, exchange, year) "
                "ON UPDATE RESTRICT ON DELETE CASCADE"
            )
        elif weakening == "check":
            cursor.execute(
                "ALTER TABLE calendar_snapshot_versions "
                "DROP CONSTRAINT calendar_snapshot_versions_year_ck"
            )
            cursor.execute(
                "ALTER TABLE calendar_snapshot_versions "
                "ADD CONSTRAINT calendar_snapshot_versions_year_ck CHECK (year >= 1)"
            )
        elif weakening == "unique":
            cursor.execute(
                "ALTER TABLE calendar_snapshot_versions "
                "DROP CONSTRAINT calendar_snapshot_versions_operation_key_uk"
            )
            cursor.execute(
                "ALTER TABLE calendar_snapshot_versions "
                "ADD CONSTRAINT calendar_snapshot_versions_operation_key_uk UNIQUE (source)"
            )
        else:
            cursor.execute(
                "ALTER TABLE calendar_snapshot_versions "
                "ALTER COLUMN persisted_at SET DEFAULT "
                "(CURRENT_TIMESTAMP + interval '1 second')"
            )

    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations ORDER BY version"
        )
        assert cursor.fetchall() == before_ledger


def test_v3_schema_verifier_rejects_disabled_same_name_trigger(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    connection = repository._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE calendar_snapshot_versions "
            "DISABLE TRIGGER calendar_snapshot_versions_immutable"
        )

    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(connection)


def test_v3_schema_verifier_rejects_same_name_trigger_with_wrong_event(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    connection = repository._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER calendar_snapshot_versions_immutable ON calendar_snapshot_versions"
        )
        cursor.execute(
            "CREATE TRIGGER calendar_snapshot_versions_immutable "
            "BEFORE UPDATE ON calendar_snapshot_versions FOR EACH ROW "
            "EXECUTE FUNCTION calendar_snapshot_history_immutable()"
        )

    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(connection)


def test_v3_schema_verifier_rejects_same_name_trigger_with_wrong_function(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    connection = repository._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE FUNCTION calendar_snapshot_wrong_trigger() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"
        )
        cursor.execute(
            "DROP TRIGGER calendar_snapshot_versions_immutable ON calendar_snapshot_versions"
        )
        cursor.execute(
            "CREATE TRIGGER calendar_snapshot_versions_immutable "
            "BEFORE UPDATE OR DELETE ON calendar_snapshot_versions FOR EACH ROW "
            "EXECUTE FUNCTION calendar_snapshot_wrong_trigger()"
        )

    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(connection)


def test_v3_schema_verifier_rejects_same_name_noop_immutable_function(
    postgres_repositories: tuple[Any, Any, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    connection = repository._connection
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE OR REPLACE FUNCTION calendar_snapshot_history_immutable() "
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$"
        )

    with pytest.raises(ValueError, match="calendar snapshot schema drift"):
        apply_calendar_snapshot_migration(connection)


def test_postgres_calendar_repository_is_publicly_exposed() -> None:
    from data_worker.jobs.calendars import PostgresCalendarRepository

    assert PostgresCalendarRepository.__name__ == "PostgresCalendarRepository"
