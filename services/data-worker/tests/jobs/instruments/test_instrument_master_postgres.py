"""Opt-in PostgreSQL integration coverage for the P1-N06 V5 boundary.

The suite is intentionally skipped unless ``KUNLUN_TEST_POSTGRES_DSN`` is
provided.  Every test creates a private schema and drops it after the test;
the target/default schema is never used by this module.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from data_worker.jobs.instruments.postgres_repository import (
    InstrumentMasterPersistenceError,
    InstrumentMasterRepositoryTransactionError,
    PostgresInstrumentMasterRepository,
)
from data_worker.jobs.instruments.tushare_master import (
    TUSHARE_COLLECTION_PARTITIONS,
    TUSHARE_FUND_BASIC_FIELDS,
    TUSHARE_INSTRUMENT_SOURCE,
    TUSHARE_STOCK_BASIC_FIELDS,
    TushareInstrumentCollector,
    TushareInstrumentConfig,
    TushareInstrumentResponse,
)
from data_worker.raw.storage import LocalFileStorage
from data_worker.storage import apply_data_worker_migrations
from data_worker.storage import migrations as worker_migrations
from data_worker.storage.migrations import (
    InstrumentMasterProviderRoles,
    apply_instrument_master_provider_migration,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus

_OBSERVED = datetime(2026, 9, 8, 1, 0, tzinfo=UTC)
ProviderContext = tuple[Any, str, Any, InstrumentMasterProviderRoles]


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _login_dsn(base_dsn: str, role: str) -> str:
    return make_conninfo(
        base_dsn,
        user=role,
        password=f"instrument-master-test-password-{role}",
    )


def _envelope(fields: Sequence[str], values: dict[str, object] | None = None) -> bytes:
    row = [] if values is None else [values.get(field, "") for field in fields]
    return json.dumps(
        {
            "code": 0,
            "msg": "",
            "data": {"fields": list(fields), "items": [] if values is None else [row]},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _stock(code: str = "600000", name: str = "示例证券") -> bytes:
    return _envelope(
        TUSHARE_STOCK_BASIC_FIELDS,
        {
            "ts_code": f"{code}.SH",
            "symbol": code,
            "name": name,
            "market": "主板",
            "exchange": "SSE",
            "list_status": "L",
            "list_date": "20200101",
            "delist_date": "",
        },
    )


def _empty(fields: Sequence[str]) -> bytes:
    return _envelope(fields)


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
        CREATE TABLE instrument_master_revisions (
          revision_id UUID PRIMARY KEY,
          instrument_id TEXT NOT NULL,
          marker TEXT NOT NULL
        );
        CREATE INDEX instrument_master_revisions_legacy_marker_idx
          ON instrument_master_revisions (marker);
        INSERT INTO instrument_master_revisions
          (revision_id, instrument_id, marker)
        VALUES ('00000000-0000-4000-8000-000000000001', 'legacy', 'untouched');
        """
    )


def _cleanup_instrument_master_fixture(
    admin: Any,
    schemas: tuple[str, ...],
    roles: tuple[str, ...],
) -> None:
    """Drop only fixture objects, one transaction per dependency-sensitive step."""

    errors: list[BaseException] = []

    def run(statement: str) -> None:
        try:
            admin.rollback()
            with admin.transaction(), admin.cursor() as cursor:
                cursor.execute(statement)
        except BaseException as exc:
            errors.append(exc)

    def role_exists(role: str) -> bool:
        try:
            admin.rollback()
            with admin.transaction(), admin.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
                    (role,),
                )
                return cursor.fetchone() is not None
        except BaseException as exc:
            errors.append(exc)
            return False

    for schema in schemas:
        run(f"DROP SCHEMA IF EXISTS {_identifier(schema)} CASCADE")
    for role in roles:
        identifier = _identifier(role)
        if role_exists(role):
            run(f"DROP OWNED BY {identifier}")
            run(f"DROP ROLE IF EXISTS {identifier}")

    try:
        admin.rollback()
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(
                "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname = ANY(%s)",
                (list(schemas),),
            )
            remaining_schemas = cursor.fetchall()
            cursor.execute(
                "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                (list(roles),),
            )
            remaining_roles = cursor.fetchall()
            if remaining_schemas or remaining_roles:
                raise RuntimeError("instrument master fixture cleanup left catalog objects")
    except BaseException as exc:
        errors.append(exc)

    try:
        admin.close()
    except BaseException as exc:
        errors.append(exc)
    if errors:
        raise errors[0]


@pytest.fixture()
def instrument_master_pg() -> Generator[ProviderContext, None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    # A configured integration DSN is an explicit request to exercise the
    # real database boundary.  Only an absent DSN may skip; connection or
    # dependency failures must fail the test rather than hide an outage.
    psycopg_api: Any = psycopg
    admin = psycopg_api.connect(dsn)

    legacy_schema = f"instrument_master_legacy_{uuid4().hex}"
    provider_schema = f"instrument_master_provider_{uuid4().hex}"
    roles = InstrumentMasterProviderRoles(
        owner=f"instrument_master_owner_{uuid4().hex}",
        migrator=f"instrument_master_migrator_{uuid4().hex}",
        runtime=f"instrument_master_runtime_{uuid4().hex}",
        reader=f"instrument_master_reader_{uuid4().hex}",
    )
    connection: Any = None
    setup_connection: Any = None
    migrator_connection: Any = None
    try:
        role_identifiers = {
            field: f'"{getattr(roles, field)}"'
            for field in ("owner", "migrator", "runtime", "reader")
        }
        with admin.transaction(), admin.cursor() as raw_cursor:
            raw_cursor.execute(f"CREATE ROLE {role_identifiers['owner']} NOLOGIN NOINHERIT")
            raw_cursor.execute(f"CREATE ROLE {role_identifiers['migrator']} LOGIN NOINHERIT")
            raw_cursor.execute(f"CREATE ROLE {role_identifiers['runtime']} LOGIN NOINHERIT")
            raw_cursor.execute(f"CREATE ROLE {role_identifiers['reader']} NOLOGIN NOINHERIT")
            for role in (roles.migrator, roles.runtime):
                raw_cursor.execute(
                    sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                        sql.Identifier(role),
                        sql.Literal(f"instrument-master-test-password-{role}"),
                    )
                )
            raw_cursor.execute(
                f"GRANT {role_identifiers['owner']} TO {role_identifiers['migrator']} "
                "WITH INHERIT FALSE, SET TRUE, ADMIN FALSE"
            )
            raw_cursor.execute(f'CREATE SCHEMA "{legacy_schema}"')
            raw_cursor.execute(
                f'CREATE SCHEMA "{provider_schema}" AUTHORIZATION {role_identifiers["owner"]}'
            )
        setup_connection = psycopg_api.connect(dsn, options=f'-c search_path="{legacy_schema}"')
        with setup_connection.transaction(), setup_connection.cursor() as cursor:
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(setup_connection)
        with admin.transaction(), admin.cursor() as raw_cursor:
            raw_cursor.execute(
                f'GRANT USAGE ON SCHEMA "{legacy_schema}" TO {role_identifiers["migrator"]}'
            )
            raw_cursor.execute(
                f'GRANT SELECT ON TABLE "{legacy_schema}".data_worker_schema_migrations '
                f"TO {role_identifiers['migrator']}"
            )
        setup_connection.close()
        setup_connection = None
        migrator_connection = psycopg_api.connect(
            _login_dsn(dsn, roles.migrator),
            options=f'-c search_path="{legacy_schema}"',
        )
        apply_instrument_master_provider_migration(
            migrator_connection,
            schema=provider_schema,
            roles=roles,
            legacy_schema=legacy_schema,
        )
        migrator_connection.close()
        migrator_connection = None
        connection = psycopg_api.connect(
            _login_dsn(dsn, roles.runtime),
            options=f"-c search_path={provider_schema},pg_catalog",
        )
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path = "{provider_schema}", "{legacy_schema}", pg_catalog')
        connection.commit()
        yield connection, provider_schema, psycopg_api, roles
    finally:
        cleanup_errors: list[BaseException] = []
        if connection is not None:
            try:
                connection.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        for candidate in (migrator_connection, setup_connection):
            if candidate is not None:
                try:
                    candidate.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        try:
            _cleanup_instrument_master_fixture(
                admin,
                (provider_schema, legacy_schema),
                tuple(
                    getattr(roles, field) for field in ("runtime", "reader", "migrator", "owner")
                ),
            )
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            raise cleanup_errors[0]


def _new_connection(context: ProviderContext) -> Any:
    connection, provider_schema, psycopg, roles = context
    del connection
    dsn = os.environ["KUNLUN_TEST_POSTGRES_DSN"]
    connection = psycopg.connect(
        _login_dsn(dsn, roles.runtime),
        options=f"-c search_path={provider_schema}",
    )
    with connection.cursor() as cursor:
        cursor.execute(f'SET search_path = "{provider_schema}", pg_catalog')
    connection.commit()
    return connection


def _repository(context: ProviderContext) -> PostgresInstrumentMasterRepository:
    connection, provider_schema, _psycopg, roles = context
    return PostgresInstrumentMasterRepository(
        connection,
        schema=provider_schema,
        runtime_role=roles.runtime,
        provider_roles=roles,
    )


def _collect(
    tmp_path: Path,
    run_id: str,
    *,
    stock_body: bytes | None = None,
    observed_at: datetime = _OBSERVED,
) -> tuple[Any, LocalFileStorage]:
    responses = [
        TushareInstrumentResponse(200, stock_body or _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_STOCK_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
        TushareInstrumentResponse(200, _empty(TUSHARE_FUND_BASIC_FIELDS)),
    ]
    storage = LocalFileStorage(tmp_path / run_id)

    def transport(
        url: str, headers: Mapping[str, str], body: bytes, timeout_seconds: float
    ) -> TushareInstrumentResponse:
        assert url == "https://api.tushare.pro"
        assert headers == {"Content-Type": "application/json; charset=utf-8"}
        assert timeout_seconds > 0
        assert b"token" in body
        return responses.pop(0)

    result = TushareInstrumentCollector(
        TushareInstrumentConfig(
            token="integration-test-token",
            max_attempts=1,
        ),
        storage,
        transport=transport,
        clock=lambda: observed_at,
        sleeper=lambda _: None,
    ).collect(run_id, "2026-09-08")
    assert result.terminal.value == "COMPLETE"
    assert result.completeness.value == "COMPLETE"
    assert len(result.page_refs) == len(TUSHARE_COLLECTION_PARTITIONS)
    return result, storage


def _count(connection: Any, table: str) -> int:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return int(cursor.fetchone()[0])


def test_private_provider_migration_is_verified_without_shared_v5(
    instrument_master_pg: ProviderContext,
) -> None:
    connection, provider_schema, _psycopg, roles = instrument_master_pg
    worker_migrations.verify_instrument_master_provider_schema(
        connection, schema=provider_schema, roles=roles
    )


def test_repository_persists_replayed_raw_graph_and_is_idempotent(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    result, storage = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000101",
        stock_body=_stock(),
    )
    repository = _repository(instrument_master_pg)

    first = repository.persist_authoritative_instrument_master_run(
        storage, result.run_id, result.manifest_date, result.manifest_capture_id
    )
    second = repository.persist_authoritative_instrument_master_run(
        storage, result.run_id, result.manifest_date, result.manifest_capture_id
    )

    assert first.disposition == "SNAPSHOT_CANDIDATE"
    assert first.run_disposition == "CONFIRMED"
    assert second.disposition == "DUPLICATE"
    assert _count(connection, "tushare_instrument_master_runs") == 1
    assert _count(connection, "tushare_instrument_master_raw_refs") == len(result.page_refs)
    assert _count(connection, "tushare_instrument_master_snapshots") == 1
    assert _count(connection, "tushare_instrument_master_revisions") == 1
    assert _count(connection, "tushare_instrument_master_heads") == 1
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT capture_id, object_id, request_identity, observed_at, available_at, "
            "content_type FROM tushare_instrument_master_raw_refs ORDER BY ordinal"
        )
        assert cursor.fetchall() == [
            (
                page.capture_id,
                page.object_id,
                page.request,
                page.observed_at,
                page.available_at,
                page.content_type,
            )
            for page in result.page_refs
        ]


class _IdentityCursor:
    def __init__(self, identity: tuple[str, str]) -> None:
        self.identity = identity
        self.calls: list[str] = []
        self._row: tuple[str, str] | None = None

    def __enter__(self) -> _IdentityCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, _params: Sequence[object] | None = None) -> None:
        self.calls.append(statement)
        self._row = self.identity if statement == "SELECT SESSION_USER, CURRENT_USER" else None

    def fetchone(self) -> tuple[str, str] | None:
        return self._row


class _IdentityTransaction:
    def __init__(self, connection: _IdentityConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _IdentityTransaction:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _IdentityConnection:
    def __init__(self, identities: Sequence[tuple[str, str]]) -> None:
        self.info = type("Info", (), {"transaction_status": TransactionStatus.IDLE})()
        self._identities = iter(identities)
        self.cursors: list[_IdentityCursor] = []

    def transaction(self) -> _IdentityTransaction:
        return _IdentityTransaction(self)

    def cursor(self) -> _IdentityCursor:
        cursor = _IdentityCursor(next(self._identities))
        self.cursors.append(cursor)
        return cursor


def test_runtime_identity_is_checked_for_each_operation() -> None:
    connection = _IdentityConnection((("runtime", "runtime"), ("admin", "runtime")))
    repository = PostgresInstrumentMasterRepository(
        cast(Any, connection),
        runtime_role="runtime",
        provider_roles=InstrumentMasterProviderRoles(),
    )

    assert (
        repository._run(  # pyright: ignore[reportPrivateUsage]
            lambda cursor: (cursor.execute("SELECT business"), "first")[1]
        )
        == "first"
    )
    with pytest.raises(InstrumentMasterPersistenceError, match="persistence failed"):
        repository._run(  # pyright: ignore[reportPrivateUsage]
            lambda cursor: (cursor.execute("SELECT business"), "second")[1]
        )

    calls = [statement for cursor in connection.cursors for statement in cursor.calls]
    assert calls == [
        "SELECT SESSION_USER, CURRENT_USER",
        'SET LOCAL search_path = "kunlun_instrument_provider", pg_catalog, pg_temp',
        "SELECT business",
        "SELECT SESSION_USER, CURRENT_USER",
    ]


def test_repository_rejects_admin_session_with_runtime_set_role(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    _connection, provider_schema, psycopg_api, roles = instrument_master_pg
    admin = psycopg_api.connect(
        os.environ["KUNLUN_TEST_POSTGRES_DSN"],
        options=f'-c search_path="{provider_schema}"',
    )
    result, storage = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000123",
        stock_body=_stock(name="管理员伪装身份"),
    )
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'SET ROLE "{roles.runtime}"')
            cursor.execute(f'SET search_path = "{provider_schema}", pg_catalog')
        admin.commit()
        repository = PostgresInstrumentMasterRepository(
            admin,
            schema=provider_schema,
            runtime_role=roles.runtime,
            provider_roles=roles,
        )

        with pytest.raises(InstrumentMasterPersistenceError, match="persistence failed"):
            repository.persist_authoritative_instrument_master_run(
                storage, result.run_id, result.manifest_date, result.manifest_capture_id
            )
        assert _count(admin, "tushare_instrument_master_runs") == 0
    finally:
        admin.close()


def test_repository_missing_record_is_candidate_and_historical_revision_is_reused(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    repository = _repository(instrument_master_pg)
    first, first_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000111",
        stock_body=_stock(name="名称甲"),
        observed_at=_OBSERVED,
    )
    changed, changed_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000112",
        stock_body=_stock(name="名称乙"),
        observed_at=_OBSERVED + timedelta(hours=1),
    )
    reverted, reverted_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000113",
        stock_body=_stock(name="名称甲"),
        observed_at=_OBSERVED + timedelta(hours=2),
    )
    missing, missing_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000114",
        stock_body=None,
        observed_at=_OBSERVED + timedelta(hours=3),
    )

    repository.persist_authoritative_instrument_master_run(
        first_raw, first.run_id, first.manifest_date, first.manifest_capture_id
    )
    repository.persist_authoritative_instrument_master_run(
        changed_raw, changed.run_id, changed.manifest_date, changed.manifest_capture_id
    )
    repository.persist_authoritative_instrument_master_run(
        reverted_raw, reverted.run_id, reverted.manifest_date, reverted.manifest_capture_id
    )
    repository.persist_authoritative_instrument_master_run(
        missing_raw, missing.run_id, missing.manifest_date, missing.manifest_capture_id
    )

    assert _count(connection, "tushare_instrument_master_revisions") == 2
    assert _count(connection, "tushare_instrument_master_removal_candidates") == 1
    assert _count(connection, "tushare_instrument_master_heads") == 1
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT listing_lifecycle, name FROM tushare_instrument_master_revisions AS r "
            "JOIN tushare_instrument_master_heads AS h ON h.revision_id = r.revision_id "
            "WHERE h.unified_code = '600000.SH'"
        )
        assert cursor.fetchone() == ("LISTED", "名称甲")


def test_repository_reversion_uses_current_snapshot_ordering_and_blocks_old_replay(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    repository = _repository(instrument_master_pg)
    first, first_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000115",
        stock_body=_stock(name="名称甲"),
        observed_at=_OBSERVED,
    )
    changed, changed_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000116",
        stock_body=_stock(name="名称乙"),
        observed_at=_OBSERVED + timedelta(hours=1),
    )
    reverted, reverted_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000117",
        stock_body=_stock(name="名称甲"),
        observed_at=_OBSERVED + timedelta(hours=2),
    )
    old_missing, old_missing_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000118",
        stock_body=None,
        observed_at=_OBSERVED + timedelta(minutes=30),
    )

    for result, storage in (
        (first, first_raw),
        (changed, changed_raw),
        (reverted, reverted_raw),
    ):
        repository.persist_authoritative_instrument_master_run(
            storage, result.run_id, result.manifest_date, result.manifest_capture_id
        )

    out_of_order = repository.persist_authoritative_instrument_master_run(
        old_missing_raw,
        old_missing.run_id,
        old_missing.manifest_date,
        old_missing.manifest_capture_id,
    )

    assert out_of_order.disposition == "NO_HEAD_CHANGE"
    assert out_of_order.run_disposition == "OUT_OF_ORDER"
    assert _count(connection, "tushare_instrument_master_removal_candidates") == 0
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.name FROM tushare_instrument_master_heads AS h "
            "JOIN tushare_instrument_master_revisions AS r ON r.revision_id = h.revision_id "
            "WHERE h.unified_code = '600000.SH'"
        )
        assert cursor.fetchone() == ("名称甲",)


def test_repository_rejects_same_ordering_coordinate_with_different_content(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    repository = _repository(instrument_master_pg)
    first, first_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000119",
        stock_body=_stock(name="名称甲"),
        observed_at=_OBSERVED,
    )
    conflict, conflict_raw = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000120",
        stock_body=_stock(name="名称乙"),
        observed_at=_OBSERVED,
    )
    repository.persist_authoritative_instrument_master_run(
        first_raw, first.run_id, first.manifest_date, first.manifest_capture_id
    )

    outcome = repository.persist_authoritative_instrument_master_run(
        conflict_raw,
        conflict.run_id,
        conflict.manifest_date,
        conflict.manifest_capture_id,
    )

    assert outcome.disposition == "CONFLICT"
    assert outcome.run_disposition == "CONFLICT"


def test_repository_pit_hides_future_publication_and_conflict_does_not_write(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    repository = _repository(instrument_master_pg)
    run_id = "00000000-0000-4000-8000-000000000121"
    result, storage = _collect(tmp_path, run_id, stock_body=_stock())
    first = repository.persist_authoritative_instrument_master_run(
        storage, result.run_id, result.manifest_date, result.manifest_capture_id
    )
    assert first.snapshot_id is not None

    conflict, conflict_storage = _collect(tmp_path, run_id, stock_body=_stock(name="冲突名称"))
    outcome = repository.persist_authoritative_instrument_master_run(
        conflict_storage,
        conflict.run_id,
        conflict.manifest_date,
        conflict.manifest_capture_id,
    )
    assert outcome.disposition == "CONFLICT"
    assert _count(connection, "tushare_instrument_master_runs") == 1

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT published_at FROM tushare_instrument_master_snapshots WHERE snapshot_id = %s",
            (first.snapshot_id,),
        )
        published_at = cursor.fetchone()[0]
    assert isinstance(published_at, datetime)
    assert repository.query_as_of("600000.SH", published_at - timedelta(microseconds=1)).status == (
        "INDETERMINATE"
    )
    assert repository.query_as_of("600000.SH", published_at + timedelta(microseconds=1)).status == (
        "VISIBLE"
    )

    removal_result, removal_storage = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000122",
        stock_body=None,
        observed_at=_OBSERVED + timedelta(hours=1),
    )
    removal = repository.persist_authoritative_instrument_master_run(
        removal_storage,
        removal_result.run_id,
        removal_result.manifest_date,
        removal_result.manifest_capture_id,
    )
    assert removal.snapshot_id is not None
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT published_at FROM tushare_instrument_master_snapshots WHERE snapshot_id = %s",
            (removal.snapshot_id,),
        )
        removal_published_at = cursor.fetchone()[0]
    assert isinstance(removal_published_at, datetime)
    assert (
        repository.query_as_of("600000.SH", removal_published_at - timedelta(microseconds=1)).status
        == "VISIBLE"
    )
    assert (
        repository.query_as_of("600000.SH", removal_published_at + timedelta(microseconds=1)).status
        == "INDETERMINATE"
    )


def test_repository_rolls_back_and_rejects_non_idle_connection(
    tmp_path: Path,
    instrument_master_pg: ProviderContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    repository = _repository(instrument_master_pg)
    result, storage = _collect(
        tmp_path,
        "00000000-0000-4000-8000-000000000131",
        stock_body=_stock(),
    )

    connection.execute("SELECT 1")
    with pytest.raises(InstrumentMasterRepositoryTransactionError):
        repository.persist_authoritative_instrument_master_run(
            storage, result.run_id, result.manifest_date, result.manifest_capture_id
        )
    connection.rollback()

    def fail_insert(*_: object) -> None:
        raise RuntimeError("controlled rollback")

    monkeypatch.setattr(
        PostgresInstrumentMasterRepository,
        "_insert_revision",
        staticmethod(fail_insert),
    )
    with pytest.raises(InstrumentMasterPersistenceError, match="persistence failed"):
        repository.persist_authoritative_instrument_master_run(
            storage, result.run_id, result.manifest_date, result.manifest_capture_id
        )
    assert _count(connection, "tushare_instrument_master_runs") == 0


def test_concurrent_same_evidence_has_one_winner(
    tmp_path: Path, instrument_master_pg: ProviderContext
) -> None:
    result, storage = _collect(
        tmp_path,
        "00000000-0000-4000-0000-000000000141",
        stock_body=_stock(),
    )
    context = instrument_master_pg

    def persist_once() -> str:
        connection = _new_connection(context)
        try:
            outcome = PostgresInstrumentMasterRepository(
                connection,
                schema=context[1],
                runtime_role=context[3].runtime,
                provider_roles=context[3],
            ).persist_authoritative_instrument_master_run(
                storage, result.run_id, result.manifest_date, result.manifest_capture_id
            )
            return outcome.disposition
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:

        def invoke(_: int) -> str:
            return persist_once()

        outcomes = list(executor.map(invoke, range(2)))
    assert sorted(outcomes) == ["DUPLICATE", "SNAPSHOT_CANDIDATE"]


def test_v5_schema_binds_definer_and_actor_security_to_database_identity(
    instrument_master_pg: ProviderContext,
) -> None:
    connection, _provider_schema, _psycopg, _roles = instrument_master_pg
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.prosecdef, p.proconfig "
            "FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
            "WHERE n.nspname = current_schema() "
            "AND p.proname = 'tushare_instrument_master_publish_head'"
        )
        is_definer, config = cursor.fetchone()
        assert is_definer is True
        assert tuple(config or ()) == ("search_path=pg_catalog, pg_temp",)
        cursor.execute(
            "SELECT has_function_privilege('public', "
            "'tushare_instrument_master_publish_head("
            "text,uuid,timestamp with time zone)'::regprocedure, 'EXECUTE')"
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(
            "SELECT has_function_privilege('public', "
            "'tushare_instrument_master_current_actor()'::regprocedure, 'EXECUTE')"
        )
        assert cursor.fetchone()[0] is False
        cursor.execute("SELECT current_user::text")
        database_user = str(cursor.fetchone()[0])

        run_id = uuid4()
        now = datetime.now(UTC)
        cursor.execute(
            "INSERT INTO tushare_instrument_master_runs "
            "(run_id, source, profile_version, schema_version, parser_version, manifest_date, "
            "manifest_capture_id, manifest_object_id, terminal, completeness, disposition, "
            "reason_code, record_count, opened_at, completed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run_id,
                TUSHARE_INSTRUMENT_SOURCE,
                "tushare-instrument-profile-v1",
                "tushare-instrument-raw-v1",
                "tushare-instrument-parser-v1",
                "2026-09-08",
                "security-test-manifest",
                "0" * 64,
                "FAILED",
                "REJECTED",
                "REJECTED",
                "security_test",
                0,
                now,
                now,
            ),
        )
        cursor.execute(
            "INSERT INTO tushare_instrument_master_audit "
            "(audit_id, run_id, action, details, actor) VALUES (%s, %s, %s, %s::jsonb, %s)",
            (uuid4(), run_id, "RUN_REJECTED", "{}", "forged-actor"),
        )
        cursor.execute(
            "SELECT actor FROM tushare_instrument_master_audit WHERE run_id = %s",
            (run_id,),
        )
        assert cursor.fetchone()[0] == database_user
