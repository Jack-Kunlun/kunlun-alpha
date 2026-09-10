"""Isolated PostgreSQL contract tests for the calendar-quality V5 ledger."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import os
import re
import runpy
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import data_worker.jobs.calendars.official_szse_daily as official_szse_daily_module
import data_worker.storage as storage_package
import pytest
from data_worker.jobs.calendars.calendar_quality import (
    CalendarClosureEvidence,
    CalendarQualityDay,
    CalendarQualityEvidenceLink,
    CalendarQualityOverlay,
    CalendarQualitySource,
    assess_calendar_quality,
)
from data_worker.jobs.calendars.calendar_quality_repository import (
    CalendarQualityOperationConflictError,
    CalendarQualityOverlayConflictError,
    CalendarQualityPersistenceError,
    PostgresCalendarQualityRepository,
)
from data_worker.jobs.calendars.official_calendar_repository import (
    PostgresOfficialCalendarRepository,
    official_calendar_snapshot_id,
)
from data_worker.jobs.calendars.official_szse_daily import SzseOfficialCalendarCollector
from data_worker.raw import LocalFileStorage
from data_worker.storage import migrations as migration_module
from data_worker.storage.migrations import (
    CALENDAR_QUALITY_MIGRATION_NAME,
    CALENDAR_QUALITY_MIGRATION_VERSION,
    CalendarQualityPublishDisposition,
    CalendarQualityRoles,
    apply_data_worker_migrations,
    prepare_calendar_quality_runtime_context,
    publish_calendar_quality,
    verify_calendar_quality_reader,
    verify_calendar_quality_runtime,
)
from psycopg import errors, sql

_AVAILABLE = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
_QUALITY_SCHEMA_RE = r"^calendar_quality_(p1n07|diag|drift)_[0-9a-f]{32}$"
_TEST_DATABASE_RE = re.compile(r"^kunlun_test_[a-z0-9_]+$")
_TEST_DATABASE_MARKER = "kunlun-calendar-quality-pg-test-v1"


def _apply_calendar_quality_for_test(
    connection: Any,
    *,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    with connection.transaction(), connection.cursor() as cursor:
        migration_module._apply_calendar_quality_migration_in_transaction(
            cursor,
            schema=schema,
            roles=roles,
        )


def _seal_calendar_quality_for_test(
    connection: Any,
    *,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    with connection.transaction(), connection.cursor() as cursor:
        migration_module._seal_calendar_quality_in_transaction(
            cursor,
            schema=schema,
            roles=roles,
        )


def test_calendar_quality_split_mutations_are_not_public_storage_api() -> None:
    forbidden = {
        "CALENDAR_QUALITY_MIGRATION",
        "apply_calendar_quality_migration",
        "load_calendar_quality_migration",
        "seal_calendar_quality",
    }
    assert forbidden.isdisjoint(storage_package.__all__)
    assert all(not hasattr(storage_package, name) for name in forbidden)


class _IsolationProbeCursor:
    def __init__(
        self,
        database: str,
        marker: str | None,
        *,
        schema: str | None = "public",
        search_path: str = '"$user", public',
        identity: tuple[str, str] | None = None,
    ) -> None:
        self.database = database
        self.marker = marker
        self.schema = schema
        self.search_path = search_path
        self.identity = identity
        self.queries: list[str] = []
        self._fetch_index = 0

    def execute(self, query: str, _parameters: object = None) -> None:
        self.queries.append(query)

    def fetchone(self) -> tuple[Any, ...] | None:
        if self._fetch_index == 0:
            self._fetch_index += 1
            marker_relation = (
                "public.kunlun_test_database_marker" if self.marker is not None else None
            )
            return (self.database, self.schema, self.search_path, marker_relation)
        self._fetch_index += 1
        if self._fetch_index == 2:
            if self.marker is None:
                return None
            return (self.marker, 1)
        return self.identity


def _assert_isolated_quality_test_database(
    cursor: Any,
    *,
    schema: str | None = None,
    expected_identity: tuple[str, str] | None = None,
    allow_migrator_pre_set_role: bool = False,
) -> None:
    cursor.execute(
        "SELECT current_database(), current_schema(), current_setting('search_path'), "
        "to_regclass('public.kunlun_test_database_marker')"
    )
    row = cursor.fetchone()
    if row is None or len(row) != 4 or not _TEST_DATABASE_RE.fullmatch(str(row[0])):
        raise ValueError("dedicated test database is required")
    if row[3] is None:
        raise ValueError("database marker is required")
    cursor.execute("SELECT marker, count(*) OVER () FROM public.kunlun_test_database_marker")
    marker_row = cursor.fetchone()
    if marker_row is None or tuple(marker_row) != (_TEST_DATABASE_MARKER, 1):
        raise ValueError("database marker is invalid")
    if schema is not None:
        observed_search_path = str(row[2]).replace('"', "").replace(" ", "")
        schema_visible = str(row[1]) == schema
        schema_hidden_before_role = allow_migrator_pre_set_role and row[1] is None
        if (not schema_visible and not schema_hidden_before_role) or observed_search_path != schema:
            raise ValueError("test database schema context is invalid")
    if expected_identity is not None:
        cursor.execute("SELECT SESSION_USER, CURRENT_USER")
        identity = cursor.fetchone()
        if identity is None or tuple(str(value) for value in identity) != expected_identity:
            raise ValueError("test database identity is invalid")


def test_test_database_guard_rejects_formal_database_before_write() -> None:
    cursor = _IsolationProbeCursor("kunlun", "kunlun-calendar-quality-pg-test-v1")

    with pytest.raises(ValueError, match="dedicated test database"):
        _assert_isolated_quality_test_database(cursor)

    assert not any(
        query.lstrip().upper().startswith(("CREATE", "DROP", "INSERT")) for query in cursor.queries
    )


def test_test_database_guard_rejects_missing_marker_before_write() -> None:
    cursor = _IsolationProbeCursor("kunlun_test_quality", None)

    with pytest.raises(ValueError, match="database marker"):
        _assert_isolated_quality_test_database(cursor)

    assert not any(
        query.lstrip().upper().startswith(("CREATE", "DROP", "INSERT")) for query in cursor.queries
    )


def test_migrator_pre_set_role_guard_allows_null_schema_only_explicitly() -> None:
    cursor = _IsolationProbeCursor(
        "kunlun_test_calendar_quality_20260909",
        _TEST_DATABASE_MARKER,
        schema=None,
        search_path='"calendar_quality_diag_abc"',
        identity=("cq_migrator_abc", "cq_migrator_abc"),
    )

    _assert_isolated_quality_test_database(
        cursor,
        schema="calendar_quality_diag_abc",
        expected_identity=("cq_migrator_abc", "cq_migrator_abc"),
        allow_migrator_pre_set_role=True,
    )


def test_default_schema_guard_rejects_null_current_schema() -> None:
    cursor = _IsolationProbeCursor(
        "kunlun_test_calendar_quality_20260909",
        _TEST_DATABASE_MARKER,
        schema=None,
        search_path='"calendar_quality_diag_abc"',
        identity=("cq_migrator_abc", "cq_migrator_abc"),
    )

    with pytest.raises(ValueError, match="schema context"):
        _assert_isolated_quality_test_database(
            cursor,
            schema="calendar_quality_diag_abc",
            expected_identity=("cq_migrator_abc", "cq_migrator_abc"),
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


def _assert_quality_schemas_clean(admin: Any) -> None:
    with admin.cursor() as cursor:
        cursor.execute("SELECT nspname FROM pg_namespace WHERE nspname ~ %s", (_QUALITY_SCHEMA_RE,))
        leftovers = [str(row[0]) for row in cursor.fetchall()]
    assert leftovers == []


def _drop_quality_schema(admin: Any, schema: str) -> None:
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    _assert_quality_schemas_clean(admin)


def _source(
    source_id: UUID,
    *,
    source_name: str = "sse-calendar",
    source_fingerprint: str = "b" * 64,
    links: tuple[CalendarQualityEvidenceLink, ...] | None = None,
    closures: tuple[CalendarClosureEvidence, ...] = (),
) -> CalendarQualitySource:
    if links is None:
        links = (
            CalendarQualityEvidenceLink(
                source_id=source_id,
                evidence_ref=f"evidence-{source_id.hex}",
                artifact_sha256="a" * 64,
            ),
        )
    return CalendarQualitySource(
        source_id=source_id,
        source_kind="SPARSE",
        source_name=source_name,
        exchange="SH",
        year=2026,
        captured_at=_AVAILABLE,
        available_at=_AVAILABLE,
        coverage_level="UNKNOWN",
        confirmed_through=None,
        source_fingerprint=source_fingerprint,
        days=(
            CalendarQualityDay(
                calendar_date=date(2026, 1, 1),
                is_trading_day=False,
                reason="PUBLIC_HOLIDAY",
            ),
        ),
        evidence_links=links,
        closures=closures,
    )


@contextmanager
def _fixture_identity_pins(helpers: dict[str, Any]) -> Generator[None, None, None]:
    fixture_bodies = {
        "root": helpers["_official_root_body"](),
        "path": helpers["_official_path_body"](),
        "concat": helpers["_official_concatversion_body"](),
        "js": helpers["_official_js_body"](),
    }
    original_pins = official_szse_daily_module._IDENTITY_SOURCE_SHA256
    official_szse_daily_module._IDENTITY_SOURCE_SHA256 = {
        kind: hashlib.sha256(body).hexdigest() for kind, body in fixture_bodies.items()
    }
    try:
        yield
    finally:
        official_szse_daily_module._IDENTITY_SOURCE_SHA256 = original_pins


class _DelayedCutoffClock:
    def __init__(self, base_clock: Any) -> None:
        self._base_clock = base_clock
        self._index = 0

    def __call__(self) -> datetime:
        value = self._base_clock()
        if self._index >= 41:
            value += timedelta(hours=1)
        self._index += 1
        return value


def _collect_v4_result(
    root: Path, *, run_id: UUID | None = None, delayed_cutoff: bool = False
) -> tuple[Any, Any, dict[str, Any]]:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_official_szse_daily.py")))
    raw = LocalFileStorage(root / "raw")
    clock: Any = helpers["_Clock"]()
    if delayed_cutoff:
        clock = _DelayedCutoffClock(clock)
    collector = SzseOfficialCalendarCollector(
        raw,
        transport=helpers["_transport"](),
        clock=clock,
        run_id=uuid4() if run_id is None else run_id,
    )
    with _fixture_identity_pins(helpers):
        result = collector.collect()
    return result, raw, helpers


def _v4_references(result: Any) -> tuple[Any, ...]:
    ordered: list[Any] = []
    seen: set[tuple[str, str, str]] = set()

    def add(reference: Any) -> None:
        if reference is None:
            return
        key = (reference.kind, reference.capture_id, reference.checksum)
        if key not in seen:
            seen.add(key)
            ordered.append(reference)

    for identity, attempt in zip(result.identity_assets, result.attempts[:4], strict=True):
        add(identity)
        add(attempt.state_ref)
    for reference in result.catalog_refs:
        add(reference)
    for attempt in result.attempts[4:]:
        add(attempt.raw_ref)
        add(attempt.state_ref)
    add(result.raw_manifest_ref)
    return tuple(ordered)


def _v4_source(snapshot_id: UUID, result: Any) -> CalendarQualitySource:
    proof = result.proof
    return CalendarQualitySource(
        source_id=snapshot_id,
        source_kind="OFFICIAL",
        source_name=proof.authority,
        exchange=proof.exchange,
        year=proof.year,
        captured_at=proof.opened_at,
        available_at=proof.cutoff_at,
        coverage_level=proof.coverage.level.value,
        confirmed_through=proof.coverage.confirmed_through,
        source_fingerprint=proof.proof_digest,
        days=tuple(
            CalendarQualityDay(
                calendar_date=day.date,
                is_trading_day=day.is_trading_day,
                reason=None if day.is_trading_day else "SPECIAL",
            )
            for day in proof.daily_days
        ),
        evidence_links=tuple(
            CalendarQualityEvidenceLink(
                source_id=snapshot_id,
                evidence_ref=reference.capture_id,
                artifact_sha256=reference.checksum,
            )
            for reference in _v4_references(result)
        ),
    )


def _seed_v4_source(
    connection: Any,
    root: Path,
    *,
    run_id: UUID | None = None,
    delayed_cutoff: bool = False,
) -> tuple[UUID, CalendarQualitySource, Any, dict[str, Any]]:
    result, raw, helpers = _collect_v4_result(root, run_id=run_id, delayed_cutoff=delayed_cutoff)
    with _fixture_identity_pins(helpers):
        outcome = PostgresOfficialCalendarRepository(connection).persist_authoritative_szse_run(
            raw,
            result.run_id,
            result.raw_manifest_ref.raw_date,
            result.raw_manifest_ref.capture_id,
        )
    snapshot_id = outcome.snapshot_id
    if snapshot_id is None:
        raise AssertionError("fixture V4 run did not create a snapshot")
    assert snapshot_id == official_calendar_snapshot_id(result.run_id)
    return snapshot_id, _v4_source(snapshot_id, result), result, helpers


def _insert_snapshot_version(connection: Any, source_id: UUID, fingerprint: str = "b" * 64) -> None:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO calendar_snapshot_versions "
            "(version_id, source, exchange, year, fingerprint) VALUES (%s, %s, %s, %s, %s)",
            (source_id, "sse-calendar", "SH", 2026, bytes.fromhex(fingerprint)),
        )


@pytest.fixture()
def quality_pre_v5_postgres() -> Generator[tuple[Any, str], None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:
        pytest.fail(f"configured PostgreSQL fixture could not connect: {type(exc).__name__}")
    schema = f"calendar_quality_diag_{uuid4().hex}"
    connection: Any = None
    isolation_verified = False
    try:
        with admin.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor)
            isolation_verified = True
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with connection.transaction(), connection.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor, schema=schema)
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(connection)
        yield connection, schema
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            try:
                if isolation_verified:
                    _drop_quality_schema(admin, schema)
            finally:
                admin.close()


@pytest.fixture()
def quality_migration_pre_v5_postgres() -> Generator[
    tuple[Any, Any, str, CalendarQualityRoles], None, None
]:
    """Provide an isolated admin/migrator pair for strict migration tests."""

    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:
        pytest.fail(f"configured PostgreSQL fixture could not connect: {type(exc).__name__}")
    suffix = uuid4().hex
    schema = f"calendar_quality_diag_{suffix}"
    roles = CalendarQualityRoles(
        owner=f"cq_owner_{suffix[:48]}",
        migrator=f"cq_migrator_{suffix[:45]}",
        runtime=f"cq_runtime_{suffix[:45]}",
        reader=f"cq_reader_{suffix[:46]}",
    )
    password = f"pw_{suffix}"
    admin_schema: Any = None
    migrator: Any = None
    isolation_verified = False
    try:
        with admin.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor)
            isolation_verified = True
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            for role in (roles.owner, roles.migrator, roles.runtime, roles.reader):
                login = "LOGIN" if role in {roles.migrator, roles.runtime} else "NOLOGIN"
                statement = sql.SQL(
                    "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.SQL(login))
                if role == roles.migrator:
                    statement += sql.SQL(" PASSWORD {} ").format(sql.Literal(password))
                cursor.execute(statement)
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(roles.owner)
                )
            )
        admin_schema = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with admin_schema.transaction(), admin_schema.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor, schema=schema)
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(admin_schema)
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT ON TABLE {}.data_worker_schema_migrations TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(roles.owner))
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE, ADMIN FALSE").format(
                    sql.Identifier(roles.owner), sql.Identifier(roles.migrator)
                )
            )
        migrator = psycopg.connect(
            dsn,
            user=roles.migrator,
            password=password,
            options=f'-c search_path="{schema}"',
        )
        with migrator.transaction(), migrator.cursor() as cursor:
            _assert_isolated_quality_test_database(
                cursor,
                schema=schema,
                expected_identity=(roles.migrator, roles.migrator),
                allow_migrator_pre_set_role=True,
            )
        yield admin_schema, migrator, schema, roles
    finally:
        cleanup_errors: list[str] = []
        for connection in (migrator, admin_schema):
            if connection is not None:
                try:
                    connection.close()
                except BaseException as exc:
                    cleanup_errors.append(f"connection close: {type(exc).__name__}")
        try:
            with admin.cursor() as cursor:
                if isolation_verified:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                    )
        except BaseException as exc:
            cleanup_errors.append(f"schema drop: {type(exc).__name__}")
        for role in (roles.migrator, roles.runtime, roles.reader, roles.owner):
            try:
                with admin.cursor() as cursor:
                    if isolation_verified:
                        cursor.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )
            except BaseException as exc:
                cleanup_errors.append(f"role drop: {role}:{type(exc).__name__}")
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                    ([roles.owner, roles.migrator, roles.runtime, roles.reader],),
                )
                leftovers = [str(row[0]) for row in cursor.fetchall()]
                if leftovers:
                    cleanup_errors.append(f"role leftovers: {','.join(leftovers)}")
        except BaseException as exc:
            cleanup_errors.append(f"cleanup assertion: {type(exc).__name__}")
        try:
            admin.close()
        except BaseException as exc:
            cleanup_errors.append(f"admin close: {type(exc).__name__}")
        if cleanup_errors:
            pytest.fail("; ".join(cleanup_errors))


def test_wrong_v5_ledger_fails_closed_without_objects_or_rewrite(
    quality_migration_pre_v5_postgres: tuple[Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, migrator, schema, roles = quality_migration_pre_v5_postgres
    wrong_name = f"{CALENDAR_QUALITY_MIGRATION_NAME}-wrong"
    wrong_checksum = "0" * 64
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {}.data_worker_schema_migrations "
                "(version, name, checksum, applied_at) VALUES (%s, %s, %s, %s)"
            ).format(sql.Identifier(schema)),
            (CALENDAR_QUALITY_MIGRATION_VERSION, wrong_name, wrong_checksum, _AVAILABLE),
        )

    with pytest.raises(ValueError, match="checksum or name drift"):
        _apply_calendar_quality_for_test(migrator, schema=schema, roles=roles)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "SELECT version, name, checksum FROM {}.data_worker_schema_migrations "
                "WHERE version=%s"
            ).format(sql.Identifier(schema)),
            (CALENDAR_QUALITY_MIGRATION_VERSION,),
        )
        assert cursor.fetchone() == (
            CALENDAR_QUALITY_MIGRATION_VERSION,
            wrong_name,
            wrong_checksum,
        )
        cursor.execute(
            "SELECT count(*) FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() "
            "AND position('calendar_quality_' IN c.relname)=1 "
            "AND c.relkind IN ('r', 'p')"
        )
        assert cursor.fetchone()[0] == 0


def test_orphan_quality_function_is_not_replaced_or_completed(
    quality_migration_pre_v5_postgres: tuple[Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, migrator, schema, roles = quality_migration_pre_v5_postgres
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "CREATE FUNCTION {}.calendar_quality_history_immutable() "
                "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END; $$"
            ).format(sql.Identifier(schema))
        )

    with pytest.raises(ValueError, match="untracked calendar quality schema"):
        _apply_calendar_quality_for_test(migrator, schema=schema, roles=roles)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid=p.pronamespace "
            "WHERE n.nspname=current_schema() "
            "AND p.proname='calendar_quality_history_immutable'"
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT count(*) FROM pg_class AS c "
            "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() "
            "AND position('calendar_quality_' IN c.relname)=1 "
            "AND c.relkind IN ('r', 'p')"
        )
        assert cursor.fetchone()[0] == 0


def test_partial_quality_table_is_not_replaced_or_completed(
    quality_migration_pre_v5_postgres: tuple[Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, migrator, schema, roles = quality_migration_pre_v5_postgres
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE TABLE {}.calendar_quality_assessments (sentinel INTEGER)").format(
                sql.Identifier(schema)
            )
        )

    with pytest.raises(ValueError, match="untracked calendar quality schema"):
        _apply_calendar_quality_for_test(migrator, schema=schema, roles=roles)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='calendar_quality_assessments'"
        )
        assert [str(row[0]) for row in cursor.fetchall()] == ["sentinel"]


@pytest.fixture()
def quality_publish_postgres() -> Generator[
    tuple[Any, str, CalendarQualityRoles, str, str], None, None
]:
    """Prepare a clean, isolated V1-V4 database state for atomic publish tests."""

    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:
        pytest.fail(f"configured PostgreSQL fixture could not connect: {type(exc).__name__}")
    suffix = uuid4().hex
    schema = f"calendar_quality_p1n07_{suffix}"
    roles = CalendarQualityRoles(
        owner=f"cq_pub_owner_{suffix[:50]}",
        migrator=f"cq_pub_migrator_{suffix[:46]}",
        runtime=f"cq_pub_runtime_{suffix[:47]}",
        reader=f"cq_pub_reader_{suffix[:47]}",
    )
    migrator_password = f"migrator_{suffix}"
    runtime_password = f"runtime_{suffix}"
    admin_schema: Any = None
    isolation_verified = False
    try:
        with admin.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor)
            isolation_verified = True
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        admin_schema = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with admin_schema.transaction(), admin_schema.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor, schema=schema)
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(admin_schema)
        yield admin_schema, schema, roles, migrator_password, runtime_password
    finally:
        cleanup_errors: list[str] = []
        if admin_schema is not None:
            try:
                admin_schema.close()
            except BaseException as exc:
                cleanup_errors.append(f"connection close: {type(exc).__name__}")
        try:
            if isolation_verified:
                with admin.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                    )
        except BaseException as exc:
            cleanup_errors.append(f"schema drop: {type(exc).__name__}")
        for role in (roles.migrator, roles.runtime, roles.reader, roles.owner):
            try:
                if isolation_verified:
                    with admin.cursor() as cursor:
                        cursor.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )
            except BaseException as exc:
                cleanup_errors.append(f"role drop: {role}:{type(exc).__name__}")
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname=%s",
                    (schema,),
                )
                if cursor.fetchone() is not None:
                    cleanup_errors.append(f"schema leftover: {schema}")
                cursor.execute(
                    "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                    ([roles.owner, roles.migrator, roles.runtime, roles.reader],),
                )
                leftovers = [str(row[0]) for row in cursor.fetchall()]
                if leftovers:
                    cleanup_errors.append(f"role leftovers: {','.join(leftovers)}")
        except BaseException as exc:
            cleanup_errors.append(f"cleanup assertion: {type(exc).__name__}")
        try:
            admin.close()
        except BaseException as exc:
            cleanup_errors.append(f"admin close: {type(exc).__name__}")
        if cleanup_errors:
            pytest.fail("; ".join(cleanup_errors))


def test_atomic_publish_installs_and_repeat_returns_already_sealed(
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres

    first = publish_calendar_quality(
        connection,
        schema=schema,
        roles=roles,
        migrator_password=migrator_password,
        runtime_password=runtime_password,
    )
    assert first.disposition is CalendarQualityPublishDisposition.PUBLISHED

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version=%s",
            (CALENDAR_QUALITY_MIGRATION_VERSION,),
        )
        assert cursor.fetchone() == (
            CALENDAR_QUALITY_MIGRATION_VERSION,
            CALENDAR_QUALITY_MIGRATION_NAME,
            hashlib.sha256(migration_module.load_calendar_quality_migration()).hexdigest(),
        )
        cursor.execute(
            "SELECT member.rolname, granted.rolname, m.inherit_option, "
            "m.set_option, m.admin_option "
            "FROM pg_catalog.pg_auth_members AS m "
            "JOIN pg_catalog.pg_roles AS member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles AS granted ON granted.oid=m.roleid "
            "WHERE member.rolname=%s OR granted.rolname=%s",
            (roles.migrator, roles.owner),
        )
        assert cursor.fetchall() == []
        cursor.execute(
            "SELECT rolpassword FROM pg_catalog.pg_authid WHERE rolname=%s",
            (roles.migrator,),
        )
        password_before = cursor.fetchone()

    second = publish_calendar_quality(
        connection,
        schema=schema,
        roles=roles,
        migrator_password="a-different-password-that-must-not-rotate",
        runtime_password="another-different-password-that-must-not-rotate",
    )
    assert second.disposition is CalendarQualityPublishDisposition.ALREADY_SEALED

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolpassword FROM pg_catalog.pg_authid WHERE rolname=%s",
            (roles.migrator,),
        )
        assert cursor.fetchone() == password_before
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_auth_members AS m "
            "JOIN pg_catalog.pg_roles AS member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles AS granted ON granted.oid=m.roleid "
            "WHERE member.rolname=%s OR granted.rolname=%s",
            (roles.migrator, roles.owner),
        )
        assert cursor.fetchone()[0] == 0


def test_atomic_publish_ignores_temporary_relation_shadows(
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE data_worker_schema_migrations (sentinel text)")
        cursor.execute("CREATE TEMP TABLE calendar_quality_assessments (sentinel text)")

    result = publish_calendar_quality(
        connection,
        schema=schema,
        roles=roles,
        migrator_password=migrator_password,
        runtime_password=runtime_password,
    )
    assert result.disposition is CalendarQualityPublishDisposition.PUBLISHED

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "SELECT count(*) FROM {}.data_worker_schema_migrations WHERE version=%s"
            ).format(sql.Identifier(schema)),
            (CALENDAR_QUALITY_MIGRATION_VERSION,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT to_regclass(%s) IS NOT NULL",
            (f'"{schema}".calendar_quality_assessments',),
        )
        assert cursor.fetchone()[0] is True


def test_atomic_publish_rejects_non_idle_connection_before_write(
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

    with pytest.raises(ValueError, match="idle connection"):
        publish_calendar_quality(
            connection,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )
    connection.rollback()

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname=ANY(%s)",
            (list(roles),),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname LIKE 'calendar_quality_%%'",
            (schema,),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            sql.SQL(
                "SELECT count(*) FROM {}.data_worker_schema_migrations WHERE version=%s"
            ).format(sql.Identifier(schema)),
            (CALENDAR_QUALITY_MIGRATION_VERSION,),
        )
        assert cursor.fetchone()[0] == 0


def test_atomic_publish_preserves_unrelated_shared_schema_acl(
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    app_role = f"cq_test_app_{uuid4().hex[:40]}"
    app_role_created = False
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(app_role)))
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(app_role)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier("data_worker_schema_migrations"),
                    sql.Identifier(app_role),
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT (run_id) ON TABLE {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier("official_calendar_scan_runs"),
                    sql.Identifier(app_role),
                )
            )
        app_role_created = True

        result = publish_calendar_quality(
            connection,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )
        assert result.disposition is CalendarQualityPublishDisposition.PUBLISHED
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_catalog.has_schema_privilege(%s, %s, 'USAGE'), "
                "pg_catalog.has_table_privilege(%s, %s, 'SELECT'), "
                "pg_catalog.has_column_privilege(%s, %s, 'run_id', 'SELECT')",
                (
                    app_role,
                    schema,
                    app_role,
                    f'"{schema}".data_worker_schema_migrations',
                    app_role,
                    f'"{schema}".official_calendar_scan_runs',
                ),
            )
            assert tuple(cursor.fetchone()) == (True, True, True)
    finally:
        if app_role_created:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(
                        sql.Identifier(schema), sql.Identifier(app_role)
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}").format(
                        sql.Identifier(schema), sql.Identifier(app_role)
                    )
                )
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(app_role)))


@pytest.mark.parametrize(
    "failure_stage",
    ("after_roles", "before_migration", "after_migration", "before_seal"),
)
def test_atomic_publish_rolls_back_roles_objects_and_v5_ledger_on_failure(
    failure_stage: str,
    monkeypatch: pytest.MonkeyPatch,
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres

    original_create_roles = migration_module._calendar_quality_create_roles
    original_migration = migration_module._apply_calendar_quality_migration_in_transaction

    def fail_after_roles(*args: object, **kwargs: object) -> None:
        original_create_roles(*args, **kwargs)
        raise ValueError("injected calendar quality publish failure")

    def fail_before_migration(*_args: object, **_kwargs: object) -> None:
        raise ValueError("injected calendar quality publish failure")

    def fail_after_migration(*args: object, **kwargs: object) -> None:
        original_migration(*args, **kwargs)
        raise ValueError("injected calendar quality publish failure")

    def fail_before_seal(*_args: object, **_kwargs: object) -> None:
        raise ValueError("injected calendar quality publish failure")

    if failure_stage == "after_roles":
        monkeypatch.setattr(
            migration_module,
            "_calendar_quality_create_roles",
            fail_after_roles,
        )
    elif failure_stage == "before_migration":
        monkeypatch.setattr(
            migration_module,
            "_apply_calendar_quality_migration_in_transaction",
            fail_before_migration,
        )
    elif failure_stage == "after_migration":
        monkeypatch.setattr(
            migration_module,
            "_apply_calendar_quality_migration_in_transaction",
            fail_after_migration,
        )
    else:
        monkeypatch.setattr(
            migration_module,
            "_seal_calendar_quality_in_transaction",
            fail_before_seal,
        )

    with pytest.raises(ValueError, match="injected calendar quality publish failure"):
        publish_calendar_quality(
            connection,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT SESSION_USER, CURRENT_USER")
        assert cursor.fetchone() == ("kunlun", "kunlun")
        cursor.execute(
            "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
            ([roles.owner, roles.migrator, roles.runtime, roles.reader],),
        )
        assert cursor.fetchall() == []
        cursor.execute("SELECT version FROM data_worker_schema_migrations ORDER BY version")
        assert [int(row[0]) for row in cursor.fetchall()] == [1, 2, 3, 4]
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() "
            "AND c.relname LIKE 'calendar_quality_%%'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_proc AS p "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
            "WHERE n.nspname=current_schema() "
            "AND p.proname LIKE 'calendar_quality_%%'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
            "WHERE n.nspname=current_schema() AND x.grantee=0"
        )
        assert cursor.fetchone()[0] == 0


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL is unavailable on Windows")
def test_atomic_publish_sigkill_rolls_back_unsealed_v5_transaction(
    tmp_path: Path,
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    ready_path = tmp_path / "calendar-quality-publish-ready"
    environment = os.environ.copy()
    source_root = Path(__file__).resolve().parents[3] / "src"
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root)
        if not existing_pythonpath
        else os.pathsep.join((str(source_root), existing_pythonpath))
    )
    environment.update(
        {
            "CQ_TEST_SCHEMA": schema,
            "CQ_TEST_OWNER": roles.owner,
            "CQ_TEST_MIGRATOR": roles.migrator,
            "CQ_TEST_RUNTIME": roles.runtime,
            "CQ_TEST_READER": roles.reader,
            "CQ_TEST_MIGRATOR_PASSWORD": migrator_password,
            "CQ_TEST_RUNTIME_PASSWORD": runtime_password,
            "CQ_TEST_READY_PATH": str(ready_path),
        }
    )
    child_source = """
import os
import time
from pathlib import Path

import psycopg
from data_worker.storage import migrations as migration_module

schema = os.environ["CQ_TEST_SCHEMA"]
roles = migration_module.CalendarQualityRoles(
    owner=os.environ["CQ_TEST_OWNER"],
    migrator=os.environ["CQ_TEST_MIGRATOR"],
    runtime=os.environ["CQ_TEST_RUNTIME"],
    reader=os.environ["CQ_TEST_READER"],
)
connection = psycopg.connect(
    os.environ["KUNLUN_TEST_POSTGRES_DSN"],
    options=f'-c search_path="{schema}"',
)

def pause_before_seal(*_args, **_kwargs):
    Path(os.environ["CQ_TEST_READY_PATH"]).write_text("ready", encoding="utf-8")
    time.sleep(300)

migration_module._seal_calendar_quality_in_transaction = pause_before_seal
migration_module.publish_calendar_quality(
    connection,
    schema=schema,
    roles=roles,
    migrator_password=os.environ["CQ_TEST_MIGRATOR_PASSWORD"],
    runtime_password=os.environ["CQ_TEST_RUNTIME_PASSWORD"],
)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_source],
        cwd=Path(__file__).resolve().parents[4],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not ready_path.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = "" if process.stderr is None else process.stderr.read()
                pytest.fail(f"publish child exited before SIGKILL checkpoint: {stderr}")
            time.sleep(0.05)
        assert ready_path.exists(), "publish child did not reach the pre-seal checkpoint"

        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        assert process.returncode == -signal.SIGKILL

        rollback_deadline = time.monotonic() + 10
        while True:
            with connection.transaction(), connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                    ([roles.owner, roles.migrator, roles.runtime, roles.reader],),
                )
                remaining_roles = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT count(*) FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() "
                    "AND c.relname LIKE 'calendar_quality_%%'"
                )
                remaining_relations = int(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT count(*) FROM data_worker_schema_migrations WHERE version=%s",
                    (CALENDAR_QUALITY_MIGRATION_VERSION,),
                )
                remaining_ledger = int(cursor.fetchone()[0])
            if (remaining_roles, remaining_relations, remaining_ledger) == (0, 0, 0):
                break
            if time.monotonic() >= rollback_deadline:
                pytest.fail("SIGKILL left an unsealed calendar quality transaction behind")
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


@pytest.mark.parametrize(
    ("object_name", "drift"),
    (
        ("tasks", "direct"),
        ("calendar_snapshot_versions", "direct"),
        ("official_calendar_capture_attempts", "direct"),
        ("tasks", "public"),
        ("calendar_snapshot_versions", "public"),
        ("official_calendar_capture_attempts", "public"),
        ("tasks", "owner"),
        ("data_worker_schema_migrations", "direct"),
        ("data_worker_schema_migrations", "public"),
        ("data_worker_schema_migrations", "owner"),
        ("official_calendar_scan_runs", "owner"),
        ("tasks", "column_direct"),
        ("tasks", "column_public"),
        ("calendar_snapshot_versions", "column_direct"),
        ("official_calendar_capture_attempts", "column_public"),
        ("data_worker_schema_migrations", "column_direct"),
        ("data_worker_schema_migrations", "column_public"),
        ("official_calendar_scan_runs", "column_direct"),
        ("calendar_quality_assessments", "column_direct"),
        ("calendar_quality_assessments", "column_public"),
        ("quality_drift_seq", "sequence_direct"),
        ("quality_drift_seq", "sequence_public"),
        ("quality_drift_seq", "sequence_owner"),
    ),
)
def test_publish_rejects_non_whitelist_shared_complement_drift(
    object_name: str,
    drift: str,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, _runtime, schema, roles = sealed_quality_roles_postgres
    with admin.transaction(), admin.cursor() as cursor:
        if drift == "direct":
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(object_name),
                    sql.Identifier(roles.runtime),
                )
            )
        elif drift == "public":
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO PUBLIC").format(
                    sql.Identifier(schema), sql.Identifier(object_name)
                )
            )
        elif drift == "owner":
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} OWNER TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(object_name),
                    sql.Identifier(roles.runtime),
                )
            )
        elif drift in {"column_direct", "column_public"}:
            column = {
                "tasks": "id",
                "calendar_snapshot_versions": "version_id",
                "official_calendar_capture_attempts": "run_id",
                "data_worker_schema_migrations": "version",
                "official_calendar_scan_runs": "run_id",
                "calendar_quality_assessments": "status",
            }[object_name]
            grantee = (
                sql.SQL("PUBLIC") if drift == "column_public" else sql.Identifier(roles.runtime)
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ({}) ON TABLE {}.{} TO {}").format(
                    sql.Identifier(column),
                    sql.Identifier(schema),
                    sql.Identifier(object_name),
                    grantee,
                )
            )
        else:
            cursor.execute(
                sql.SQL("CREATE SEQUENCE {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(object_name)
                )
            )
            if drift == "sequence_direct":
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SEQUENCE {}.{} TO {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(object_name),
                        sql.Identifier(roles.runtime),
                    )
                )
            elif drift == "sequence_public":
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SEQUENCE {}.{} TO PUBLIC").format(
                        sql.Identifier(schema), sql.Identifier(object_name)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("ALTER SEQUENCE {}.{} OWNER TO {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(object_name),
                        sql.Identifier(roles.runtime),
                    )
                )

    with pytest.raises(ValueError, match=r"schema (?:complement|ACL drift)"):
        publish_calendar_quality(
            admin,
            schema=schema,
            roles=roles,
            migrator_password="must-not-rotate",
            runtime_password="must-not-rotate",
        )


@pytest.mark.parametrize("relation_kind", ("partitioned", "view", "materialized", "foreign"))
def test_publish_rejects_shared_complement_relation_kind_privileges(
    relation_kind: str,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, _runtime, schema, roles = sealed_quality_roles_postgres
    suffix = uuid4().hex[:16]
    relation = f"quality_drift_{relation_kind}_{suffix}"
    wrapper = f"quality_drift_fdw_{suffix}"
    server = f"quality_drift_server_{suffix}"
    foreign_resources_created = False
    try:
        with admin.transaction(), admin.cursor() as cursor:
            if relation_kind == "partitioned":
                cursor.execute(
                    sql.SQL("CREATE TABLE {}.{} (id integer) PARTITION BY RANGE (id)").format(
                        sql.Identifier(schema), sql.Identifier(relation)
                    )
                )
            elif relation_kind == "view":
                cursor.execute(
                    sql.SQL("CREATE VIEW {}.{} AS SELECT id FROM {}.tasks").format(
                        sql.Identifier(schema),
                        sql.Identifier(relation),
                        sql.Identifier(schema),
                    )
                )
            elif relation_kind == "materialized":
                cursor.execute(
                    sql.SQL(
                        "CREATE MATERIALIZED VIEW {}.{} AS SELECT id FROM {}.tasks WITH NO DATA"
                    ).format(
                        sql.Identifier(schema),
                        sql.Identifier(relation),
                        sql.Identifier(schema),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("CREATE FOREIGN DATA WRAPPER {}").format(sql.Identifier(wrapper))
                )
                cursor.execute(
                    sql.SQL("CREATE SERVER {} FOREIGN DATA WRAPPER {}").format(
                        sql.Identifier(server), sql.Identifier(wrapper)
                    )
                )
                cursor.execute(
                    sql.SQL("CREATE FOREIGN TABLE {}.{} (id integer) SERVER {}").format(
                        sql.Identifier(schema),
                        sql.Identifier(relation),
                        sql.Identifier(server),
                    )
                )
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier(schema),
                    sql.Identifier(relation),
                    sql.Identifier(roles.runtime),
                )
            )
        foreign_resources_created = relation_kind == "foreign"

        with pytest.raises(ValueError, match="schema complement role ACL drift"):
            publish_calendar_quality(
                admin,
                schema=schema,
                roles=roles,
                migrator_password="must-not-rotate",
                runtime_password="must-not-rotate",
            )
    finally:
        if foreign_resources_created:
            with admin.transaction(), admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SERVER {} CASCADE").format(sql.Identifier(server)))
                cursor.execute(
                    sql.SQL("DROP FOREIGN DATA WRAPPER {}").format(sql.Identifier(wrapper))
                )


def test_clean_publish_rejects_public_column_acl_before_role_creation(
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT (id) ON TABLE {}.tasks TO PUBLIC").format(sql.Identifier(schema))
        )

    with pytest.raises(ValueError, match="PUBLIC column ACL drift"):
        publish_calendar_quality(
            connection,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname=ANY(%s)",
            (list(roles),),
        )
        assert cursor.fetchone()[0] == 0


@pytest.mark.parametrize(
    ("object_name", "drift", "column"),
    (
        ("schema", "schema", None),
        ("data_worker_schema_migrations", "table", None),
        ("data_worker_schema_migrations", "column", "version"),
        ("official_calendar_scan_runs", "table", None),
        ("official_calendar_snapshots", "column", "snapshot_id"),
    ),
)
def test_clean_publish_preserves_and_rejects_allowed_surface_public_acl(
    object_name: str,
    drift: str,
    column: str | None,
    quality_publish_postgres: tuple[Any, str, CalendarQualityRoles, str, str],
) -> None:
    connection, schema, roles, migrator_password, runtime_password = quality_publish_postgres
    with connection.transaction(), connection.cursor() as cursor:
        if drift == "schema":
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO PUBLIC").format(sql.Identifier(schema))
            )
        elif drift == "table":
            cursor.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO PUBLIC").format(
                    sql.Identifier(schema), sql.Identifier(object_name)
                )
            )
        else:
            assert column is not None
            cursor.execute(
                sql.SQL("GRANT SELECT ({}) ON TABLE {}.{} TO PUBLIC").format(
                    sql.Identifier(column),
                    sql.Identifier(schema),
                    sql.Identifier(object_name),
                )
            )

    with pytest.raises(ValueError, match="clean preflight"):
        publish_calendar_quality(
            connection,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_roles WHERE rolname=ANY(%s)",
            (list(roles),),
        )
        assert cursor.fetchone()[0] == 0
        if drift == "schema":
            cursor.execute(
                "SELECT pg_catalog.has_schema_privilege('public', %s, 'USAGE')",
                (schema,),
            )
        elif drift == "table":
            cursor.execute(
                "SELECT pg_catalog.has_table_privilege('public', %s, 'SELECT')",
                (f'"{schema}"."{object_name}"',),
            )
        else:
            cursor.execute(
                "SELECT pg_catalog.has_column_privilege('public', %s, %s, 'SELECT')",
                (f'"{schema}"."{object_name}"', column),
            )
        assert cursor.fetchone()[0] is True


@pytest.fixture()
def sealed_quality_roles_postgres() -> Generator[
    tuple[Any, Any, Any, str, CalendarQualityRoles], None, None
]:
    """Exercise bootstrap-equivalent roles on a disposable schema."""

    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn, autocommit=True)
    except Exception as exc:
        pytest.fail(f"configured PostgreSQL fixture could not connect: {type(exc).__name__}")
    suffix = uuid4().hex
    schema = f"calendar_quality_drift_{suffix}"
    roles = CalendarQualityRoles(
        owner=f"cq_owner_{suffix[:48]}",
        migrator=f"cq_migrator_{suffix[:45]}",
        runtime=f"cq_runtime_{suffix[:45]}",
        reader=f"cq_reader_{suffix[:46]}",
    )
    migrator_password = f"migrator_{suffix}"
    runtime_password = f"runtime_{suffix}"
    admin_schema: Any = None
    migrator: Any = None
    runtime: Any = None
    isolation_verified = False
    try:
        with admin.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor)
            isolation_verified = True
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            for role in (roles.owner, roles.migrator, roles.runtime, roles.reader):
                login = role in {roles.migrator, roles.runtime}
                statement = sql.SQL(
                    "CREATE ROLE {} {} NOINHERIT NOSUPERUSER NOCREATEDB "
                    "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
                ).format(
                    sql.Identifier(role),
                    sql.SQL("LOGIN" if login else "NOLOGIN"),
                )
                if role == roles.migrator:
                    statement += sql.SQL(" PASSWORD {} ").format(sql.Literal(migrator_password))
                elif role == roles.runtime:
                    statement += sql.SQL(" PASSWORD {} ").format(sql.Literal(runtime_password))
                cursor.execute(statement)
        admin_schema = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with admin_schema.transaction(), admin_schema.cursor() as cursor:
            _assert_isolated_quality_test_database(cursor, schema=schema)
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(admin_schema)
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(roles.owner)
                )
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT ON TABLE {}.data_worker_schema_migrations TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(roles.owner))
            )
            cursor.execute(
                sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE, ADMIN FALSE").format(
                    sql.Identifier(roles.owner), sql.Identifier(roles.migrator)
                )
            )
        migrator = psycopg.connect(
            dsn,
            user=roles.migrator,
            password=migrator_password,
            options=f'-c search_path="{schema}"',
        )
        with migrator.transaction(), migrator.cursor() as cursor:
            _assert_isolated_quality_test_database(
                cursor,
                schema=schema,
                expected_identity=(roles.migrator, roles.migrator),
                allow_migrator_pre_set_role=True,
            )
        _apply_calendar_quality_for_test(migrator, schema=schema, roles=roles)
        _seal_calendar_quality_for_test(admin_schema, schema=schema, roles=roles)
        runtime = psycopg.connect(
            dsn,
            user=roles.runtime,
            password=runtime_password,
            options=f'-c search_path="{schema}"',
        )
        with runtime.transaction(), runtime.cursor() as cursor:
            _assert_isolated_quality_test_database(
                cursor,
                schema=schema,
                expected_identity=(roles.runtime, roles.runtime),
            )
        yield admin_schema, migrator, runtime, schema, roles
    finally:
        cleanup_errors: list[str] = []
        for connection in (runtime, migrator, admin_schema):
            if connection is not None:
                try:
                    connection.close()
                except BaseException as exc:
                    cleanup_errors.append(f"connection close: {type(exc).__name__}")
        try:
            with admin.cursor() as cursor:
                if isolation_verified:
                    cursor.execute(
                        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                    )
        except BaseException as exc:
            cleanup_errors.append(f"schema drop: {type(exc).__name__}")
        for role in (roles.migrator, roles.runtime, roles.reader, roles.owner):
            try:
                with admin.cursor() as cursor:
                    if isolation_verified:
                        cursor.execute(
                            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                        )
            except BaseException as exc:
                cleanup_errors.append(f"role drop: {role}:{type(exc).__name__}")
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname=%s",
                    (schema,),
                )
                if cursor.fetchone() is not None:
                    cleanup_errors.append(f"schema leftover: {schema}")
                cursor.execute(
                    "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
                    ([roles.owner, roles.migrator, roles.runtime, roles.reader],),
                )
                leftovers = [str(row[0]) for row in cursor.fetchall()]
                if leftovers:
                    cleanup_errors.append(f"role leftovers: {','.join(leftovers)}")
        except BaseException as exc:
            cleanup_errors.append(f"cleanup assertion: {type(exc).__name__}")
        try:
            admin.close()
        except BaseException as exc:
            cleanup_errors.append(f"admin close: {type(exc).__name__}")
        if cleanup_errors:
            pytest.fail("; ".join(cleanup_errors))


def test_sealed_roles_support_runtime_and_reject_admin_impersonation_and_writes(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, runtime, schema, roles = sealed_quality_roles_postgres
    verify_calendar_quality_runtime(runtime, schema=schema, roles=roles)
    repository = PostgresCalendarQualityRepository(runtime, schema=schema, roles=roles)
    assessment = assess_calendar_quality(
        operation_id="quality-role-runtime",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    persisted = repository.persist_assessment(assessment)
    assert persisted.disposition == "CREATED"

    with admin.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'INSERT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'UPDATE'), "
            "pg_catalog.has_table_privilege(%s, %s, 'REFERENCES')",
            (
                roles.runtime,
                f'"{schema}".calendar_quality_assessments',
                roles.runtime,
                f'"{schema}".calendar_quality_assessments',
                roles.runtime,
                f'"{schema}".calendar_quality_assessments',
                roles.runtime,
                f'"{schema}".calendar_quality_assessments',
            ),
        )
        assert tuple(cursor.fetchone()) == (True, True, False, False)
        cursor.execute(
            "SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'INSERT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'UPDATE'), "
            "pg_catalog.has_table_privilege(%s, %s, 'DELETE'), "
            "pg_catalog.has_table_privilege(%s, %s, 'TRUNCATE'), "
            "pg_catalog.has_table_privilege(%s, %s, 'REFERENCES'), "
            "pg_catalog.has_table_privilege(%s, %s, 'TRIGGER'), "
            "pg_catalog.has_table_privilege(%s, %s, 'MAINTAIN')",
            tuple(
                value
                for _privilege in (
                    "SELECT",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "TRUNCATE",
                    "REFERENCES",
                    "TRIGGER",
                    "MAINTAIN",
                )
                for value in (roles.owner, f'"{schema}".calendar_quality_assessments')
            ),
        )
        assert tuple(cursor.fetchone()) == (True, True, True, True, True, True, True, True)

    with (
        pytest.raises(errors.InsufficientPrivilege),
        runtime.transaction(),
        runtime.cursor() as cursor,
    ):
        cursor.execute("SELECT assessment_id FROM calendar_quality_assessments FOR KEY SHARE")

    with runtime.transaction(), runtime.cursor() as cursor:
        cursor.execute("SELECT SESSION_USER, CURRENT_USER")
        assert tuple(cursor.fetchone()) == (roles.runtime, roles.runtime)

    with admin.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.has_schema_privilege(%s, %s, 'USAGE'), "
            "pg_catalog.has_schema_privilege(%s, %s, 'CREATE')",
            (roles.runtime, schema, roles.runtime, schema),
        )
        assert tuple(cursor.fetchone()) == (True, False)
        cursor.execute(
            "SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'INSERT'), "
            "pg_catalog.has_table_privilege(%s, %s, 'UPDATE')",
            (
                roles.reader,
                f'"{schema}".calendar_quality_assessments',
                roles.reader,
                f'"{schema}".calendar_quality_assessments',
                roles.reader,
                f'"{schema}".calendar_quality_assessments',
            ),
        )
        assert tuple(cursor.fetchone()) == (True, False, False)
        cursor.execute(
            "SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT')",
            (roles.reader, f'"{schema}".official_calendar_scan_runs'),
        )
        assert cursor.fetchone()[0] is False
        cursor.execute(
            "SELECT member.rolname, granted.rolname, m.inherit_option, "
            "m.set_option, m.admin_option "
            "FROM pg_catalog.pg_auth_members AS m "
            "JOIN pg_catalog.pg_roles AS member ON member.oid=m.member "
            "JOIN pg_catalog.pg_roles AS granted ON granted.oid=m.roleid "
            "WHERE member.rolname = ANY(%s) OR granted.rolname = ANY(%s)",
            ([roles.owner, roles.migrator, roles.runtime, roles.reader],) * 2,
        )
        assert cursor.fetchall() == []

    for statement in (
        sql.SQL("UPDATE {}.calendar_quality_assessments SET operation_id='tampered'").format(
            sql.Identifier(schema)
        ),
        sql.SQL("DELETE FROM {}.calendar_quality_assessments").format(sql.Identifier(schema)),
        sql.SQL("TRUNCATE {}.calendar_quality_audit").format(sql.Identifier(schema)),
        sql.SQL("CREATE TABLE {}.calendar_quality_forbidden (id integer)").format(
            sql.Identifier(schema)
        ),
        sql.SQL("SELECT * FROM {}.data_worker_schema_migrations").format(sql.Identifier(schema)),
    ):
        with (
            pytest.raises(errors.InsufficientPrivilege),
            runtime.transaction(),
            runtime.cursor() as cursor,
        ):
            cursor.execute(statement)

    with (
        pytest.raises(ValueError, match="database role is invalid"),
        admin.transaction(),
        admin.cursor() as cursor,
    ):
        cursor.execute(f'SET LOCAL ROLE "{roles.runtime}"')
        verify_calendar_quality_runtime(admin, schema=schema, roles=roles)


def test_runtime_context_keeps_permanent_relations_ahead_of_pg_temp(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, runtime, schema, roles = sealed_quality_roles_postgres
    with runtime.transaction(), runtime.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE calendar_quality_assessments (sentinel text)")
        cursor.execute("CREATE TEMP TABLE official_calendar_snapshots (sentinel text)")

    verify_calendar_quality_runtime(runtime, schema=schema, roles=roles)
    with runtime.transaction(), runtime.cursor() as cursor:
        prepare_calendar_quality_runtime_context(
            cursor,
            schema=schema,
            expected_role=roles.runtime,
        )
        cursor.execute("SELECT current_setting('search_path')")
        assert str(cursor.fetchone()[0]).replace(" ", "") == (f'"{schema}",pg_catalog,pg_temp')
        cursor.execute(
            "SELECT to_regclass('calendar_quality_assessments') = to_regclass(%s), "
            "to_regclass('official_calendar_snapshots') = to_regclass(%s)",
            (
                f'"{schema}".calendar_quality_assessments',
                f'"{schema}".official_calendar_snapshots',
            ),
        )
        assert tuple(cursor.fetchone()) == (True, True)

    repository = PostgresCalendarQualityRepository(runtime, schema=schema, roles=roles)
    assessment = assess_calendar_quality(
        operation_id="quality-runtime-temp-shadow",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    assert repository.persist_assessment(assessment).disposition == "CREATED"
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT count(*) FROM {}.calendar_quality_assessments").format(
                sql.Identifier(schema)
            )
        )
        assert cursor.fetchone()[0] == 1


@pytest.mark.parametrize("drift", ("security_definer", "function_config"))
def test_sealed_publish_rejects_function_execution_semantic_drift(
    drift: str,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, _runtime, schema, roles = sealed_quality_roles_postgres
    with admin.transaction(), admin.cursor() as cursor:
        statement = (
            "SECURITY DEFINER" if drift == "security_definer" else "SET statement_timeout = '5s'"
        )
        cursor.execute(
            sql.SQL("ALTER FUNCTION {}.calendar_quality_history_immutable() {}").format(
                sql.Identifier(schema),
                sql.SQL(statement),
            )
        )

    with pytest.raises(ValueError, match="immutable function mismatch"):
        publish_calendar_quality(
            admin,
            schema=schema,
            roles=roles,
            migrator_password="must-not-rotate",
            runtime_password="must-not-rotate",
        )


def test_reader_verifier_pins_search_path_behind_permanent_schema(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, _runtime, schema, roles = sealed_quality_roles_postgres
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE calendar_quality_assessments (sentinel text)")
        cursor.execute(f'SET LOCAL SESSION AUTHORIZATION "{roles.reader}"')
        verify_calendar_quality_reader(admin, schema=schema, roles=roles)


def test_reader_verifier_rejects_reader_column_acl_on_shared_complement(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    admin, _migrator, _runtime, schema, roles = sealed_quality_roles_postgres
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT (id) ON TABLE {}.tasks TO {}").format(
                sql.Identifier(schema), sql.Identifier(roles.reader)
            )
        )
        cursor.execute(f'SET LOCAL SESSION AUTHORIZATION "{roles.reader}"')
        with pytest.raises(ValueError, match="schema complement role column ACL drift"):
            verify_calendar_quality_reader(admin, schema=schema, roles=roles)


def test_v5_migration_is_explicit_repeatable_and_immutable(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version FROM data_worker_schema_migrations ORDER BY version")
        assert [int(row[0]) for row in cursor.fetchall()] == [1, 2, 3, 4, 5]
    repository.initialize()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_assessments")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM pg_proc AS p "
            "JOIN pg_namespace AS n ON n.oid=p.pronamespace "
            "WHERE n.nspname=current_schema() AND p.proname='calendar_quality_no_truncate'"
        )
        assert cursor.fetchone()[0] == 1

    with (
        pytest.raises(Exception, match="immutable"),
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO calendar_quality_assessments "
            "(assessment_id, operation_id, operation_key_hash, content_fingerprint, exchange, "
            "calendar_year, status, coverage_level, detected_at, available_at, source_count, "
            "missing_date_count, conflict_date_count, confirmed_days_json) "
            "VALUES (%s, 'truncate', %s, %s, 'BJ', 2026, 'MISSING_COVERAGE', "
            "'INDETERMINATE', %s, %s, 0, 0, 0, '[]')",
            (uuid4(), b"c" * 32, b"d" * 32, _AVAILABLE, _AVAILABLE),
        )
        cursor.execute("TRUNCATE calendar_quality_audit")

    with (
        pytest.raises(Exception, match="immutable"),
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO calendar_quality_assessments "
            "(assessment_id, operation_id, operation_key_hash, content_fingerprint, exchange, "
            "calendar_year, status, coverage_level, detected_at, available_at, source_count, "
            "missing_date_count, conflict_date_count, confirmed_days_json) "
            "VALUES (%s, 'x', %s, %s, 'BJ', 2026, 'MISSING_COVERAGE', 'INDETERMINATE', "
            "%s, %s, 0, 0, 0, '[]')",
            (uuid4(), b"a" * 32, b"b" * 32, _AVAILABLE, _AVAILABLE),
        )
        cursor.execute("UPDATE calendar_quality_assessments SET operation_id='y'")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_assessments")
        assert cursor.fetchone()[0] == 0


def test_quality_catalog_has_exact_immutable_triggers_and_rejects_leaf_mutations(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    assessment = assess_calendar_quality(
        operation_id="quality-trigger-contract",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    repository.persist_assessment(assessment)

    tables = (
        "calendar_quality_assessments",
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_days",
        "calendar_quality_missing_dates",
        "calendar_quality_alerts",
        "calendar_quality_alert_sources",
        "calendar_quality_manual_overlays",
        "calendar_quality_audit",
    )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname, t.tgname, t.tgtype "
            "FROM pg_trigger AS t "
            "JOIN pg_class AS c ON c.oid=t.tgrelid "
            "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=current_schema() AND NOT t.tgisinternal "
            "AND position('calendar_quality_' IN t.tgname)=1"
        )
        actual = {(str(row[0]), str(row[1]), int(row[2])) for row in cursor.fetchall()}
    expected = {(table, f"{table}_immutable", 27) for table in tables} | {
        (table, f"{table}_no_truncate", 34) for table in tables
    }
    assert actual == expected

    with (
        pytest.raises(Exception, match="calendar quality history is immutable"),
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "DELETE FROM calendar_quality_audit WHERE assessment_id=%s",
            (assessment.assessment_id,),
        )
    with (
        pytest.raises(Exception, match="calendar quality history is immutable"),
        connection.transaction(),
        connection.cursor() as cursor,
    ):
        cursor.execute("TRUNCATE calendar_quality_audit")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_audit")
        assert cursor.fetchone()[0] == 1


def test_same_sources_different_operations_are_not_merged_and_conflicts_fail_closed(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    _source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path / "first")
    first = assess_calendar_quality(
        operation_id="quality-distinct-operation-1",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    second = assess_calendar_quality(
        operation_id="quality-distinct-operation-2",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    assert first.sources[0].content_fingerprint == second.sources[0].content_fingerprint
    repository.persist_assessment(first)
    repository.persist_assessment(second)

    _changed_source_id, changed_source, _result, _helpers = _seed_v4_source(
        connection,
        tmp_path / "second",
        run_id=uuid4(),
        delayed_cutoff=True,
    )
    conflict_first = assess_calendar_quality(
        operation_id="quality-content-conflict",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    conflict_second = assess_calendar_quality(
        operation_id="quality-content-conflict",
        exchange=changed_source.exchange,
        year=changed_source.year,
        detected_at=_AVAILABLE,
        sources=(changed_source,),
    )
    repository.persist_assessment(conflict_first)
    with pytest.raises(CalendarQualityOperationConflictError, match="conflicts"):
        repository.persist_assessment(conflict_second)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_assessments")
        assert cursor.fetchone()[0] == 3


def test_postgres_same_operation_with_different_detection_time_conflicts_without_children(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    _source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path)
    first = assess_calendar_quality(
        operation_id="quality-same-operation-different-time",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    second = assess_calendar_quality(
        operation_id="quality-same-operation-different-time",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE + timedelta(seconds=1),
        sources=(source,),
    )
    assert first.content_fingerprint != second.content_fingerprint
    repository.persist_assessment(first)
    tables = (
        "calendar_quality_assessments",
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_days",
        "calendar_quality_missing_dates",
        "calendar_quality_alerts",
        "calendar_quality_alert_sources",
        "calendar_quality_manual_overlays",
        "calendar_quality_audit",
    )
    with connection.transaction(), connection.cursor() as cursor:
        before: list[int] = []
        for table in tables:
            cursor.execute(f"SELECT count(*) FROM {table}")
            before.append(int(cursor.fetchone()[0]))
    with pytest.raises(CalendarQualityOperationConflictError, match="conflicts"):
        repository.persist_assessment(second)
    with connection.transaction(), connection.cursor() as cursor:
        after: list[int] = []
        for table in tables:
            cursor.execute(f"SELECT count(*) FROM {table}")
            after.append(int(cursor.fetchone()[0]))
    assert tuple(after) == tuple(before)


def test_manual_overlay_is_append_only_audited_idempotent_and_point_in_time_filtered(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    source_id, source, result, _helpers = _seed_v4_source(connection, tmp_path)
    assert result.raw_manifest_ref.capture_id != str(result.proof.manifest.capture_id)
    assessment = assess_calendar_quality(
        operation_id="quality-overlay-assessment",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    repository.persist_assessment(assessment)
    overlay_time = _AVAILABLE + timedelta(minutes=10)
    first_overlay = CalendarQualityOverlay(
        overlay_id=uuid4(),
        operation_id="quality-overlay-1",
        assessment_id=assessment.assessment_id,
        source_id=source_id,
        calendar_date=date(2026, 1, 1),
        decision="NON_TRADING",
        reason_code="OPERATOR_REVIEW",
        note="first",
        author="operator",
        available_at=overlay_time,
    )
    second_overlay = replace(
        first_overlay,
        overlay_id=uuid4(),
        operation_id="quality-overlay-2",
        decision="REVIEW",
        note="second",
    )
    assert repository.persist_manual_overlay(first_overlay).disposition == "CREATED"
    assert repository.persist_manual_overlay(first_overlay).disposition == "DUPLICATE"
    assert repository.persist_manual_overlay(second_overlay).disposition == "CREATED"
    assert repository.list_manual_overlays(assessment.assessment_id, _AVAILABLE) == ()
    visible = repository.list_manual_overlays(assessment.assessment_id, overlay_time)
    expected_overlays = tuple(
        sorted((first_overlay, second_overlay), key=lambda overlay: overlay.overlay_id.bytes)
    )
    assert [(item.operation_id, item.overlay_id) for item in visible] == [
        (overlay.operation_id, overlay.overlay_id) for overlay in expected_overlays
    ]
    collision_first = replace(
        first_overlay,
        overlay_id=uuid4(),
        operation_id="quality-overlay-delimiter-collision",
        note="A:B",
        author="C",
    )
    collision_second = replace(collision_first, overlay_id=uuid4(), note="A", author="B:C")
    assert repository.persist_manual_overlay(collision_first).disposition == "CREATED"
    with pytest.raises(CalendarQualityOverlayConflictError, match="conflicts"):
        repository.persist_manual_overlay(collision_second)

    for statement, parameters in (
        (
            "UPDATE official_calendar_snapshots SET authority='SZSE' WHERE snapshot_id=%s",
            (source_id,),
        ),
        ("DELETE FROM official_calendar_snapshots WHERE snapshot_id=%s", (source_id,)),
        (
            "UPDATE calendar_quality_manual_overlays SET note='changed' WHERE overlay_id=%s",
            (first_overlay.overlay_id,),
        ),
        (
            "DELETE FROM calendar_quality_manual_overlays WHERE overlay_id=%s",
            (first_overlay.overlay_id,),
        ),
    ):
        with (
            pytest.raises(Exception, match="immutable"),
            connection.transaction(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement, parameters)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT r.proof_sha256 FROM official_calendar_scan_runs r "
            "JOIN official_calendar_snapshots s ON s.run_id=r.run_id "
            "WHERE s.snapshot_id=%s",
            (source_id,),
        )
        assert bytes(cursor.fetchone()[0]).hex() == source.source_fingerprint
        cursor.execute("SELECT count(*) FROM calendar_quality_manual_overlays")
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            "SELECT count(*) FROM calendar_quality_audit WHERE assessment_id=%s",
            (assessment.assessment_id,),
        )
        assert cursor.fetchone()[0] == 4


def test_assessment_alert_and_evidence_links_round_trip_with_idempotency(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path)
    assessment = assess_calendar_quality(
        operation_id="quality-round-trip",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    created = repository.persist_assessment(assessment)
    duplicate = repository.persist_assessment(assessment)
    assert created.disposition == "CREATED"
    assert duplicate.disposition == "DUPLICATE"

    visible = repository.list_assessments(
        source.exchange, source.year, _AVAILABLE + timedelta(seconds=1)
    )
    assert len(visible) == 1
    round_tripped = visible[0]
    assert round_tripped.operation_id == assessment.operation_id
    assert round_tripped.sources[0].evidence_links == source.evidence_links
    assert all(alert.kind != "TEMPORARY_CLOSURE" for alert in round_tripped.alerts)

    before = repository.list_assessments(
        source.exchange, source.year, _AVAILABLE - timedelta(seconds=1)
    )
    assert before == ()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_alert_sources")
        assert cursor.fetchone()[0] == sum(len(alert.evidence_links) for alert in assessment.alerts)

    closure = CalendarClosureEvidence(
        source_id=source_id,
        closure_date=date(2026, 1, 1),
        evidence_ref="caller-closure",
        artifact_sha256="c" * 64,
        captured_at=source.captured_at,
        available_at=source.available_at,
    )
    forged_source = replace(source, closures=(closure,))
    forged_closure_assessment = assess_calendar_quality(
        operation_id="quality-caller-closure",
        exchange=source.exchange,
        year=source.year,
        detected_at=source.available_at,
        sources=(forged_source,),
    )
    with pytest.raises(CalendarQualityPersistenceError):
        repository.persist_assessment(forged_closure_assessment)


def test_repository_rejects_forged_complete_and_secondary_sources(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    _source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path)
    assessment = assess_calendar_quality(
        operation_id="quality-forged",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(source,),
    )
    forged = replace(
        assessment,
        status="COMPLETE",
        coverage_level="FINAL_YEAR",
        confirmed_through=date(2026, 12, 31),
    )
    with pytest.raises(CalendarQualityPersistenceError):
        repository.persist_assessment(forged)

    secondary = replace(source, source_kind="SECONDARY")
    secondary_assessment = assess_calendar_quality(
        operation_id="quality-secondary",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(secondary,),
    )
    with pytest.raises(CalendarQualityPersistenceError, match="source"):
        repository.persist_assessment(secondary_assessment)


@pytest.mark.parametrize("mutation", ("days", "evidence", "closure", "timestamp", "fingerprint"))
def test_repository_rebuilds_projection_from_v4_source_and_rejects_caller_mutations(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
    mutation: str,
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path)
    if mutation == "days":
        first_day = source.days[0]
        forged_source = replace(
            source,
            days=(
                replace(
                    first_day,
                    is_trading_day=not first_day.is_trading_day,
                    reason=None if not first_day.is_trading_day else "SPECIAL",
                ),
                *source.days[1:],
            ),
        )
    elif mutation == "evidence":
        first_link = source.evidence_links[0]
        forged_source = replace(
            source,
            evidence_links=(
                replace(first_link, artifact_sha256="0" * 64),
                *source.evidence_links[1:],
            ),
        )
    elif mutation == "closure":
        forged_source = replace(
            source,
            closures=(
                CalendarClosureEvidence(
                    source_id=source_id,
                    closure_date=date(2026, 1, 1),
                    evidence_ref="caller-closure",
                    artifact_sha256="c" * 64,
                    captured_at=source.captured_at,
                    available_at=source.available_at,
                ),
            ),
        )
    elif mutation == "timestamp":
        forged_source = replace(source, available_at=source.available_at - timedelta(seconds=1))
    else:
        forged_source = replace(source, source_fingerprint="0" * 64)
    forged_assessment = assess_calendar_quality(
        operation_id=f"quality-forged-{mutation}",
        exchange=source.exchange,
        year=source.year,
        detected_at=_AVAILABLE,
        sources=(forged_source,),
    )
    with pytest.raises(CalendarQualityPersistenceError):
        repository.persist_assessment(forged_assessment)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM calendar_quality_assessments")
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT count(*) FROM official_calendar_snapshots WHERE snapshot_id=%s", (source_id,)
        )
        assert cursor.fetchone()[0] == 1


def test_postgres_delayed_projection_uses_detected_at_for_visibility(
    tmp_path: Path,
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    _source_id, source, _result, _helpers = _seed_v4_source(connection, tmp_path)
    detected_at = _AVAILABLE
    assessment = assess_calendar_quality(
        operation_id="quality-delayed-postgres",
        exchange=source.exchange,
        year=source.year,
        detected_at=detected_at,
        sources=(source,),
    )
    assert assessment.available_at == detected_at
    assert all(alert.available_at == detected_at for alert in assessment.alerts)
    repository.persist_assessment(assessment)
    assert repository.list_assessments(source.exchange, source.year, detected_at) != ()
    assert (
        repository.list_assessments(
            source.exchange, source.year, detected_at - timedelta(microseconds=1)
        )
        == ()
    )


def test_postgres_rejects_v3_sparse_source_but_allows_zero_source_scope(
    sealed_quality_roles_postgres: tuple[Any, Any, Any, str, CalendarQualityRoles],
) -> None:
    connection, _migrator, runtime, _schema, roles = sealed_quality_roles_postgres
    repository = PostgresCalendarQualityRepository(runtime, schema=_schema, roles=roles)
    source_id = uuid4()
    _insert_snapshot_version(connection, source_id)
    sparse_assessment = assess_calendar_quality(
        operation_id="quality-v3-sparse-postgres",
        exchange="SH",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(_source(source_id),),
    )
    with pytest.raises(CalendarQualityPersistenceError, match="source"):
        repository.persist_assessment(sparse_assessment)
    zero_source_assessment = assess_calendar_quality(
        operation_id="quality-bj-zero-source-postgres",
        exchange="BJ",
        year=2026,
        detected_at=_AVAILABLE,
        sources=(),
    )
    assert repository.persist_assessment(zero_source_assessment).disposition == "CREATED"
