"""PostgreSQL isolation and ACL coverage for the private instrument provider."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from data_worker.jobs.instruments.postgres_repository import (
    InstrumentMasterPersistenceError,
    PostgresInstrumentMasterRepository,
)
from data_worker.storage.migrations import (
    INSTRUMENT_MASTER_PROVIDER_LOCK_KEY,
    InstrumentMasterProviderRoles,
    apply_data_worker_migrations,
    apply_instrument_master_provider_migration,
    verify_instrument_master_provider_schema,
)
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.pq import TransactionStatus


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _login_dsn(base_dsn: str, role: str) -> str:
    return make_conninfo(
        base_dsn,
        user=role,
        password=f"instrument-master-test-password-{role}",
    )


@contextmanager
def _third_party_role(admin: Any) -> Generator[str, None, None]:
    role = f"im_third_party_{uuid4().hex}"
    identifier = _identifier(role)
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {identifier} NOLOGIN NOINHERIT")
    try:
        yield role
    finally:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f"DROP OWNED BY {identifier}")
            cursor.execute(f"DROP ROLE IF EXISTS {identifier}")


def _base_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
          lease_token TEXT, lease_expires_at TIMESTAMPTZ, next_run_at TIMESTAMPTZ,
          last_error_category TEXT, last_error_detail JSONB,
          dead_letter_detail JSONB, created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE checkpoints (
          task_id TEXT PRIMARY KEY, cursor TEXT, state JSONB,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE quality_events (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, unified_code TEXT,
          date DATE, detail TEXT
        );
        CREATE TABLE instrument_master_revisions (
          revision_id UUID PRIMARY KEY, instrument_id TEXT NOT NULL,
          marker TEXT NOT NULL
        );
        CREATE INDEX instrument_master_revisions_legacy_marker_idx
          ON instrument_master_revisions (marker);
        INSERT INTO instrument_master_revisions
          (revision_id, instrument_id, marker)
        VALUES ('00000000-0000-4000-8000-000000000001', 'legacy', 'untouched');
        """
    )


def _cleanup_provider_fixture(
    admin: Any,
    schemas: tuple[str, ...],
    roles: tuple[str, ...],
) -> None:
    errors: list[BaseException] = []

    def run(statement: str, parameters: tuple[object, ...] = ()) -> None:
        try:
            admin.rollback()
            with admin.transaction(), admin.cursor() as cursor:
                cursor.execute(statement, parameters)
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
        role_identifier = _identifier(role)
        if role_exists(role):
            run(f"DROP OWNED BY {role_identifier}")
            run(f"DROP ROLE IF EXISTS {role_identifier}")

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
def provider_pg(tmp_path: Path) -> Generator[dict[str, Any], None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")

    admin = psycopg.connect(dsn)
    suffix = uuid4().hex
    legacy_schema = f"im_legacy_{suffix}"
    provider_schema = f"im_provider_{suffix}"
    roles = InstrumentMasterProviderRoles(
        owner=f"im_owner_{suffix}",
        migrator=f"im_migrator_{suffix}",
        runtime=f"im_runtime_{suffix}",
        reader=f"im_reader_{suffix}",
    )
    legacy = _identifier(legacy_schema)
    provider = _identifier(provider_schema)
    role_identifiers = {
        field: _identifier(getattr(roles, field))
        for field in ("owner", "migrator", "runtime", "reader")
    }
    connection: Any = None
    setup_connection: Any = None
    runtime_connection: Any = None
    reader_connection: Any = None
    try:
        with admin.transaction(), admin.cursor() as raw_cursor:
            cursor = cast(Any, raw_cursor)
            cursor.execute(f"CREATE ROLE {role_identifiers['owner']} NOLOGIN NOINHERIT")
            cursor.execute(f"CREATE ROLE {role_identifiers['migrator']} LOGIN NOINHERIT")
            cursor.execute(f"CREATE ROLE {role_identifiers['runtime']} LOGIN NOINHERIT")
            cursor.execute(f"CREATE ROLE {role_identifiers['reader']} NOLOGIN NOINHERIT")
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(roles.migrator),
                    sql.Literal(f"instrument-master-test-password-{roles.migrator}"),
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(roles.runtime),
                    sql.Literal(f"instrument-master-test-password-{roles.runtime}"),
                )
            )
            cursor.execute(
                f"GRANT {role_identifiers['owner']} TO {role_identifiers['migrator']} "
                "WITH INHERIT FALSE, SET TRUE, ADMIN FALSE"
            )
        with admin.transaction(), admin.cursor() as raw_cursor:
            cursor = cast(Any, raw_cursor)
            cursor.execute(f"CREATE SCHEMA {legacy}")
            cursor.execute(f"CREATE SCHEMA {provider} AUTHORIZATION {role_identifiers['owner']}")
            cursor.execute(f"ALTER SCHEMA {provider} OWNER TO {role_identifiers['owner']}")

        setup_connection = psycopg.connect(dsn, options=f"-c search_path={legacy}")
        with setup_connection.transaction(), setup_connection.cursor() as raw_cursor:
            _base_schema(raw_cursor)
        apply_data_worker_migrations(setup_connection)
        with admin.transaction(), admin.cursor() as raw_cursor:
            cursor = cast(Any, raw_cursor)
            cursor.execute(f"GRANT USAGE ON SCHEMA {legacy} TO {role_identifiers['migrator']}")
            cursor.execute(
                f"GRANT SELECT ON TABLE {legacy}.data_worker_schema_migrations "
                f"TO {role_identifiers['migrator']}"
            )
        setup_connection.close()
        setup_connection = None
        connection = psycopg.connect(
            _login_dsn(dsn, roles.migrator),
            options=f"-c search_path={legacy}",
        )
        apply_instrument_master_provider_migration(
            connection,
            schema=provider_schema,
            roles=roles,
            legacy_schema=legacy_schema,
        )
        # The connection is left idle after the migration transaction and may
        # be used by the test for read-only legacy assertions.
        yield {
            "dsn": dsn,
            "legacy_schema": legacy_schema,
            "provider_schema": provider_schema,
            "roles": roles,
            "admin": admin,
            "connection": connection,
        }
    finally:
        cleanup_errors: list[BaseException] = []
        for candidate in (reader_connection, runtime_connection, connection, setup_connection):
            if candidate is not None:
                try:
                    candidate.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
        try:
            _cleanup_provider_fixture(
                admin,
                (provider_schema, legacy_schema),
                (roles.runtime, roles.reader, roles.migrator, roles.owner),
            )
        except BaseException as exc:
            cleanup_errors.append(exc)
        if cleanup_errors:
            raise cleanup_errors[0]


def test_provider_isolated_from_legacy_and_shared_migration(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    legacy = _identifier(provider_pg["legacy_schema"])
    provider = _identifier(provider_pg["provider_schema"])
    with admin.transaction(), admin.cursor() as raw_cursor:
        raw_cursor.execute(f"SELECT marker FROM {legacy}.instrument_master_revisions")
        assert raw_cursor.fetchone() == ("untouched",)
        raw_cursor.execute(
            f"SELECT version, name FROM {legacy}.data_worker_schema_migrations ORDER BY version"
        )
        assert [row[0] for row in raw_cursor.fetchall()] == [1, 2, 3, 4]
        raw_cursor.execute(
            "SELECT count(*) FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relname = 'tushare_instrument_master_revisions'",
            (provider_pg["provider_schema"],),
        )
        assert raw_cursor.fetchone() == (1,)
        raw_cursor.execute(
            f"SELECT count(*) FROM {provider}.tushare_instrument_master_schema_migrations"
        )
        assert raw_cursor.fetchone() == (1,)
        raw_cursor.execute(
            f"SELECT version FROM {provider}.tushare_instrument_master_schema_migrations"
        )
        assert raw_cursor.fetchone() == (1,)


def test_repository_rejects_shared_admin_identity_before_use(
    provider_pg: dict[str, Any],
) -> None:
    repository = PostgresInstrumentMasterRepository(
        provider_pg["admin"],
        schema=provider_pg["provider_schema"],
        runtime_role=provider_pg["roles"].runtime,
        provider_roles=provider_pg["roles"],
    )
    with pytest.raises(InstrumentMasterPersistenceError, match="persistence failed"):
        repository.verify_schema()


def test_provider_verifier_restores_transaction_lifecycle(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    roles = provider_pg["roles"]
    assert admin.info.transaction_status == TransactionStatus.IDLE
    verify_instrument_master_provider_schema(
        admin,
        schema=provider_pg["provider_schema"],
        roles=roles,
    )
    assert admin.info.transaction_status == TransactionStatus.IDLE
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute("SELECT 1")
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=roles,
        )
        assert admin.info.transaction_status == TransactionStatus.INTRANS
    assert admin.info.transaction_status == TransactionStatus.IDLE


def test_dedicated_login_roles_can_migrate_and_runtime_read_only(
    provider_pg: dict[str, Any],
) -> None:
    dsn = provider_pg["dsn"]
    roles = provider_pg["roles"]
    legacy = _identifier(provider_pg["legacy_schema"])
    provider = _identifier(provider_pg["provider_schema"])

    migrator: Any = psycopg.connect(_login_dsn(dsn, roles.migrator))
    try:
        apply_instrument_master_provider_migration(
            migrator,
            schema=provider_pg["provider_schema"],
            roles=roles,
            legacy_schema=provider_pg["legacy_schema"],
        )
        with migrator.transaction(), migrator.cursor() as cursor:
            cursor.execute("SELECT SESSION_USER, CURRENT_USER")
            assert cursor.fetchone() == (roles.migrator, roles.migrator)
            cursor.execute(f"SELECT version FROM {legacy}.data_worker_schema_migrations")
            assert [row[0] for row in cursor.fetchall()] == [1, 2, 3, 4]
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            migrator.transaction(),
            migrator.cursor() as cursor,
        ):
            cursor.execute(f"UPDATE {legacy}.data_worker_schema_migrations SET version = version")
    finally:
        migrator.rollback()
        migrator.close()

    runtime: Any = psycopg.connect(
        _login_dsn(dsn, roles.runtime),
        options=f"-c search_path={provider}",
    )
    try:
        repository = PostgresInstrumentMasterRepository(
            runtime,
            schema=provider_pg["provider_schema"],
            runtime_role=roles.runtime,
            provider_roles=roles,
        )
        repository.verify_schema()
        with runtime.transaction(), runtime.cursor() as cursor:
            cursor.execute("SELECT SESSION_USER, CURRENT_USER")
            assert cursor.fetchone() == (roles.runtime, roles.runtime)
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            runtime.transaction(),
            runtime.cursor() as cursor,
        ):
            cursor.execute(
                f"UPDATE {provider}.tushare_instrument_master_heads SET updated_at = updated_at"
            )
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            runtime.transaction(),
            runtime.cursor() as cursor,
        ):
            cursor.execute(f"CREATE TABLE {provider}.login_probe (id INTEGER)")
    finally:
        runtime.rollback()
        runtime.close()


def test_provider_migration_rejects_admin_session_with_migrator_set_role(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    roles = provider_pg["roles"]
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'SET ROLE "{roles.migrator}"')
        admin.commit()

        with pytest.raises(ValueError, match="requires migrator role"):
            apply_instrument_master_provider_migration(
                admin,
                schema=provider_pg["provider_schema"],
                roles=roles,
                legacy_schema=provider_pg["legacy_schema"],
            )
    finally:
        with admin.cursor() as cursor:
            cursor.execute("RESET ROLE")
        admin.commit()


def test_provider_migration_serializes_same_schema_startup(
    provider_pg: dict[str, Any],
) -> None:
    roles = provider_pg["roles"]
    dsn = provider_pg["dsn"]
    schema = provider_pg["provider_schema"]
    first = psycopg.connect(_login_dsn(dsn, roles.migrator))
    second = psycopg.connect(_login_dsn(dsn, roles.migrator))
    try:
        with first.transaction(), first.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(pg_catalog.hashtext(%s))",
                (f"{INSTRUMENT_MASTER_PROVIDER_LOCK_KEY}:{schema}",),
            )
            with second.transaction(), second.cursor() as second_cursor:
                second_cursor.execute("SET statement_timeout = '250ms'")
            with pytest.raises(psycopg.errors.QueryCanceled):
                apply_instrument_master_provider_migration(
                    second,
                    schema=schema,
                    roles=roles,
                    legacy_schema=provider_pg["legacy_schema"],
                )
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_provider_verifier_rejects_acl_drift(provider_pg: dict[str, Any]) -> None:
    admin = provider_pg["admin"]
    roles = provider_pg["roles"]
    provider = _identifier(provider_pg["provider_schema"])
    verify_instrument_master_provider_schema(
        admin,
        schema=provider_pg["provider_schema"],
        roles=roles,
    )
    with admin.transaction(), admin.cursor() as raw_cursor:
        raw_cursor.execute(
            f"GRANT DELETE ON {provider}.tushare_instrument_master_runs TO "
            f"{_identifier(roles.runtime)}"
        )
    with pytest.raises(ValueError, match="ACL"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=roles,
        )


def test_provider_verifier_rejects_third_party_schema_acl(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with _third_party_role(admin) as third_party:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f"GRANT USAGE ON SCHEMA {provider} TO {_identifier(third_party)}")
        with pytest.raises(ValueError, match="schema ACL"):
            verify_instrument_master_provider_schema(
                admin,
                schema=provider_pg["provider_schema"],
                roles=provider_pg["roles"],
            )


def test_provider_verifier_rejects_third_party_table_acl(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with _third_party_role(admin) as third_party:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(
                f"GRANT SELECT ON {provider}.tushare_instrument_master_runs "
                f"TO {_identifier(third_party)}"
            )
        with pytest.raises(ValueError, match="table .* ACL"):
            verify_instrument_master_provider_schema(
                admin,
                schema=provider_pg["provider_schema"],
                roles=provider_pg["roles"],
            )


def test_provider_verifier_rejects_third_party_function_acl(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with _third_party_role(admin) as third_party:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(
                f"GRANT EXECUTE ON FUNCTION {provider}."
                "tushare_instrument_master_publish_head(TEXT, UUID, TIMESTAMPTZ) "
                f"TO {_identifier(third_party)}"
            )
        with pytest.raises(ValueError, match="function .* ACL"):
            verify_instrument_master_provider_schema(
                admin,
                schema=provider_pg["provider_schema"],
                roles=provider_pg["roles"],
            )


def test_provider_verifier_rejects_third_party_default_table_acl(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    roles = provider_pg["roles"]
    with _third_party_role(admin) as third_party:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {_identifier(roles.owner)} "
                f"IN SCHEMA {provider} GRANT SELECT ON TABLES TO {_identifier(third_party)}"
            )
        with pytest.raises(ValueError, match="default ACL"):
            verify_instrument_master_provider_schema(
                admin,
                schema=provider_pg["provider_schema"],
                roles=roles,
            )


def test_provider_migration_rejects_extra_legacy_ledger_acl(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    connection = provider_pg["connection"]
    legacy = _identifier(provider_pg["legacy_schema"])
    roles = provider_pg["roles"]
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            f"GRANT UPDATE ON TABLE {legacy}.data_worker_schema_migrations "
            f"TO {_identifier(roles.migrator)}"
        )
    with pytest.raises(ValueError, match="legacy ledger ACL"):
        apply_instrument_master_provider_migration(
            connection,
            schema=provider_pg["provider_schema"],
            roles=roles,
            legacy_schema=provider_pg["legacy_schema"],
        )


def test_existing_provider_ledger_drift_is_not_repaired(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    connection = provider_pg["connection"]
    provider = _identifier(provider_pg["provider_schema"])
    roles = provider_pg["roles"]

    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE OR REPLACE FUNCTION {provider}.tushare_instrument_master_history_immutable()
            RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = pg_catalog, pg_temp
            AS $$
            BEGIN
                RETURN NEW;
            END;
            $$
            """
        )

    with pytest.raises(ValueError, match="drift"):
        apply_instrument_master_provider_migration(
            connection,
            schema=provider_pg["provider_schema"],
            roles=roles,
            legacy_schema=provider_pg["legacy_schema"],
        )


def test_provider_verifier_rejects_unexpected_role_membership(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    roles = provider_pg["roles"]
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(f"GRANT {_identifier(roles.owner)} TO {_identifier(roles.runtime)}")

    with pytest.raises(ValueError, match="role"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=roles,
        )


def test_provider_verifier_requires_noninherited_settable_migrator_membership(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    roles = provider_pg["roles"]
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            "SELECT m.inherit_option, m.set_option, m.admin_option "
            "FROM pg_catalog.pg_auth_members AS m "
            "JOIN pg_catalog.pg_roles AS member ON member.oid = m.member "
            "JOIN pg_catalog.pg_roles AS granted ON granted.oid = m.roleid "
            "WHERE member.rolname = %s AND granted.rolname = %s",
            (roles.migrator, roles.owner),
        )
        assert cursor.fetchone() == (False, True, False)


def test_provider_verifier_rejects_deceptive_publish_head_body(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    owner = _identifier(provider_pg["roles"].owner)
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(f"SET LOCAL ROLE {owner}")
        cursor.execute(
            f"""
            CREATE OR REPLACE FUNCTION {provider}.tushare_instrument_master_publish_head(
                p_unified_code TEXT,
                p_revision_id UUID,
                p_ordering_at TIMESTAMPTZ
            )
            RETURNS BOOLEAN
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, pg_temp
            AS $$
            DECLARE
                marker TEXT := '{provider_pg["provider_schema"]}.tushare_instrument_master_heads '
                    'tushare_instrument_master_revisions ordering_at';
            BEGIN
                marker := marker || p_unified_code || p_revision_id::TEXT || p_ordering_at::TEXT;
                RETURN FALSE;
            END;
            $$
            """
        )
    with pytest.raises(ValueError, match="function tushare_instrument_master_publish_head"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=provider_pg["roles"],
        )


def test_provider_verifier_rejects_column_contract_drift(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {provider}.tushare_instrument_master_runs "
            "ALTER COLUMN reason_code SET DEFAULT 'deceptive'"
        )
    with pytest.raises(ValueError, match="columns|default"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=provider_pg["roles"],
        )


def test_provider_verifier_rejects_constraint_definition_drift(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {provider}.tushare_instrument_master_runs "
            "DROP CONSTRAINT tushare_instrument_master_runs_count_ck"
        )
        cursor.execute(
            f"ALTER TABLE {provider}.tushare_instrument_master_runs "
            "ADD CONSTRAINT tushare_instrument_master_runs_count_ck CHECK (record_count > 0)"
        )
    with pytest.raises(ValueError, match="constraint"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=provider_pg["roles"],
        )


def test_provider_verifier_rejects_index_definition_drift(
    provider_pg: dict[str, Any],
) -> None:
    admin = provider_pg["admin"]
    provider = _identifier(provider_pg["provider_schema"])
    with admin.transaction(), admin.cursor() as cursor:
        cursor.execute(f"DROP INDEX {provider}.tushare_instrument_master_revisions_pit_idx")
        cursor.execute(
            f"CREATE INDEX tushare_instrument_master_revisions_pit_idx "
            f"ON {provider}.tushare_instrument_master_revisions (available_at, unified_code)"
        )
    with pytest.raises(ValueError, match="index"):
        verify_instrument_master_provider_schema(
            admin,
            schema=provider_pg["provider_schema"],
            roles=provider_pg["roles"],
        )
