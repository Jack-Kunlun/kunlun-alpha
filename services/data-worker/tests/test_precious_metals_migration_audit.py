"""Qualified RED coverage for the P1-R07 migration safety contract."""

from __future__ import annotations

import hashlib
import importlib
import os
import threading
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest


def _migration_module():
    return importlib.import_module("data_worker.storage.migrations")


def test_migration_uses_one_packaged_canonical_sql_artifact() -> None:
    module = _migration_module()
    package_root = Path(module.__file__).parent
    canonical_path = package_root / "precious_metals_migration.sql"
    assert canonical_path.is_file(), "canonical migration SQL resource is missing"
    canonical = canonical_path.read_bytes()
    loader = getattr(module, "load_precious_metals_migration", None)
    assert callable(loader), "migration loader must read the package resource"
    assert loader() == canonical
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()
    assert "CREATE INDEX" not in source.upper()
    assert "CREATE TABLE IF NOT EXISTS" not in canonical.decode("utf-8").upper()
    assert hashlib.sha256(canonical).hexdigest()


def test_migration_contract_declares_ledger_and_shared_advisory_lock() -> None:
    module = _migration_module()
    canonical_path = Path(module.__file__).with_name("precious_metals_migration.sql")
    sql = canonical_path.read_text(encoding="utf-8").upper()
    assert "DATA_WORKER_SCHEMA_MIGRATIONS" in sql
    assert "KUNLUN-ALPHA.SCHEMA-MIGRATIONS" in sql
    assert "PG_ADVISORY_XACT_LOCK" in sql

    verify = getattr(module, "verify_precious_metals_schema", None)
    assert callable(verify), "migration must expose schema verification"


def test_installed_package_resource_contains_canonical_sql() -> None:
    resource = files("data_worker.storage").joinpath("precious_metals_migration.sql")
    assert resource.is_file()
    payload = resource.read_bytes()
    assert payload.startswith(b"-- Canonical additive P1-R07 fund schema")
    assert hashlib.sha256(payload).hexdigest()


def _create_base_schema(cursor) -> None:  # type: ignore[no-untyped-def]
    cursor.execute(
        """
        CREATE TABLE providers (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          capabilities TEXT NOT NULL
        );
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
        CREATE TABLE data_versions (
          id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          date DATE NOT NULL,
          checksum TEXT NOT NULL
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


def _constraint_name(cursor, table: str, constraint_type: str, needle: str) -> str:
    """Return a task-owned constraint name for an isolated-schema mutation."""

    cursor.execute(
        """
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = %s::regclass
           AND contype = %s
           AND pg_get_constraintdef(oid) ILIKE %s
        """,
        (table, constraint_type, f"%{needle}%"),
    )
    row = cursor.fetchone()
    assert row is not None, (table, constraint_type, needle)
    return str(row[0])


@pytest.fixture()
def migration_pg():  # type: ignore[no-untyped-def]
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg = pytest.importorskip("psycopg")
    try:
        connection = psycopg.connect(dsn)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    schema = f"task7_migration_{uuid4().hex}"
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
            cursor.execute(f'SET search_path TO "{schema}"')
            _create_base_schema(cursor)
        yield connection, schema
    finally:
        connection.rollback()
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        with psycopg.connect(dsn) as verifier, verifier.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
            assert cursor.fetchone() is None
        connection.close()


def test_live_migration_creates_checksum_ledger_and_is_idempotent(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name, checksum FROM data_worker_schema_migrations")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1
        assert rows[0][1] == "precious_metals_migration"
        canonical = Path(module.__file__).with_name("precious_metals_migration.sql").read_bytes()
        assert rows[0][2] == hashlib.sha256(canonical).hexdigest()
        cursor.execute(
            "SELECT data_type, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_name = 'fund_nav_observations' AND column_name = 'value'"
        )
        data_type, precision, scale = cursor.fetchone()
        assert data_type == "numeric"
        assert (precision, scale) == (30, 12)


def test_live_migration_rejects_untracked_partial_fund_schema(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("CREATE TABLE fund_nav_observations (record_id TEXT PRIMARY KEY)")
    with pytest.raises(ValueError, match="ledger|partial|drift|schema"):
        module.apply_precious_metals_migration(connection)


@pytest.mark.parametrize("rogue_table", ("fund_rogue", "data_worker_rogue"))
def test_live_migration_rejects_extra_task_owned_table_and_preserves_ledger(
    migration_pg, rogue_table: str
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name, checksum FROM data_worker_schema_migrations")
        ledger_before = cursor.fetchall()
        cursor.execute(f'CREATE TABLE "{rogue_table}" (id TEXT)')
    with pytest.raises(ValueError, match="table|drift|schema"):
        module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name, checksum FROM data_worker_schema_migrations")
        assert cursor.fetchall() == ledger_before
        cursor.execute("SELECT to_regclass(%s)", (rogue_table,))
        assert cursor.fetchone()[0] == rogue_table


def test_live_migration_rejects_rogue_column_and_checksum_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE fund_nav_observations ADD COLUMN rogue TEXT")
    with pytest.raises(Exception, match="drift|rogue|schema"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_checksum_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE data_worker_schema_migrations SET checksum = %s",
            ("0" * 64,),
        )
    with pytest.raises(ValueError, match="checksum|name|ledger"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rolls_back_when_canonical_ddl_fails(migration_pg, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    canonical = module.load_precious_metals_migration()
    monkeypatch.setattr(
        module,
        "load_precious_metals_migration",
        lambda: canonical + b"\nCREATE TABLE deliberately_invalid (id TEXT;\n",
    )
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises((ValueError, psycopg.Error)):
        module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('data_worker_schema_migrations'), "
            "to_regclass('fund_observation_evidence')"
        )
        ledger, evidence = cursor.fetchone()
        assert ledger is None
        assert evidence is None


def test_live_migration_rejects_constraint_index_and_default_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("DROP INDEX idx_fund_nav_key")
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)

    # Restore the index is intentionally out of scope: this transaction is
    # expected to be rolled back by the fixture's schema teardown.


def test_live_migration_rejects_fk_and_default_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'fund_nav_observations'::regclass "
            "AND contype = 'f' LIMIT 1"
        )
        fk = cursor.fetchone()
        assert fk is not None
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{fk[0]}"')
    with pytest.raises(ValueError, match="constraint|foreign|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_nullable_or_numeric_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE fund_nav_observations ALTER COLUMN semantic_key DROP NOT NULL")
        cursor.execute("ALTER TABLE fund_inav_observations ALTER COLUMN value TYPE NUMERIC(20, 8)")
    with pytest.raises(ValueError, match="drift|numeric"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_default_and_unique_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE fund_observation_evidence ALTER COLUMN item_ordinal SET DEFAULT 0"
        )
    with pytest.raises(ValueError, match="default|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_concurrent_connections_have_one_ledger_winner(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, schema = migration_pg
    dsn = os.environ["KUNLUN_TEST_POSTGRES_DSN"]
    psycopg = pytest.importorskip("psycopg")
    contender = psycopg.connect(dsn)
    try:
        with contender.transaction(), contender.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def run(connection_to_use) -> None:  # type: ignore[no-untyped-def]
            try:
                barrier.wait(timeout=10)
                module.apply_precious_metals_migration(connection_to_use)
            except BaseException as exc:  # pragma: no cover - assertion below
                errors.append(exc)

        first = threading.Thread(target=run, args=(connection,))
        second = threading.Thread(target=run, args=(contender,))
        first.start()
        second.start()
        first.join(timeout=20)
        second.join(timeout=20)
        assert not first.is_alive() and not second.is_alive()
        assert errors == []
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM data_worker_schema_migrations")
            assert cursor.fetchone()[0] == 1
    finally:
        contender.rollback()
        contender.close()


def test_live_migration_fails_closed_when_base_schema_is_incomplete(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE tasks DROP COLUMN lease_token")
    with pytest.raises(Exception, match="base|tasks|schema"):
        module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('fund_nav_observations'), "
            "to_regclass('data_worker_schema_migrations')"
        )
        fund_table, ledger = cursor.fetchone()
        assert fund_table is None
        assert ledger is None


def test_live_migration_rejects_index_order_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key ON fund_nav_observations (reference_date, unified_code)"
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_index_method_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key ON fund_nav_observations USING hash (unified_code)"
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_index_predicate_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key "
            "ON fund_nav_observations (unified_code, reference_date) "
            "WHERE unified_code IS NOT NULL"
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_index_opclass_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key "
            "ON fund_nav_observations (unified_code text_pattern_ops, reference_date)"
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_same_name_custom_opclass(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            'CREATE OPERATOR CLASS "text_ops" FOR TYPE text USING btree AS '
            "STORAGE text, "
            "OPERATOR 1 < (text, text), "
            "OPERATOR 2 <= (text, text), "
            "OPERATOR 3 = (text, text), "
            "OPERATOR 4 >= (text, text), "
            "OPERATOR 5 > (text, text), "
            "FUNCTION 1 bttextcmp(text, text)"
        )
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key "
            f'ON fund_nav_observations (unified_code "{schema}".text_ops, reference_date)'
        )
    with pytest.raises(ValueError, match="index|opclass|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_index_collation_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("CREATE COLLATION \"task5_rogue_collation\" (provider = libc, locale = 'C')")
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key "
            "ON fund_nav_observations "
            '(unified_code COLLATE "task5_rogue_collation", reference_date)'
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_column_and_index_rogue_collation(
    migration_pg,
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name, checksum FROM data_worker_schema_migrations")
        ledger_before = cursor.fetchall()
        cursor.execute(
            "CREATE COLLATION \"task5_rogue_column_collation\" (provider = libc, locale = 'C')"
        )
        cursor.execute("DROP INDEX idx_fund_nav_key")
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            'ALTER COLUMN unified_code TYPE TEXT COLLATE "task5_rogue_column_collation" '
            "USING unified_code"
        )
        cursor.execute(
            "CREATE INDEX idx_fund_nav_key ON fund_nav_observations (unified_code, reference_date)"
        )
    with pytest.raises(ValueError, match="column|collation|drift"):
        module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name, checksum FROM data_worker_schema_migrations")
        assert cursor.fetchall() == ledger_before


def test_live_migration_rejects_extra_task_owned_index(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "CREATE INDEX task_owned_extra_index ON fund_nav_observations (unified_code)"
        )
    with pytest.raises(ValueError, match="index|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_primary_key_name_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        primary_key = _constraint_name(cursor, "fund_nav_observations", "p", "PRIMARY KEY")
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{primary_key}"')
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            "ADD CONSTRAINT task_owned_extra_pk PRIMARY KEY (record_id)"
        )
    with pytest.raises(ValueError, match="constraint|primary|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_missing_primary_key(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        primary_key = _constraint_name(cursor, "fund_nav_observations", "p", "PRIMARY KEY")
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{primary_key}"')
    with pytest.raises(ValueError, match="constraint|primary|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_extra_unique_constraint(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            "ADD CONSTRAINT task_owned_extra_unique UNIQUE (unified_code, reference_date)"
        )
    with pytest.raises(ValueError, match="constraint|unique|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_unique_constraint_name_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        unique = _constraint_name(
            cursor,
            "fund_observation_evidence",
            "u",
            "raw_capture_id",
        )
        cursor.execute(f'ALTER TABLE fund_observation_evidence DROP CONSTRAINT "{unique}"')
        cursor.execute(
            "ALTER TABLE fund_observation_evidence "
            "ADD CONSTRAINT task_owned_extra_unique UNIQUE (raw_capture_id, item_ordinal)"
        )
    with pytest.raises(ValueError, match="constraint|unique|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_unique_nulls_not_distinct_drift(
    migration_pg,
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        unique = _constraint_name(
            cursor,
            "fund_observation_evidence",
            "u",
            "raw_capture_id",
        )
        cursor.execute(f'ALTER TABLE fund_observation_evidence DROP CONSTRAINT "{unique}"')
        cursor.execute(
            "ALTER TABLE fund_observation_evidence "
            f'ADD CONSTRAINT "{unique}" UNIQUE NULLS NOT DISTINCT '
            "(raw_capture_id, item_ordinal)"
        )
    with pytest.raises(ValueError, match="index|constraint|unique|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_extra_check_constraint(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            "ADD CONSTRAINT task_owned_extra_check CHECK (value >= 0)"
        )
    with pytest.raises(ValueError, match="constraint|check|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_same_name_check_no_inherit_drift(
    migration_pg,
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        check = _constraint_name(cursor, "fund_nav_observations", "c", "value")
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{check}"')
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            f'ADD CONSTRAINT "{check}" CHECK (value >= 0) NO INHERIT'
        )
    with pytest.raises(ValueError, match="constraint|check|inherit|drift"):
        module.apply_precious_metals_migration(connection)


@pytest.mark.parametrize(
    ("table", "needle"),
    (
        ("fund_nav_observations", "value"),
        ("fund_inav_observations", "value"),
        ("fund_fee_observations", "management_fee_rate"),
    ),
)
def test_live_migration_rejects_missing_non_negative_check(
    migration_pg,
    table: str,
    needle: str,
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        check = _constraint_name(cursor, table, "c", needle)
        cursor.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT "{check}"')
    with pytest.raises(ValueError, match="constraint|check|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_extra_foreign_key(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE fund_nav_observations "
            "ADD CONSTRAINT task_owned_extra_fk "
            "FOREIGN KEY (evidence_id) REFERENCES fund_observation_evidence(record_id)"
        )
    with pytest.raises(ValueError, match="foreign|constraint|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_foreign_key_action_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        foreign_key = _constraint_name(cursor, "fund_nav_observations", "f", "evidence_id")
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{foreign_key}"')
        cursor.execute(
            f'ALTER TABLE fund_nav_observations ADD CONSTRAINT "{foreign_key}" '
            "FOREIGN KEY (evidence_id) REFERENCES fund_observation_evidence(record_id) "
            "ON DELETE CASCADE"
        )
    with pytest.raises(ValueError, match="foreign|constraint|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_foreign_key_name_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        foreign_key = _constraint_name(cursor, "fund_nav_observations", "f", "evidence_id")
        cursor.execute(f'ALTER TABLE fund_nav_observations DROP CONSTRAINT "{foreign_key}"')
        cursor.execute(
            "ALTER TABLE fund_nav_observations ADD CONSTRAINT task_owned_extra_fk "
            "FOREIGN KEY (evidence_id) REFERENCES fund_observation_evidence(record_id)"
        )
    with pytest.raises(ValueError, match="foreign|constraint|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_rejects_cross_schema_same_name_foreign_key(
    migration_pg,
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    cross_schema = f"task5_cross_schema_{uuid4().hex}"
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{cross_schema}"')
            cursor.execute(
                f'CREATE TABLE "{cross_schema}"."fund_observation_evidence" '
                "(record_id TEXT PRIMARY KEY)"
            )
            constraint = _constraint_name(
                cursor,
                "fund_metadata_observations",
                "f",
                "fund_observation_evidence",
            )
            cursor.execute(f'ALTER TABLE fund_metadata_observations DROP CONSTRAINT "{constraint}"')
            cursor.execute(
                f'ALTER TABLE fund_metadata_observations ADD CONSTRAINT "{constraint}" '
                f'FOREIGN KEY (evidence_id) REFERENCES "{cross_schema}".'
                '"fund_observation_evidence" '
                "(record_id)"
            )
        with pytest.raises(ValueError, match="constraint|drift"):
            module.apply_precious_metals_migration(connection)
    finally:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{cross_schema}" CASCADE')


def test_live_migration_rejects_column_order_drift(migration_pg) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    module.apply_precious_metals_migration(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("ALTER TABLE fund_nav_observations DROP COLUMN semantic_key")
        cursor.execute("ALTER TABLE fund_nav_observations ADD COLUMN semantic_key TEXT NOT NULL")
    with pytest.raises(ValueError, match="column|drift"):
        module.apply_precious_metals_migration(connection)


def test_live_migration_verifies_schema_before_ledger_and_rolls_back_on_failure(
    migration_pg, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    module = _migration_module()
    connection, _schema = migration_pg
    observed_ledger_rows: list[int] = []

    def fail_schema_verification(cursor) -> None:  # type: ignore[no-untyped-def]
        cursor.execute("SELECT count(*) FROM data_worker_schema_migrations")
        observed_ledger_rows.append(int(cursor.fetchone()[0]))
        raise ValueError("instrumented schema verification failure")

    monkeypatch.setattr(module, "_verify_fund_schema", fail_schema_verification)
    with pytest.raises(ValueError, match="instrumented"):
        module.apply_precious_metals_migration(connection)
    assert observed_ledger_rows == [0]
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regclass('data_worker_schema_migrations'), "
            "to_regclass('fund_observation_evidence')"
        )
        assert cursor.fetchone() == (None, None)
