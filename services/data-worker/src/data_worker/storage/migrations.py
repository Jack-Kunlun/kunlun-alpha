"""Verified additive PostgreSQL migration for precious-metals fund storage.

The SQL lives only in the packaged ``precious_metals_migration.sql`` resource.
This module owns the transaction, advisory lock, base-schema preflight, ledger
checksum, and exact post-apply schema verification.  It never rewrites the
P1-R05 version-1 tables.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from importlib.resources import files
from typing import TYPE_CHECKING, Any, NamedTuple, cast

from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from psycopg import Connection


MIGRATION_VERSION = 1
MIGRATION_NAME = "precious_metals_migration"
MIGRATION_LOCK_KEY = "kunlun-alpha.schema-migrations"
_RESOURCE_NAME = "precious_metals_migration.sql"
SEAT_MIGRATION_VERSION = 2
SEAT_MIGRATION_NAME = "seat_collection_migration"
_PACKAGE_RESOURCE_ROOT = "data_worker"
_SEAT_RESOURCE_PACKAGE = "data_worker.jobs.seats"
_SEAT_RESOURCE_NAME = "seat_collection_migration.sql"
CALENDAR_SNAPSHOT_MIGRATION_VERSION = 3
CALENDAR_SNAPSHOT_MIGRATION_NAME = "calendar_snapshot_migration"
_CALENDAR_RESOURCE_PATH = ("jobs", "calendars")
_CALENDAR_RESOURCE_NAME = "calendar_snapshot_migration.sql"
OFFICIAL_CALENDAR_MIGRATION_VERSION = 4
OFFICIAL_CALENDAR_MIGRATION_NAME = "official_calendar_migration"
_OFFICIAL_CALENDAR_RESOURCE_PATH = ("jobs", "calendars")
_OFFICIAL_CALENDAR_RESOURCE_NAME = "official_calendar_migration.sql"
CALENDAR_QUALITY_MIGRATION_VERSION = 5
CALENDAR_QUALITY_MIGRATION_NAME = "calendar_quality_migration"
_CALENDAR_QUALITY_RESOURCE_PATH = ("jobs", "calendars")
_CALENDAR_QUALITY_RESOURCE_NAME = "calendar_quality_migration.sql"
CALENDAR_QUALITY_SCHEMA = "kunlun"
CALENDAR_QUALITY_OWNER_ROLE = "kunlun_cq_owner"
CALENDAR_QUALITY_MIGRATOR_ROLE = "kunlun_cq_migrator"
CALENDAR_QUALITY_RUNTIME_ROLE = "kunlun_cq_runtime"
CALENDAR_QUALITY_READER_ROLE = "kunlun_cq_reader"
CALENDAR_QUALITY_LOCK_KEY = "kunlun-alpha.calendar-quality"
class CalendarQualityRoles(NamedTuple):
    """Database roles required by the calendar-quality V5 boundary."""

    owner: str = CALENDAR_QUALITY_OWNER_ROLE
    migrator: str = CALENDAR_QUALITY_MIGRATOR_ROLE
    runtime: str = CALENDAR_QUALITY_RUNTIME_ROLE
    reader: str = CALENDAR_QUALITY_READER_ROLE


class CalendarQualityPublishDisposition(str, Enum):
    """Terminal result of the administrator-owned first-install operation."""

    PUBLISHED = "PUBLISHED"
    ALREADY_SEALED = "ALREADY_SEALED"


@dataclass(frozen=True, slots=True)
class CalendarQualityPublishResult:
    """Safe, non-sensitive result returned by the publish boundary."""

    disposition: CalendarQualityPublishDisposition


_BASE_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "tasks": {
        "id": ("text", False),
        "kind": ("text", False),
        "status": ("text", False),
        "attempts": ("integer", False),
        "max_attempts": ("integer", False),
        "lease_token": ("text", True),
        "lease_expires_at": ("timestamp with time zone", True),
        "next_run_at": ("timestamp with time zone", True),
        "last_error_category": ("text", True),
        "last_error_detail": ("jsonb", True),
        "dead_letter_detail": ("jsonb", True),
        "created_at": ("timestamp with time zone", False),
        "updated_at": ("timestamp with time zone", False),
    },
    "checkpoints": {
        "task_id": ("text", False),
        "cursor": ("text", True),
        "state": ("jsonb", True),
        "updated_at": ("timestamp with time zone", False),
    },
    "quality_events": {
        "id": ("text", False),
        "kind": ("text", False),
        "unified_code": ("text", True),
        "date": ("date", True),
        "detail": ("text", True),
    },
}

_FUND_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "data_worker_schema_migrations": {
        "version": ("integer", False),
        "name": ("text", False),
        "checksum": ("text", False),
        "applied_at": ("timestamp with time zone", False),
    },
    "fund_observation_evidence": {
        "record_id": ("text", False),
        "raw_capture_id": ("text", False),
        "raw_object_id": ("text", False),
        "checksum": ("text", False),
        "source": ("text", False),
        "source_revision": ("text", True),
        "schema_version": ("text", False),
        "normalizer_version": ("text", False),
        "payload_digest": ("text", False),
        "item_ordinal": ("integer", False),
        "event_time": ("timestamp with time zone", True),
        "publish_time": ("timestamp with time zone", True),
        "ingest_time": ("timestamp with time zone", True),
        "available_time": ("timestamp with time zone", True),
        "processing_time": ("timestamp with time zone", True),
    },
    "fund_logical_observations": {
        "observation_id": ("text", False),
        "kind": ("text", False),
        "source": ("text", False),
        "source_revision": ("text", True),
        "semantic_key": ("text", False),
        "content_digest": ("text", False),
        "payload": ("jsonb", False),
        "created_at": ("timestamp with time zone", False),
    },
    "fund_observation_evidence_links": {
        "observation_id": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_metadata_observations": {
        "record_id": ("text", False),
        "observation_id": ("text", False),
        "unified_code": ("text", False),
        "payload": ("jsonb", False),
        "semantic_key": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_nav_observations": {
        "record_id": ("text", False),
        "observation_id": ("text", False),
        "unified_code": ("text", False),
        "reference_date": ("date", False),
        "value": ("numeric", False),
        "semantic_key": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_inav_observations": {
        "record_id": ("text", False),
        "observation_id": ("text", False),
        "unified_code": ("text", False),
        "reference_date": ("date", False),
        "value": ("numeric", False),
        "semantic_key": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_benchmark_observations": {
        "record_id": ("text", False),
        "observation_id": ("text", False),
        "unified_code": ("text", False),
        "reference_date": ("date", False),
        "benchmark": ("text", False),
        "semantic_key": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_fee_observations": {
        "record_id": ("text", False),
        "observation_id": ("text", False),
        "unified_code": ("text", False),
        "reference_date": ("date", False),
        "management_fee_rate": ("numeric", False),
        "semantic_key": ("text", False),
        "evidence_id": ("text", False),
    },
    "fund_rejections": {
        "record_id": ("text", False),
        "kind": ("text", False),
        "reason": ("text", False),
        "payload": ("jsonb", False),
        "raw_capture_id": ("text", False),
    },
    "fund_quality_events": {
        "event_id": ("text", False),
        "kind": ("text", False),
        "semantic_key": ("text", False),
        "detail": ("text", False),
        "created_at": ("timestamp with time zone", False),
    },
    "fund_quality_event_evidence": {
        "quality_event_id": ("text", False),
        "evidence_id": ("text", False),
    },
}

_FUND_TABLES = tuple(_FUND_COLUMNS)

_NUMERIC_TYPMOD = 1_966_096
_CURRENT_SCHEMA_SENTINEL = "<current_schema>"


class _ConstraintSpec(NamedTuple):
    table: str
    name: str
    contype: str
    columns: tuple[str, ...]
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    match_type: str | None = None
    update_action: str | None = None
    delete_action: str | None = None
    expression: str | None = None
    deferrable: bool = False
    deferred: bool = False
    validated: bool = True
    referenced_schema: str | None = None
    no_inherit: bool = False


class _IndexSpec(NamedTuple):
    table: str
    name: str
    access_method: str
    keys: tuple[str, ...]
    included: tuple[str, ...] = ()
    unique: bool = False
    predicate: str | None = None
    options: tuple[str, ...] = ()
    key_options: tuple[int, ...] = ()
    key_opclasses: tuple[tuple[str, str, str], ...] = ()
    key_collations: tuple[int, ...] = ()
    owner: str | None = None
    nulls_not_distinct: bool = False


def _primary_key(table: str, name: str, *columns: str) -> _ConstraintSpec:
    return _ConstraintSpec(table, name, "p", columns, no_inherit=True)


def _foreign_key(
    table: str,
    name: str,
    column: str,
    referenced_table: str,
) -> _ConstraintSpec:
    referenced_column = {
        "fund_logical_observations": "observation_id",
        "fund_quality_events": "event_id",
    }.get(referenced_table, "record_id")
    return _ConstraintSpec(
        table,
        name,
        "f",
        (column,),
        referenced_table,
        (referenced_column,),
        "s",
        "a",
        "a",
        referenced_schema=_CURRENT_SCHEMA_SENTINEL,
        no_inherit=True,
    )


_EXPECTED_CONSTRAINTS = (
    _primary_key("data_worker_schema_migrations", "data_worker_schema_migrations_pkey", "version"),
    _primary_key("fund_observation_evidence", "fund_observation_evidence_pkey", "record_id"),
    _ConstraintSpec(
        "fund_observation_evidence",
        "fund_observation_evidence_raw_capture_id_item_ordinal_key",
        "u",
        ("raw_capture_id", "item_ordinal"),
        no_inherit=True,
    ),
    _ConstraintSpec(
        "fund_observation_evidence",
        "fund_observation_evidence_item_ordinal_check",
        "c",
        ("item_ordinal",),
        expression="(item_ordinal >= 0)",
    ),
    _primary_key("fund_logical_observations", "fund_logical_observations_pkey", "observation_id"),
    _ConstraintSpec(
        "fund_logical_observations",
        "fund_logical_observations_kind_source_semantic_key_source_r_key",
        "u",
        ("kind", "source", "semantic_key", "source_revision", "content_digest"),
        no_inherit=True,
    ),
    _primary_key(
        "fund_observation_evidence_links",
        "fund_observation_evidence_links_pkey",
        "observation_id",
        "evidence_id",
    ),
    _primary_key("fund_metadata_observations", "fund_metadata_observations_pkey", "record_id"),
    _primary_key("fund_nav_observations", "fund_nav_observations_pkey", "record_id"),
    _ConstraintSpec(
        "fund_nav_observations",
        "fund_nav_observations_value_check",
        "c",
        ("value",),
        expression="(value >= (0)::numeric)",
    ),
    _primary_key("fund_inav_observations", "fund_inav_observations_pkey", "record_id"),
    _ConstraintSpec(
        "fund_inav_observations",
        "fund_inav_observations_value_check",
        "c",
        ("value",),
        expression="(value >= (0)::numeric)",
    ),
    _primary_key("fund_benchmark_observations", "fund_benchmark_observations_pkey", "record_id"),
    _primary_key("fund_fee_observations", "fund_fee_observations_pkey", "record_id"),
    _ConstraintSpec(
        "fund_fee_observations",
        "fund_fee_observations_management_fee_rate_check",
        "c",
        ("management_fee_rate",),
        expression="(management_fee_rate >= (0)::numeric)",
    ),
    _primary_key("fund_rejections", "fund_rejections_pkey", "record_id"),
    _primary_key("fund_quality_events", "fund_quality_events_pkey", "event_id"),
    _primary_key(
        "fund_quality_event_evidence",
        "fund_quality_event_evidence_pkey",
        "quality_event_id",
        "evidence_id",
    ),
    _foreign_key(
        "fund_observation_evidence_links",
        "fund_observation_evidence_links_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_observation_evidence_links",
        "fund_observation_evidence_links_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_metadata_observations",
        "fund_metadata_observations_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_metadata_observations",
        "fund_metadata_observations_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_metadata_observations",
        "fund_metadata_observations_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_nav_observations",
        "fund_nav_observations_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_nav_observations",
        "fund_nav_observations_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_nav_observations",
        "fund_nav_observations_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_inav_observations",
        "fund_inav_observations_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_inav_observations",
        "fund_inav_observations_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_inav_observations",
        "fund_inav_observations_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_benchmark_observations",
        "fund_benchmark_observations_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_benchmark_observations",
        "fund_benchmark_observations_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_benchmark_observations",
        "fund_benchmark_observations_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_fee_observations",
        "fund_fee_observations_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_fee_observations",
        "fund_fee_observations_observation_id_fkey",
        "observation_id",
        "fund_logical_observations",
    ),
    _foreign_key(
        "fund_fee_observations",
        "fund_fee_observations_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_rejections",
        "fund_rejections_record_id_fkey",
        "record_id",
        "fund_observation_evidence",
    ),
    _foreign_key(
        "fund_quality_event_evidence",
        "fund_quality_event_evidence_quality_event_id_fkey",
        "quality_event_id",
        "fund_quality_events",
    ),
    _foreign_key(
        "fund_quality_event_evidence",
        "fund_quality_event_evidence_evidence_id_fkey",
        "evidence_id",
        "fund_observation_evidence",
    ),
)

_DEFAULT_BTREE_OPCLASSES: dict[str, tuple[str, str, str]] = {
    "text": ("pg_catalog", "text_ops", "btree"),
    "integer": ("pg_catalog", "int4_ops", "btree"),
}


def _constraint_index_spec(spec: _ConstraintSpec) -> _IndexSpec:
    return _IndexSpec(
        spec.table,
        spec.name,
        "btree",
        spec.columns,
        unique=True,
        key_opclasses=tuple(
            _DEFAULT_BTREE_OPCLASSES[_FUND_COLUMNS[spec.table][column][0]]
            for column in spec.columns
        ),
        owner=spec.name,
    )


_EXPECTED_CONSTRAINT_INDEXES = tuple(
    _constraint_index_spec(spec) for spec in _EXPECTED_CONSTRAINTS if spec.contype in {"p", "u"}
)

_EXPECTED_INDEXES = (
    _IndexSpec(
        "fund_observation_evidence",
        "idx_fund_evidence_source_time",
        "btree",
        ("source", "ingest_time", "record_id"),
        key_opclasses=(
            ("pg_catalog", "text_ops", "btree"),
            ("pg_catalog", "timestamptz_ops", "btree"),
            ("pg_catalog", "text_ops", "btree"),
        ),
    ),
    _IndexSpec(
        "fund_logical_observations",
        "idx_fund_logical_semantic",
        "btree",
        ("kind", "source", "semantic_key"),
        key_opclasses=(
            ("pg_catalog", "text_ops", "btree"),
            ("pg_catalog", "text_ops", "btree"),
            ("pg_catalog", "text_ops", "btree"),
        ),
    ),
    _IndexSpec(
        "fund_nav_observations",
        "idx_fund_nav_key",
        "btree",
        ("unified_code", "reference_date"),
        key_opclasses=(("pg_catalog", "text_ops", "btree"), ("pg_catalog", "date_ops", "btree")),
    ),
    _IndexSpec(
        "fund_inav_observations",
        "idx_fund_inav_key",
        "btree",
        ("unified_code", "reference_date"),
        key_opclasses=(("pg_catalog", "text_ops", "btree"), ("pg_catalog", "date_ops", "btree")),
    ),
    _IndexSpec(
        "fund_benchmark_observations",
        "idx_fund_benchmark_key",
        "btree",
        ("unified_code", "reference_date"),
        key_opclasses=(("pg_catalog", "text_ops", "btree"), ("pg_catalog", "date_ops", "btree")),
    ),
    _IndexSpec(
        "fund_fee_observations",
        "idx_fund_fee_key",
        "btree",
        ("unified_code", "reference_date"),
        key_opclasses=(("pg_catalog", "text_ops", "btree"), ("pg_catalog", "date_ops", "btree")),
    ),
)


def load_precious_metals_migration() -> bytes:
    """Read the canonical SQL bytes from the installed package resource."""

    return files("data_worker.storage").joinpath(_RESOURCE_NAME).read_bytes()


def _migration_checksum() -> str:
    return hashlib.sha256(load_precious_metals_migration()).hexdigest()


def load_seat_collection_migration() -> bytes:
    """Read the canonical seat SQL from the installed package resource."""

    return files(_SEAT_RESOURCE_PACKAGE).joinpath(_SEAT_RESOURCE_NAME).read_bytes()


def _seat_migration_checksum() -> str:
    return hashlib.sha256(load_seat_collection_migration()).hexdigest()


def load_calendar_snapshot_migration() -> bytes:
    """Read the canonical calendar snapshot SQL from the package resource."""

    return (
        files(_PACKAGE_RESOURCE_ROOT)
        .joinpath(*_CALENDAR_RESOURCE_PATH, _CALENDAR_RESOURCE_NAME)
        .read_bytes()
    )


def _calendar_snapshot_migration_checksum() -> str:
    return hashlib.sha256(load_calendar_snapshot_migration()).hexdigest()


def load_official_calendar_migration() -> bytes:
    """Read the canonical immutable official-calendar V4 SQL resource."""

    return (
        files(_PACKAGE_RESOURCE_ROOT)
        .joinpath(*_OFFICIAL_CALENDAR_RESOURCE_PATH, _OFFICIAL_CALENDAR_RESOURCE_NAME)
        .read_bytes()
    )


def _official_calendar_migration_checksum() -> str:
    return hashlib.sha256(load_official_calendar_migration()).hexdigest()


def load_calendar_quality_migration() -> bytes:
    """Read the additive calendar-quality V5 SQL resource."""

    return (
        files(_PACKAGE_RESOURCE_ROOT)
        .joinpath(*_CALENDAR_QUALITY_RESOURCE_PATH, _CALENDAR_QUALITY_RESOURCE_NAME)
        .read_bytes()
    )


def _calendar_quality_migration_checksum() -> str:
    return hashlib.sha256(load_calendar_quality_migration()).hexdigest()


# Kept as a compatibility export for existing callers; the source of truth is
# still the packaged bytes above, never a duplicated SQL literal.
PRECIOUS_METALS_MIGRATION = load_precious_metals_migration().decode("utf-8")
CALENDAR_SNAPSHOT_MIGRATION = load_calendar_snapshot_migration().decode("utf-8")
OFFICIAL_CALENDAR_MIGRATION = load_official_calendar_migration().decode("utf-8")
CALENDAR_QUALITY_MIGRATION = load_calendar_quality_migration().decode("utf-8")


_CATALOG_CONTRACT_CHECKSUM = "42351a268e5d5e8139d4c8c4f7ab7b0c361d462954052fb19a88aa22dddb282c"


def _catalog_column_rows(
    cursor: Any,
    tables: tuple[str, ...],
) -> list[tuple[object, ...]]:
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, a.attnum, a.attname, "
        "format_type(a.atttypid, -1), a.atttypmod, NOT a.attnotnull, "
        "a.attcollation, t.typcollation, "
        "pg_get_expr(d.adbin, d.adrelid) "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "JOIN pg_attribute AS a ON a.attrelid = c.oid "
        "JOIN pg_type AS t ON t.oid = a.atttypid "
        "LEFT JOIN pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        f"AND c.relname IN ({placeholders}) "
        "AND a.attnum > 0 AND NOT a.attisdropped",
        tables,
    )
    return cast(list[tuple[object, ...]], cursor.fetchall())


def _verify_columns(cursor: Any, expected: dict[str, dict[str, tuple[str, bool]]]) -> None:
    tables = tuple(expected)
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, a.attnum, a.attname, "
        "format_type(a.atttypid, -1), a.atttypmod, NOT a.attnotnull, "
        "a.attcollation, t.typcollation, "
        "pg_get_expr(d.adbin, d.adrelid) "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "JOIN pg_attribute AS a ON a.attrelid = c.oid "
        "JOIN pg_type AS t ON t.oid = a.atttypid "
        "LEFT JOIN pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        f"AND c.relname IN ({placeholders}) "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY c.relname, a.attnum",
        tables,
    )
    rows = cast(list[tuple[object, ...]], cursor.fetchall())
    actual: dict[str, list[tuple[str, str, int, bool, int, int, object]]] = {}
    for row in rows:
        (
            table,
            _attnum,
            column,
            data_type,
            typmod,
            nullable,
            collation,
            type_collation,
            column_default,
        ) = row
        actual.setdefault(str(table), []).append(
            (
                str(column),
                str(data_type),
                int(str(typmod)),
                bool(nullable),
                int(str(collation)),
                int(str(type_collation)),
                column_default,
            )
        )
    for table, columns in expected.items():
        observed = actual.get(table)
        if observed is None:
            raise ValueError(f"required schema table is missing: {table}")
        expected_names = tuple(columns)
        observed_names = tuple(row[0] for row in observed)
        if observed_names != expected_names:
            raise ValueError(f"schema drift in {table}: unexpected columns")
        for index, (column, (data_type, nullable)) in enumerate(columns.items()):
            (
                observed_column,
                observed_type,
                observed_typmod,
                observed_nullable,
                observed_collation,
                expected_collation,
                column_default,
            ) = observed[index]
            expected_typmod = _NUMERIC_TYPMOD if data_type == "numeric" else -1
            if (
                observed_column != column
                or observed_type != data_type
                or observed_typmod != expected_typmod
                or observed_nullable != nullable
                or observed_collation != expected_collation
            ):
                raise ValueError(f"schema drift in {table}.{column}")
            if column_default is not None:
                raise ValueError(f"schema drift in {table}.{column} default")


def _task_owned_tables(cursor: Any) -> set[str]:
    """Enumerate task-owned tables without treating P1-R05 tables as drift."""

    cursor.execute(
        "SELECT c.relname "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        "AND (left(c.relname, 5) = 'fund_' OR left(c.relname, 12) = 'data_worker_')"
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _verify_task_owned_tables(cursor: Any) -> None:
    expected = set(_FUND_TABLES)
    actual = _task_owned_tables(cursor)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(
            f"schema drift in task-owned table set: missing={missing!r} extra={extra!r}"
        )


def _verify_base_schema(cursor: Any) -> None:
    _verify_columns(cursor, _BASE_COLUMNS)


def _int_vector(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if isinstance(value, (tuple, list)):
        items = cast(tuple[object, ...] | list[object], value)
        return tuple(int(str(item)) for item in items)
    text = str(value).strip().strip("{}[]")
    if not text:
        return ()
    return tuple(int(item) for item in text.replace(",", " ").split())


def _catalog_attribute_names(cursor: Any, tables: tuple[str, ...]) -> dict[str, dict[int, str]]:
    rows = _catalog_column_rows(cursor, tables)
    return {
        table: {int(str(row[1])): str(row[2]) for row in rows if str(row[0]) == table}
        for table in tables
    }


def _verify_constraint_specs(
    cursor: Any,
    tables: tuple[str, ...],
    expected_specs: tuple[_ConstraintSpec, ...],
    *,
    normalize_expressions: bool = False,
    drift_prefix: str = "schema drift",
) -> None:
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, con.conname, con.contype, con.conkey, con.confkey, "
        "rc.relname, rn.nspname, con.confmatchtype, con.confupdtype, con.confdeltype, "
        "con.condeferrable, con.condeferred, con.convalidated, con.connoinherit, "
        "pg_get_expr(con.conbin, con.conrelid) "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS c ON c.oid = con.conrelid "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_class AS rc ON rc.oid = con.confrelid "
        "LEFT JOIN pg_namespace AS rn ON rn.oid = rc.relnamespace "
        "WHERE n.nspname = current_schema() "
        f"AND c.relname IN ({placeholders})",
        tables,
    )
    rows = cursor.fetchall()
    attribute_names = _catalog_attribute_names(cursor, tables)
    actual: set[_ConstraintSpec] = set()
    for row in rows:
        (
            table,
            name,
            contype,
            conkey,
            confkey,
            referenced_table,
            referenced_schema,
            match_type,
            update_action,
            delete_action,
            deferrable,
            deferred,
            validated,
            no_inherit,
            expression,
        ) = row
        table_name = str(table)
        referenced_name = str(referenced_table) if referenced_table is not None else None
        referenced_schema_name = str(referenced_schema) if referenced_schema is not None else None
        columns = tuple(
            attribute_names[table_name].get(attnum, f"<attnum:{attnum}>")
            for attnum in _int_vector(conkey)
        )
        if referenced_name is None:
            referenced_columns: tuple[str, ...] = ()
        else:
            referenced_attributes = attribute_names.get(referenced_name, {})
            referenced_columns = tuple(
                referenced_attributes.get(attnum, f"<attnum:{attnum}>")
                for attnum in _int_vector(confkey)
            )
        actual.add(
            _ConstraintSpec(
                table_name,
                str(name),
                str(contype),
                columns,
                referenced_name,
                referenced_columns,
                str(match_type) if referenced_name is not None else None,
                str(update_action) if referenced_name is not None else None,
                str(delete_action) if referenced_name is not None else None,
                (
                    _canonical_catalog_expression(expression)
                    if normalize_expressions
                    else str(expression)
                    if expression is not None
                    else None
                ),
                bool(deferrable),
                bool(deferred),
                bool(validated),
                referenced_schema=referenced_schema_name,
                no_inherit=bool(no_inherit),
            )
        )
    cursor.execute("SELECT current_schema()")
    current_schema = str(cursor.fetchone()[0])
    expected = {
        spec._replace(referenced_schema=current_schema)
        if spec.referenced_schema == _CURRENT_SCHEMA_SENTINEL
        else spec
        for spec in expected_specs
    }
    missing = expected - actual
    extra = actual - expected
    if missing:
        item = sorted(missing, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"{drift_prefix}: missing constraint {item.table}.{item.name}")
    if extra:
        item = sorted(extra, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"{drift_prefix}: unexpected constraint {item.table}.{item.name}")


def _verify_constraints(cursor: Any) -> None:
    _verify_constraint_specs(cursor, _FUND_TABLES, _EXPECTED_CONSTRAINTS)


def _index_keys(
    cursor: Any,
    index_oid: int,
    table: str,
    key_vector: object,
    key_count: int,
    total_count: int,
    attribute_names: dict[str, dict[int, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    keys: list[str] = []
    for position, attnum in enumerate(_int_vector(key_vector), start=1):
        if attnum:
            keys.append(attribute_names[table].get(attnum, f"<attnum:{attnum}>"))
        else:
            cursor.execute(
                "SELECT pg_get_indexdef(%s, %s, true)",
                (index_oid, position),
            )
            expression = cursor.fetchone()[0]
            keys.append(f"<expression:{expression}>")
    if len(keys) != total_count:
        raise ValueError(f"schema drift in index on {table}: invalid key count")
    return tuple(keys[:key_count]), tuple(keys[key_count:])


def _catalog_attribute_type_collations(
    cursor: Any, tables: tuple[str, ...]
) -> dict[tuple[str, str], int]:
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, a.attname, t.typcollation "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "JOIN pg_attribute AS a ON a.attrelid = c.oid "
        "JOIN pg_type AS t ON t.oid = a.atttypid "
        "WHERE n.nspname = current_schema() "
        f"AND c.relname IN ({placeholders}) "
        "AND a.attnum > 0 AND NOT a.attisdropped",
        tables,
    )
    return {
        (str(table), str(column)): int(str(collation))
        for table, column, collation in cursor.fetchall()
    }


def _index_opclass_specs(
    cursor: Any, opclass_vector: object, key_count: int
) -> tuple[tuple[str, str, str], ...]:
    opclasses = _int_vector(opclass_vector)
    if len(opclasses) != key_count:
        raise ValueError("schema drift in index: invalid opclass count")
    specs: list[tuple[str, str, str]] = []
    for opclass_oid in opclasses:
        cursor.execute(
            "SELECT n.nspname, opc.opcname, am.amname "
            "FROM pg_opclass AS opc "
            "JOIN pg_namespace AS n ON n.oid = opc.opcnamespace "
            "JOIN pg_am AS am ON am.oid = opc.opcmethod "
            "WHERE opc.oid = %s",
            (opclass_oid,),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("schema drift in index: unknown opclass")
        specs.append((str(row[0]), str(row[1]), str(row[2])))
    return tuple(specs)


def _verify_index_specs(
    cursor: Any,
    tables: tuple[str, ...],
    expected_specs: tuple[_IndexSpec, ...],
    *,
    drift_prefix: str = "schema drift",
) -> None:
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, i.oid, i.relname, am.amname, ix.indisunique, "
        "ix.indnkeyatts, ix.indnatts, ix.indkey, ix.indoption, "
        "ix.indclass, ix.indcollation, "
        "owner.conname, ix.indnullsnotdistinct, "
        "pg_get_expr(ix.indpred, ix.indrelid), i.reloptions, ix.indisvalid, ix.indisready "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "JOIN pg_index AS ix ON ix.indrelid = c.oid "
        "JOIN pg_class AS i ON i.oid = ix.indexrelid "
        "JOIN pg_am AS am ON am.oid = i.relam "
        "LEFT JOIN pg_constraint AS owner "
        "ON owner.conindid = i.oid AND owner.contype IN ('p', 'u') "
        "WHERE n.nspname = current_schema() "
        f"AND c.relname IN ({placeholders}) ",
        tables,
    )
    rows = cursor.fetchall()
    attribute_names = _catalog_attribute_names(cursor, tables)
    actual: set[_IndexSpec] = set()
    for row in rows:
        (
            table,
            index_oid,
            name,
            access_method,
            unique,
            key_count,
            total_count,
            key_vector,
            key_options,
            opclass_vector,
            collation_vector,
            owner,
            nulls_not_distinct,
            predicate,
            options,
            valid,
            ready,
        ) = row
        if not bool(valid) or not bool(ready):
            raise ValueError(f"schema drift: invalid index {table}.{name}")
        keys, included = _index_keys(
            cursor,
            int(index_oid),
            str(table),
            key_vector,
            int(key_count),
            int(total_count),
            attribute_names,
        )
        key_count_int = int(key_count)
        opclass_specs = _index_opclass_specs(cursor, opclass_vector, key_count_int)
        collations = _int_vector(collation_vector)
        if len(collations) != key_count_int:
            raise ValueError(f"schema drift in index {table}.{name}: invalid collation count")
        actual.add(
            _IndexSpec(
                str(table),
                str(name),
                str(access_method),
                keys,
                included,
                bool(unique),
                str(predicate) if predicate is not None else None,
                tuple(str(option) for option in (options or ())),
                _int_vector(key_options),
                opclass_specs,
                collations,
                str(owner) if owner is not None else None,
                bool(nulls_not_distinct),
            )
        )
    attribute_collations = _catalog_attribute_type_collations(cursor, tables)
    expected = {
        spec._replace(
            key_options=(spec.key_options or (0,) * len(spec.keys)),
            key_opclasses=(spec.key_opclasses or ((),) * len(spec.keys)),
            key_collations=tuple(
                attribute_collations[(spec.table, column)] for column in spec.keys
            ),
        )
        for spec in expected_specs
    }
    missing = expected - actual
    extra = actual - expected
    if missing:
        item = sorted(missing, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"{drift_prefix}: missing index {item.table}.{item.name}")
    if extra:
        item = sorted(extra, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"{drift_prefix}: unexpected index {item.table}.{item.name}")


def _verify_indexes(cursor: Any) -> None:
    _verify_index_specs(
        cursor,
        _FUND_TABLES,
        (*_EXPECTED_INDEXES, *_EXPECTED_CONSTRAINT_INDEXES),
    )


def _verify_fund_schema(cursor: Any) -> None:
    if _migration_checksum() != _CATALOG_CONTRACT_CHECKSUM:
        raise ValueError("schema drift: catalog contract checksum mismatch")
    _verify_columns(cursor, _FUND_COLUMNS)
    _verify_constraints(cursor)
    _verify_indexes(cursor)


def verify_precious_metals_schema(connection: Connection[Any]) -> None:
    """Verify base and additive schemas using the caller's connection."""

    with connection.cursor() as cursor:
        _verify_base_schema(cursor)
        _verify_task_owned_tables(cursor)
        _verify_fund_schema(cursor)


def _verify_ledger(cursor: Any, checksum: str) -> None:
    _verify_columns(
        cursor, {"data_worker_schema_migrations": _FUND_COLUMNS["data_worker_schema_migrations"]}
    )
    cursor.execute(
        "SELECT version, name, checksum FROM data_worker_schema_migrations ORDER BY version"
    )
    rows = cursor.fetchall()
    expected_entries = {
        MIGRATION_VERSION: (MIGRATION_NAME, checksum),
        SEAT_MIGRATION_VERSION: (SEAT_MIGRATION_NAME, _seat_migration_checksum()),
        CALENDAR_SNAPSHOT_MIGRATION_VERSION: (
            CALENDAR_SNAPSHOT_MIGRATION_NAME,
            _calendar_snapshot_migration_checksum(),
        ),
        OFFICIAL_CALENDAR_MIGRATION_VERSION: (
            OFFICIAL_CALENDAR_MIGRATION_NAME,
            _official_calendar_migration_checksum(),
        ),
        CALENDAR_QUALITY_MIGRATION_VERSION: (
            CALENDAR_QUALITY_MIGRATION_NAME,
            _calendar_quality_migration_checksum(),
        ),
    }
    seen_versions: set[int] = set()
    for row in rows:
        version = int(row[0])
        expected = expected_entries.get(version)
        if expected is None or (str(row[1]), str(row[2])) != expected:
            raise ValueError("schema migration ledger checksum or name drift")
        seen_versions.add(version)
    if MIGRATION_VERSION not in seen_versions:
        raise ValueError("schema migration ledger checksum or name drift")
    if OFFICIAL_CALENDAR_MIGRATION_VERSION in seen_versions and not {
        MIGRATION_VERSION,
        SEAT_MIGRATION_VERSION,
        CALENDAR_SNAPSHOT_MIGRATION_VERSION,
    }.issubset(seen_versions):
        raise ValueError("schema migration ledger checksum or name drift")
    if CALENDAR_QUALITY_MIGRATION_VERSION in seen_versions and not {
        MIGRATION_VERSION,
        SEAT_MIGRATION_VERSION,
        CALENDAR_SNAPSHOT_MIGRATION_VERSION,
        OFFICIAL_CALENDAR_MIGRATION_VERSION,
    }.issubset(seen_versions):
        raise ValueError("schema migration ledger checksum or name drift")


_SEAT_COLUMNS: dict[str, tuple[str, ...]] = {
    "seat_collection_raw_records": (
        "source",
        "revision_id",
        "raw_record_id",
        "revision_key",
        "revision_accepted",
        "is_latest",
        "raw_json",
    ),
    "seat_collection_normalized": ("trade_id", "raw_record_id", "trade_json"),
    "seat_collection_rejected": ("raw_record_id", "reason", "rejected_json"),
    "seat_collection_batches": (
        "route_key",
        "batch_id",
        "request_fingerprint",
        "batch_fingerprint",
        "expected_previous_checkpoint",
        "checkpoint_token",
        "result_json",
    ),
    "seat_collection_checkpoints": (
        "route_key",
        "checkpoint_token",
        "batch_id",
        "request_fingerprint",
        "batch_fingerprint",
    ),
}


def _canonical_catalog_expression(value: object) -> str | None:
    if value is None:
        return None
    return (
        "".join(str(value).lower().split()).replace("::text", "").replace("(", "").replace(")", "")
    )


def _canonical_pg_definition(value: object) -> str:
    """Normalize pg_get_constraintdef output without weakening its semantics."""

    return " ".join(str(value).split()).lower()


def _verify_seat_collection_schema(cursor: Any) -> None:
    table_names = tuple(_SEAT_COLUMNS)
    placeholders = ", ".join("%s" for _ in table_names)
    cursor.execute(
        "SELECT table_name, column_name "
        "FROM information_schema.columns "
        f"WHERE table_schema = current_schema() AND table_name IN ({placeholders})",
        table_names,
    )
    actual = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
    missing = {
        (table, column)
        for table, columns in _SEAT_COLUMNS.items()
        for column in columns
        if (table, column) not in actual
    }
    if missing:
        table, column = sorted(missing)[0]
        raise ValueError(f"seat schema drift: missing column {table}.{column}")

    cursor.execute(
        "SELECT table_class.relname, index_class.relname, "
        "index_catalog.indisunique, index_catalog.indisprimary, "
        "ARRAY("
        "  SELECT attribute.attname "
        "  FROM unnest(index_catalog.indkey) WITH ORDINALITY "
        "       AS index_key(attnum, position) "
        "  JOIN pg_attribute AS attribute "
        "    ON attribute.attrelid = index_catalog.indrelid "
        "   AND attribute.attnum = index_key.attnum "
        "  WHERE index_key.position <= index_catalog.indnkeyatts "
        "  ORDER BY index_key.position"
        "), pg_get_expr(index_catalog.indpred, index_catalog.indrelid, TRUE) "
        "FROM pg_index AS index_catalog "
        "JOIN pg_class AS table_class ON table_class.oid = index_catalog.indrelid "
        "JOIN pg_class AS index_class ON index_class.oid = index_catalog.indexrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace "
        "WHERE namespace.nspname = current_schema() "
        f"AND table_class.relname IN ({placeholders})",
        table_names,
    )
    indexes = {
        (str(row[0]), str(row[1])): (
            bool(row[2]),
            bool(row[3]),
            tuple(str(column) for column in row[4]),
            _canonical_catalog_expression(row[5]),
        )
        for row in cursor.fetchall()
    }
    expected_named_indexes = {
        ("seat_collection_raw_records", "idx_seat_collection_raw_latest"): (
            False,
            False,
            ("revision_key", "is_latest"),
            None,
        ),
        ("seat_collection_raw_records", "uq_seat_collection_raw_latest"): (
            True,
            False,
            ("revision_key",),
            "is_latest=true",
        ),
    }
    for identity, expected in expected_named_indexes.items():
        if indexes.get(identity) != expected:
            raise ValueError(f"seat schema drift: index {identity[1]} definition mismatch")

    cursor.execute(
        "SELECT source_table.relname, constraint_catalog.contype, "
        "ARRAY("
        "  SELECT attribute.attname "
        "  FROM unnest(constraint_catalog.conkey) WITH ORDINALITY "
        "       AS constraint_key(attnum, position) "
        "  JOIN pg_attribute AS attribute "
        "    ON attribute.attrelid = constraint_catalog.conrelid "
        "   AND attribute.attnum = constraint_key.attnum "
        "  ORDER BY constraint_key.position"
        "), target_table.relname, "
        "ARRAY("
        "  SELECT attribute.attname "
        "  FROM unnest(constraint_catalog.confkey) WITH ORDINALITY "
        "       AS constraint_key(attnum, position) "
        "  JOIN pg_attribute AS attribute "
        "    ON attribute.attrelid = constraint_catalog.confrelid "
        "   AND attribute.attnum = constraint_key.attnum "
        "  ORDER BY constraint_key.position"
        "), pg_get_constraintdef(constraint_catalog.oid, TRUE) "
        "FROM pg_constraint AS constraint_catalog "
        "JOIN pg_class AS source_table ON source_table.oid = constraint_catalog.conrelid "
        "JOIN pg_namespace AS namespace ON namespace.oid = source_table.relnamespace "
        "LEFT JOIN pg_class AS target_table ON target_table.oid = constraint_catalog.confrelid "
        "WHERE namespace.nspname = current_schema() "
        f"AND source_table.relname IN ({placeholders})",
        table_names,
    )
    constraint_rows = cursor.fetchall()
    constraints = {
        (
            str(row[0]),
            str(row[1]),
            tuple(str(column) for column in row[2]),
            str(row[3]) if row[3] is not None else None,
            tuple(str(column) for column in row[4]),
        )
        for row in constraint_rows
    }
    required_constraints = {
        ("seat_collection_raw_records", "p", ("raw_record_id",), None, ()),
        ("seat_collection_raw_records", "u", ("source", "revision_id"), None, ()),
        ("seat_collection_normalized", "p", ("trade_id",), None, ()),
        (
            "seat_collection_normalized",
            "f",
            ("raw_record_id",),
            "seat_collection_raw_records",
            ("raw_record_id",),
        ),
        ("seat_collection_rejected", "p", ("raw_record_id", "reason"), None, ()),
        (
            "seat_collection_rejected",
            "f",
            ("raw_record_id",),
            "seat_collection_raw_records",
            ("raw_record_id",),
        ),
        ("seat_collection_batches", "p", ("route_key", "batch_id"), None, ()),
        (
            "seat_collection_batches",
            "u",
            ("route_key", "request_fingerprint", "batch_fingerprint"),
            None,
            (),
        ),
        ("seat_collection_checkpoints", "p", ("route_key",), None, ()),
    }
    missing_constraints = required_constraints - constraints
    if missing_constraints:
        table, kind, columns, _, _ = sorted(missing_constraints)[0]
        raise ValueError(f"seat schema drift: missing {kind} constraint on {table}{columns}")

    raw_checks = {
        _canonical_catalog_expression(row[5])
        for row in constraint_rows
        if str(row[0]) == "seat_collection_raw_records" and str(row[1]) == "c"
    }
    if "checkraw_payload_hash~'^[0-9a-f]{64}$'" not in raw_checks:
        raise ValueError("seat schema drift: raw payload hash check mismatch")
    if "checkis_latest=falseorrevision_accepted=true" not in raw_checks:
        raise ValueError("seat schema drift: latest revision check mismatch")


_OFFICIAL_CALENDAR_TABLES = (
    "official_calendar_scan_runs",
    "official_calendar_evidence_refs",
    "official_calendar_capture_attempts",
    "official_calendar_run_catalogs",
    "official_calendar_run_passes",
    "official_calendar_run_pages",
    "official_calendar_snapshots",
    "official_calendar_snapshot_evidence",
    "official_calendar_snapshot_days",
)
_OFFICIAL_CALENDAR_COLUMNS: dict[str, tuple[tuple[str, str, bool, bool], ...]] = {
    "official_calendar_scan_runs": (
        ("run_id", "uuid", False, False),
        ("authority", "text", False, False),
        ("exchange", "text", False, False),
        ("calendar_year", "integer", False, False),
        ("parser_version", "text", False, False),
        ("source_version", "text", False, False),
        ("contract_version", "text", False, False),
        ("policy_id", "text", False, False),
        ("compiled_catalog_sha256", "bytea", False, False),
        ("manifest_member_sha256", "bytea", False, False),
        ("manifest_raw_sha256", "bytea", False, False),
        ("proof_sha256", "bytea", False, False),
        ("manifest_raw_evidence_id", "uuid", False, False),
        ("manifest_artifact_id", "uuid", False, False),
        ("manifest_capture_id", "uuid", False, False),
        ("opened_at", "timestamp with time zone", False, False),
        ("cutoff_at", "timestamp with time zone", False, False),
        ("source_nowdate", "date", False, False),
        ("coverage_level", "text", False, False),
        ("confirmed_through", "date", True, False),
        ("run_disposition", "text", False, False),
        ("persisted_at", "timestamp with time zone", False, True),
    ),
    "official_calendar_evidence_refs": (
        ("evidence_ref_id", "uuid", False, False),
        ("run_id", "uuid", False, False),
        ("role", "text", False, False),
        ("source", "text", False, False),
        ("raw_capture_id", "text", False, False),
        ("raw_date", "date", False, False),
        ("raw_size", "integer", False, False),
        ("content_type", "text", False, False),
        ("object_sha256", "bytea", False, False),
        ("route_sha256", "bytea", False, False),
        ("request_identity", "text", False, False),
        ("identity_verified", "boolean", False, False),
        ("replay_verified", "boolean", False, False),
        ("observed_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
    ),
    "official_calendar_capture_attempts": (
        ("run_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("attempt_id", "text", False, False),
        ("capture_id", "text", False, False),
        ("endpoint_kind", "text", False, False),
        ("pass_number", "integer", True, False),
        ("month", "integer", True, False),
        ("status_code", "integer", False, False),
        ("error_code", "text", True, False),
        ("replay_allowed", "boolean", False, False),
        ("observed_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("raw_evidence_ref_id", "uuid", False, False),
        ("state_evidence_ref_id", "uuid", False, False),
    ),
    "official_calendar_run_catalogs": (
        ("run_id", "uuid", False, False),
        ("month", "integer", False, False),
        ("catalog_id", "uuid", False, False),
        ("resource_id", "text", False, False),
        ("raw_evidence_ref_id", "uuid", False, False),
        ("raw_artifact_sha256", "bytea", False, False),
    ),
    "official_calendar_run_passes": (
        ("run_id", "uuid", False, False),
        ("pass_number", "integer", False, False),
        ("pass_id", "uuid", False, False),
        ("opened_at", "timestamp with time zone", False, False),
        ("finished_at", "timestamp with time zone", False, False),
        ("member_sha256", "bytea", False, False),
    ),
    "official_calendar_run_pages": (
        ("run_id", "uuid", False, False),
        ("pass_number", "integer", False, False),
        ("month", "integer", False, False),
        ("page_id", "uuid", False, False),
        ("pass_id", "uuid", False, False),
        ("catalog_id", "uuid", False, False),
        ("resource_id", "text", False, False),
        ("raw_evidence_ref_id", "uuid", False, False),
        ("raw_artifact_sha256", "bytea", False, False),
        ("canonical_payload_sha256", "bytea", False, False),
        ("artifact_id", "uuid", False, False),
        ("capture_id", "uuid", False, False),
        ("opened_at", "timestamp with time zone", False, False),
        ("observed_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("source_nowdate", "date", False, False),
    ),
    "official_calendar_snapshots": (
        ("snapshot_id", "uuid", False, False),
        ("run_id", "uuid", False, False),
        ("authority", "text", False, False),
        ("exchange", "text", False, False),
        ("calendar_year", "integer", False, False),
        ("captured_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("terminal", "text", False, False),
        ("coverage_level", "text", False, False),
        ("confirmed_through", "date", True, False),
        ("supersedes_snapshot_id", "uuid", True, False),
        ("disposition", "text", False, False),
        ("persisted_at", "timestamp with time zone", False, True),
    ),
    "official_calendar_snapshot_evidence": (
        ("snapshot_id", "uuid", False, False),
        ("run_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("evidence_ref_id", "uuid", False, False),
        ("role", "text", False, False),
    ),
    "official_calendar_snapshot_days": (
        ("snapshot_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("calendar_date", "date", False, False),
        ("is_trading_day", "boolean", False, False),
        ("reason", "text", True, False),
    ),
}

# The V4 trigger graph is part of the integrity boundary.  Keep these bodies
# independent from the SQL resource so a schema owner cannot weaken a
# function and have the verifier learn the weakened body from that resource.
_OFFICIAL_CALENDAR_FUNCTION_BODIES: dict[str, str] = {
    "official_calendar_history_immutable": """
    BEGIN
        RAISE EXCEPTION 'official calendar history is immutable';
    END;
    """,
    "official_calendar_no_truncate": """
    BEGIN
        RAISE EXCEPTION 'official calendar history is immutable';
    END;
    """,
    "official_calendar_validate_run": """
    DECLARE
        snapshot_count INTEGER;
    BEGIN
        PERFORM pg_catalog.set_config(
            'search_path',
            pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
            TRUE
        );
        IF (SELECT count(*) FROM official_calendar_evidence_refs
            WHERE run_id = NEW.run_id) <> 69
           OR (SELECT count(*) FROM official_calendar_capture_attempts
               WHERE run_id = NEW.run_id) <> 28
           OR (SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id = NEW.run_id) <> 12
           OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = NEW.run_id) <> 2
           OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = NEW.run_id) <> 24
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_ROOT') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_PATH') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_CONCAT') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_JS') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'CATALOG') <> 12
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'RESPONSE') <> 24
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'STATE') <> 28
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'MANIFEST') <> 1
        THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_evidence_refs e
             WHERE e.run_id = NEW.run_id
               AND ((e.role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT',
                                'IDENTITY_JS', 'RESPONSE')
                     AND e.source <> 'szse-calendar')
                    OR (e.role = 'CATALOG' AND e.source <> 'szse-calendar-catalog')
                    OR (e.role = 'STATE' AND e.source <> 'szse-calendar-state')
                    OR (e.role = 'MANIFEST' AND e.source <> 'szse-calendar-manifest'))
        ) THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_capture_attempts a
              JOIN official_calendar_evidence_refs raw
                ON raw.run_id = a.run_id AND raw.evidence_ref_id = a.raw_evidence_ref_id
              JOIN official_calendar_evidence_refs state
                ON state.run_id = a.run_id AND state.evidence_ref_id = a.state_evidence_ref_id
             WHERE a.run_id = NEW.run_id
               AND ((a.ordinal = 1 AND raw.role <> 'IDENTITY_ROOT')
                    OR (a.ordinal = 2 AND raw.role <> 'IDENTITY_PATH')
                    OR (a.ordinal = 3 AND raw.role <> 'IDENTITY_CONCAT')
                    OR (a.ordinal = 4 AND raw.role <> 'IDENTITY_JS')
                    OR (a.ordinal > 4 AND raw.role <> 'RESPONSE')
                    OR (a.ordinal = 1 AND a.endpoint_kind <> 'root')
                    OR (a.ordinal = 2 AND a.endpoint_kind <> 'path')
                    OR (a.ordinal = 3 AND a.endpoint_kind <> 'concat')
                    OR (a.ordinal = 4 AND a.endpoint_kind <> 'js')
                    OR (a.ordinal > 4 AND a.endpoint_kind <> 'page')
                    OR (a.ordinal <= 4 AND (a.pass_number IS NOT NULL OR a.month IS NOT NULL))
                    OR (a.ordinal > 4 AND (a.pass_number <> ((a.ordinal - 5) / 12) + 1
                                           OR a.month <> ((a.ordinal - 5) % 12) + 1))
                    OR state.role <> 'STATE'
                    OR raw.source <> 'szse-calendar'
                    OR state.source <> 'szse-calendar-state'
                    OR raw.raw_capture_id <> a.capture_id
                OR state.request_identity !~ '^PUT path_sha256=[0-9a-f]{64}$')
        ) THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_run_catalogs c
              JOIN official_calendar_evidence_refs e
                ON e.run_id = c.run_id AND e.evidence_ref_id = c.raw_evidence_ref_id
             WHERE c.run_id = NEW.run_id
               AND (e.role <> 'CATALOG' OR e.source <> 'szse-calendar-catalog'
                    OR e.object_sha256 <> c.raw_artifact_sha256)
        ) THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_run_pages p
              LEFT JOIN official_calendar_evidence_refs e
                ON e.run_id = p.run_id AND e.evidence_ref_id = p.raw_evidence_ref_id
              LEFT JOIN official_calendar_run_passes pass
                ON pass.run_id = p.run_id AND pass.pass_number = p.pass_number
              LEFT JOIN official_calendar_run_catalogs catalog
                ON catalog.run_id = p.run_id AND catalog.month = p.month
             WHERE p.run_id = NEW.run_id
               AND (e.evidence_ref_id IS NULL OR e.role <> 'RESPONSE' OR e.source <> 'szse-calendar'
                    OR e.object_sha256 <> p.raw_artifact_sha256
                    OR e.observed_at <> p.observed_at OR e.available_at <> p.available_at
                    OR pass.pass_id IS NULL OR p.pass_id IS DISTINCT FROM pass.pass_id
                    OR catalog.catalog_id IS NULL
                    OR p.catalog_id IS DISTINCT FROM catalog.catalog_id
                    OR catalog.resource_id IS NULL
                    OR p.resource_id IS DISTINCT FROM catalog.resource_id)
        ) THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM (
                  SELECT a.observed_at, a.available_at,
                         lag(a.available_at) OVER (ORDER BY a.ordinal) AS previous_available
                    FROM official_calendar_capture_attempts a
                   WHERE a.run_id = NEW.run_id
              ) ordered
             WHERE ordered.previous_available IS NOT NULL
               AND (ordered.observed_at < ordered.previous_available
                    OR ordered.available_at < ordered.previous_available)
        ) THEN
            RAISE EXCEPTION 'official calendar run evidence is not ordered';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM official_calendar_evidence_refs e
             WHERE e.run_id = NEW.run_id
               AND e.evidence_ref_id = NEW.manifest_raw_evidence_id
               AND e.role = 'MANIFEST'
               AND e.source = 'szse-calendar-manifest'
               AND e.object_sha256 = NEW.manifest_raw_sha256
               AND e.observed_at = NEW.cutoff_at
               AND e.available_at = NEW.cutoff_at
        ) THEN
            RAISE EXCEPTION 'official calendar run is incomplete';
        END IF;
        SELECT count(*)::INTEGER
          INTO snapshot_count
          FROM official_calendar_snapshots
         WHERE run_id = NEW.run_id;
        IF (NEW.run_disposition = 'CONFIRMED' AND snapshot_count <> 1)
           OR (NEW.run_disposition <> 'CONFIRMED' AND snapshot_count <> 0)
        THEN
            RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
        END IF;
        RETURN NEW;
    END;
    """,
    "official_calendar_validate_append": """
    DECLARE
        target_run_id UUID;
        target_snapshot_id UUID;
        expected_days INTEGER;
        actual_days INTEGER;
    BEGIN
        PERFORM pg_catalog.set_config(
            'search_path',
            pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
            TRUE
        );
        IF TG_TABLE_NAME = 'official_calendar_snapshot_days' THEN
            target_snapshot_id := (to_jsonb(NEW)->>'snapshot_id')::UUID;
            SELECT run_id
              INTO target_run_id
              FROM official_calendar_snapshots
             WHERE snapshot_id = target_snapshot_id;
        ELSE
            target_run_id := (to_jsonb(NEW)->>'run_id')::UUID;
        END IF;
        IF target_run_id IS NULL THEN
            RAISE EXCEPTION 'official calendar run graph is invalid';
        END IF;
        IF TG_TABLE_NAME = 'official_calendar_snapshots'
           AND (SELECT run_disposition FROM official_calendar_scan_runs
                WHERE run_id = target_run_id)
               <> 'CONFIRMED'
        THEN
            RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
        END IF;
        IF (SELECT count(*) FROM official_calendar_evidence_refs
            WHERE run_id = target_run_id) > 69
           OR (SELECT count(*) FROM official_calendar_capture_attempts
               WHERE run_id = target_run_id) > 28
           OR (SELECT count(*) FROM official_calendar_run_catalogs
               WHERE run_id = target_run_id) > 12
           OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = target_run_id) > 2
           OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = target_run_id) > 24
           OR (SELECT count(*) FROM official_calendar_snapshots WHERE run_id = target_run_id) > 1
           OR (SELECT count(*) FROM official_calendar_snapshot_evidence
               WHERE run_id = target_run_id) > 69
        THEN
            RAISE EXCEPTION 'official calendar run graph is immutable';
        END IF;
        IF TG_TABLE_NAME = 'official_calendar_snapshot_days' THEN
            SELECT make_date(calendar_year, 12, 31) - make_date(calendar_year, 1, 1) + 1
              INTO expected_days
              FROM official_calendar_snapshots
             WHERE snapshot_id = target_snapshot_id;
            SELECT count(*)
              INTO actual_days
              FROM official_calendar_snapshot_days
             WHERE snapshot_id = target_snapshot_id;
            IF actual_days > expected_days THEN
                RAISE EXCEPTION 'official calendar run graph is immutable';
            END IF;
        END IF;
        RETURN NEW;
    END;
    """,
    "official_calendar_validate_snapshot": """
    DECLARE
        expected_days INTEGER;
        actual_days INTEGER;
        first_day DATE;
        last_day DATE;
        run_authority TEXT;
        run_exchange TEXT;
        run_year INTEGER;
        run_opened_at TIMESTAMPTZ;
        run_cutoff_at TIMESTAMPTZ;
        run_coverage_level TEXT;
        run_confirmed_through DATE;
        run_disposition TEXT;
    BEGIN
        PERFORM pg_catalog.set_config(
            'search_path',
            pg_catalog.format('pg_catalog,%I,pg_temp', TG_TABLE_SCHEMA),
            TRUE
        );
        expected_days := make_date(NEW.calendar_year, 12, 31)
            - make_date(NEW.calendar_year, 1, 1) + 1;
        SELECT r.authority, r.exchange, r.calendar_year, r.opened_at, r.cutoff_at,
               r.coverage_level, r.confirmed_through, r.run_disposition
          INTO run_authority, run_exchange, run_year, run_opened_at, run_cutoff_at,
               run_coverage_level, run_confirmed_through, run_disposition
          FROM official_calendar_scan_runs AS r
         WHERE r.run_id = NEW.run_id;
        IF run_disposition <> 'CONFIRMED'
           OR NEW.disposition <> 'SNAPSHOT_CREATED'
           OR run_authority <> NEW.authority
           OR run_exchange <> NEW.exchange
           OR run_year <> NEW.calendar_year
           OR run_coverage_level IS DISTINCT FROM NEW.coverage_level
           OR run_confirmed_through IS DISTINCT FROM NEW.confirmed_through
           OR NEW.terminal IS DISTINCT FROM (CASE
               WHEN run_coverage_level = 'FINAL_YEAR' THEN 'COMPLETE'
               ELSE 'INDETERMINATE'
           END)
        THEN
            RAISE EXCEPTION 'official calendar run snapshot disposition is invalid';
        END IF;
        IF run_opened_at IS NULL
           OR run_cutoff_at IS NULL
           OR NEW.captured_at <> run_opened_at
           OR NEW.available_at <> run_cutoff_at
        THEN
            RAISE EXCEPTION 'official calendar snapshot window is not bound to run';
        END IF;
        SELECT count(*)::INTEGER, min(calendar_date), max(calendar_date)
          INTO actual_days, first_day, last_day
          FROM official_calendar_snapshot_days
         WHERE snapshot_id = NEW.snapshot_id;
        IF actual_days <> expected_days
           OR first_day <> make_date(NEW.calendar_year, 1, 1)
           OR last_day <> make_date(NEW.calendar_year, 12, 31)
           OR (SELECT count(*) FROM official_calendar_snapshot_evidence
               WHERE snapshot_id = NEW.snapshot_id AND run_id = NEW.run_id) <> 69
           OR (SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id = NEW.run_id) <> 69
           OR (SELECT count(*) FROM official_calendar_capture_attempts
               WHERE run_id = NEW.run_id) <> 28
           OR (SELECT count(*) FROM official_calendar_run_catalogs WHERE run_id = NEW.run_id) <> 12
           OR (SELECT count(*) FROM official_calendar_run_passes WHERE run_id = NEW.run_id) <> 2
           OR (SELECT count(*) FROM official_calendar_run_pages WHERE run_id = NEW.run_id) <> 24
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_ROOT') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_PATH') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_CONCAT') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'IDENTITY_JS') <> 1
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'CATALOG') <> 12
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'RESPONSE') <> 24
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'STATE') <> 28
           OR (SELECT count(*) FROM official_calendar_evidence_refs
               WHERE run_id = NEW.run_id AND role = 'MANIFEST') <> 1
        THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_evidence_refs e
             WHERE e.run_id = NEW.run_id
               AND ((e.role IN ('IDENTITY_ROOT', 'IDENTITY_PATH', 'IDENTITY_CONCAT',
                                'IDENTITY_JS', 'RESPONSE')
                     AND e.source <> 'szse-calendar')
                    OR (e.role = 'CATALOG' AND e.source <> 'szse-calendar-catalog')
                    OR (e.role = 'STATE' AND e.source <> 'szse-calendar-state')
                    OR (e.role = 'MANIFEST' AND e.source <> 'szse-calendar-manifest'))
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_capture_attempts a
              JOIN official_calendar_evidence_refs raw
                ON raw.run_id = a.run_id AND raw.evidence_ref_id = a.raw_evidence_ref_id
              JOIN official_calendar_evidence_refs state
                ON state.run_id = a.run_id AND state.evidence_ref_id = a.state_evidence_ref_id
             WHERE a.run_id = NEW.run_id
               AND ((a.ordinal = 1 AND raw.role <> 'IDENTITY_ROOT')
                    OR (a.ordinal = 2 AND raw.role <> 'IDENTITY_PATH')
                    OR (a.ordinal = 3 AND raw.role <> 'IDENTITY_CONCAT')
                    OR (a.ordinal = 4 AND raw.role <> 'IDENTITY_JS')
                    OR (a.ordinal > 4 AND raw.role <> 'RESPONSE')
                    OR (a.ordinal = 1 AND a.endpoint_kind <> 'root')
                    OR (a.ordinal = 2 AND a.endpoint_kind <> 'path')
                    OR (a.ordinal = 3 AND a.endpoint_kind <> 'concat')
                    OR (a.ordinal = 4 AND a.endpoint_kind <> 'js')
                    OR (a.ordinal > 4 AND a.endpoint_kind <> 'page')
                    OR (a.ordinal <= 4 AND (a.pass_number IS NOT NULL OR a.month IS NOT NULL))
                    OR (a.ordinal > 4 AND (a.pass_number <> ((a.ordinal - 5) / 12) + 1
                                           OR a.month <> ((a.ordinal - 5) % 12) + 1))
                    OR state.role <> 'STATE'
                    OR raw.source <> 'szse-calendar'
                    OR state.source <> 'szse-calendar-state'
                    OR raw.raw_capture_id <> a.capture_id
                OR state.request_identity !~ '^PUT path_sha256=[0-9a-f]{64}$')
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_run_catalogs c
              JOIN official_calendar_evidence_refs e
                ON e.run_id = c.run_id AND e.evidence_ref_id = c.raw_evidence_ref_id
             WHERE c.run_id = NEW.run_id
               AND (e.role <> 'CATALOG' OR e.source <> 'szse-calendar-catalog'
                    OR e.object_sha256 <> c.raw_artifact_sha256)
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_run_pages p
              LEFT JOIN official_calendar_evidence_refs e
                ON e.run_id = p.run_id AND e.evidence_ref_id = p.raw_evidence_ref_id
              LEFT JOIN official_calendar_run_passes pass
                ON pass.run_id = p.run_id AND pass.pass_number = p.pass_number
              LEFT JOIN official_calendar_run_catalogs catalog
                ON catalog.run_id = p.run_id AND catalog.month = p.month
             WHERE p.run_id = NEW.run_id
               AND (e.evidence_ref_id IS NULL OR e.role <> 'RESPONSE' OR e.source <> 'szse-calendar'
                    OR e.object_sha256 <> p.raw_artifact_sha256
                    OR e.observed_at <> p.observed_at OR e.available_at <> p.available_at
                    OR pass.pass_id IS NULL OR p.pass_id IS DISTINCT FROM pass.pass_id
                    OR catalog.catalog_id IS NULL
                    OR p.catalog_id IS DISTINCT FROM catalog.catalog_id
                    OR catalog.resource_id IS NULL
                    OR p.resource_id IS DISTINCT FROM catalog.resource_id)
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM official_calendar_evidence_refs e
             WHERE e.run_id = NEW.run_id
               AND e.evidence_ref_id = (SELECT r.manifest_raw_evidence_id
                                        FROM official_calendar_scan_runs r
                                        WHERE r.run_id = NEW.run_id)
               AND e.role = 'MANIFEST'
               AND e.source = 'szse-calendar-manifest'
               AND e.object_sha256 = (SELECT r.manifest_raw_sha256
                                      FROM official_calendar_scan_runs r
                                      WHERE r.run_id = NEW.run_id)
               AND e.observed_at = (SELECT r.cutoff_at
                                    FROM official_calendar_scan_runs r
                                    WHERE r.run_id = NEW.run_id)
               AND e.available_at = (SELECT r.cutoff_at
                                     FROM official_calendar_scan_runs r
                                     WHERE r.run_id = NEW.run_id)
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot is incomplete';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_snapshot_evidence se
             WHERE se.snapshot_id = NEW.snapshot_id
               AND ((se.ordinal = 0 AND se.role <> 'IDENTITY_ROOT')
                    OR (se.ordinal = 1 AND se.role <> 'STATE')
                    OR (se.ordinal = 2 AND se.role <> 'IDENTITY_PATH')
                    OR (se.ordinal = 3 AND se.role <> 'STATE')
                    OR (se.ordinal = 4 AND se.role <> 'IDENTITY_CONCAT')
                    OR (se.ordinal = 5 AND se.role <> 'STATE')
                    OR (se.ordinal = 6 AND se.role <> 'IDENTITY_JS')
                    OR (se.ordinal = 7 AND se.role <> 'STATE')
                    OR (se.ordinal BETWEEN 8 AND 19 AND se.role <> 'CATALOG')
                    OR (se.ordinal BETWEEN 20 AND 67
                        AND (((se.ordinal - 20) % 2 = 0 AND se.role <> 'RESPONSE')
                             OR ((se.ordinal - 20) % 2 = 1 AND se.role <> 'STATE')))
                    OR (se.ordinal = 68 AND se.role <> 'MANIFEST'))
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM (
                  SELECT e.observed_at, e.available_at,
                         lag(e.available_at) OVER (ORDER BY se.ordinal) AS previous_available
                    FROM official_calendar_snapshot_evidence se
                    JOIN official_calendar_evidence_refs e
                      ON e.run_id = se.run_id AND e.evidence_ref_id = se.evidence_ref_id
                   WHERE se.snapshot_id = NEW.snapshot_id
              ) ordered
             WHERE ordered.previous_available IS NOT NULL
               AND (ordered.observed_at < ordered.previous_available
                    OR ordered.available_at < ordered.previous_available)
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
        END IF;
        IF EXISTS (
            SELECT 1 FROM official_calendar_snapshot_days d
            WHERE d.snapshot_id = NEW.snapshot_id
              AND d.calendar_date <> make_date(NEW.calendar_year, 1, 1) + d.ordinal
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot days are not continuous';
        END IF;
        IF EXISTS (
            SELECT 1 FROM official_calendar_evidence_refs e
            WHERE e.run_id = NEW.run_id AND (
                e.observed_at < (SELECT opened_at FROM official_calendar_scan_runs
                                 WHERE run_id = NEW.run_id)
                OR e.available_at > (SELECT cutoff_at FROM official_calendar_scan_runs
                                     WHERE run_id = NEW.run_id))
        ) THEN
            RAISE EXCEPTION 'official calendar evidence is outside run window';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM official_calendar_snapshot_evidence se
              JOIN official_calendar_evidence_refs e ON e.evidence_ref_id = se.evidence_ref_id
             WHERE se.snapshot_id = NEW.snapshot_id
               AND (e.run_id <> NEW.run_id OR se.run_id <> NEW.run_id OR se.role <> e.role)
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot evidence has wrong lineage';
        END IF;
        IF (SELECT min(ordinal) FROM official_calendar_snapshot_evidence
            WHERE snapshot_id = NEW.snapshot_id) <> 0
           OR (SELECT max(ordinal) FROM official_calendar_snapshot_evidence
               WHERE snapshot_id = NEW.snapshot_id) <> 68
        THEN
            RAISE EXCEPTION 'official calendar snapshot evidence is not ordered';
        END IF;
        IF NEW.supersedes_snapshot_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
              FROM official_calendar_snapshots parent
             WHERE parent.snapshot_id = NEW.supersedes_snapshot_id
               AND parent.authority = NEW.authority
               AND parent.exchange = NEW.exchange
               AND parent.calendar_year = NEW.calendar_year
               AND parent.available_at < NEW.available_at
        ) THEN
            RAISE EXCEPTION 'official calendar snapshot parent is invalid';
        END IF;
        RETURN NEW;
    END;
    """,
}
_OFFICIAL_CALENDAR_INDEX_COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "official_calendar_snapshots_resolution_idx": (
        "official_calendar_snapshots",
        ("authority", "exchange", "calendar_year", "available_at", "snapshot_id"),
    ),
    "official_calendar_evidence_refs_timeline_idx": (
        "official_calendar_evidence_refs",
        ("run_id", "observed_at", "available_at", "evidence_ref_id"),
    ),
}


def _official_calendar_tables(cursor: Any) -> set[str]:
    cursor.execute(
        "SELECT c.relname FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') "
        "AND c.relname LIKE 'official_calendar_%'"
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _verify_official_calendar_schema(cursor: Any) -> None:
    tables = tuple(_OFFICIAL_CALENDAR_COLUMNS)
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = current_schema() "
        f"AND table_name IN ({placeholders}) ORDER BY table_name, ordinal_position",
        tables,
    )
    actual: dict[str, list[tuple[str, str, bool, bool, object]]] = {}
    for table, column, data_type, nullable, default in cursor.fetchall():
        actual.setdefault(str(table), []).append(
            (
                str(column),
                str(data_type),
                str(nullable).upper() == "YES",
                default is not None,
                default,
            )
        )
    if _official_calendar_tables(cursor) != set(_OFFICIAL_CALENDAR_TABLES):
        raise ValueError("official calendar schema drift: table set mismatch")
    for table, expected in _OFFICIAL_CALENDAR_COLUMNS.items():
        observed = actual.get(table)
        if observed is None or tuple(row[0] for row in observed) != tuple(
            row[0] for row in expected
        ):
            raise ValueError(f"official calendar schema drift: columns in {table}")
        for got, want in zip(observed, expected, strict=True):
            if got[0] != want[0] or got[1] != want[1] or got[2] != want[2] or got[3] != want[3]:
                raise ValueError(f"official calendar schema drift: column {table}.{got[0]}")
            if want[3] and _canonical_catalog_expression(got[4]) != "current_timestamp":
                raise ValueError(f"official calendar schema drift: default {table}.{got[0]}")
    expected_function_names = set(_OFFICIAL_CALENDAR_FUNCTION_BODIES)
    cursor.execute(
        "SELECT p.oid, p.proname, p.pronargs, p.pronargdefaults, p.prokind, "
        "p.provolatile, p.prosecdef, p.proleakproof, p.proparallel, p.provariadic, "
        "p.proconfig, "
        "pg_get_function_identity_arguments(p.oid), pg_get_function_result(p.oid), "
        "rt.typname, l.lanname, p.prosrc "
        "FROM pg_proc AS p "
        "JOIN pg_namespace AS n ON n.oid=p.pronamespace "
        "JOIN pg_type AS rt ON rt.oid=p.prorettype "
        "JOIN pg_language AS l ON l.oid=p.prolang "
        "WHERE n.nspname=current_schema() AND p.proname = ANY(%s)",
        (list(expected_function_names),),
    )
    function_rows = cursor.fetchall()
    if len(function_rows) != len(expected_function_names):
        raise ValueError("official calendar schema drift: function set mismatch")
    function_oids: dict[str, int] = {}
    for row in function_rows:
        (
            function_oid,
            function_name,
            argument_count,
            argument_defaults,
            function_kind,
            volatility,
            security_definer,
            leakproof,
            parallel_safety,
            variadic_oid,
            configuration,
            identity_arguments,
            function_result,
            return_type,
            language,
            function_body,
        ) = row
        name = str(function_name)
        expected_body = _canonical_function_body(_OFFICIAL_CALENDAR_FUNCTION_BODIES[name])
        if (
            name not in expected_function_names
            or name in function_oids
            or int(argument_count) != 0
            or int(argument_defaults) != 0
            or str(function_kind) != "f"
            or str(volatility) != "v"
            or bool(security_definer)
            or bool(leakproof)
            or str(parallel_safety) != "u"
            or int(variadic_oid) != 0
            or tuple(str(item) for item in (configuration or ())) != ("search_path=pg_catalog",)
            or str(identity_arguments) != ""
            or str(function_result) != "trigger"
            or str(return_type) != "trigger"
            or str(language) != "plpgsql"
            or _canonical_function_body(function_body) != expected_body
        ):
            raise ValueError(f"official calendar schema drift: function {name}")
        function_oids[name] = int(function_oid)
    if set(function_oids) != expected_function_names:
        raise ValueError("official calendar schema drift: function set mismatch")

    cursor.execute(
        "SELECT c.relname, t.tgname, t.tgtype, t.tgenabled, t.tgdeferrable, "
        "t.tginitdeferred, t.tgconstraint, t.tgfoid, p.proname, p.prokind, rt.typname, "
        "l.lanname, t.tgnargs, t.tgargs, pg_get_expr(t.tgqual, t.tgrelid, TRUE) "
        "FROM pg_trigger AS t "
        "JOIN pg_class AS c ON c.oid=t.tgrelid "
        "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
        "JOIN pg_proc AS p ON p.oid=t.tgfoid "
        "JOIN pg_type AS rt ON rt.oid=p.prorettype "
        "JOIN pg_language AS l ON l.oid=p.prolang "
        "WHERE n.nspname=current_schema() AND c.relname LIKE 'official_calendar_%' "
        "AND NOT t.tgisinternal"
    )
    trigger_rows = cursor.fetchall()
    trigger_names = {(str(row[0]), str(row[1])) for row in trigger_rows}
    expected_triggers = (
        {(table, f"{table}_immutable") for table in _OFFICIAL_CALENDAR_TABLES}
        | {(table, f"{table}_no_truncate") for table in _OFFICIAL_CALENDAR_TABLES}
        | {("official_calendar_scan_runs", "official_calendar_scan_runs_complete")}
        | {("official_calendar_snapshots", "official_calendar_snapshots_complete")}
        | {
            (table, f"{table}_append_guard")
            for table in _OFFICIAL_CALENDAR_TABLES
            if table != "official_calendar_scan_runs"
        }
    )
    if trigger_names != expected_triggers:
        raise ValueError("official calendar schema drift: trigger set mismatch")
    for row in trigger_rows:
        (
            table,
            name,
            trigger_type,
            enabled,
            deferrable,
            initially_deferred,
            constraint_oid,
            function_oid,
            function_name,
            function_kind,
            return_type,
            language,
            argument_count,
            arguments,
            condition,
        ) = row
        if name.endswith("_immutable"):
            expected_type = 27
            expected_deferrable = False
            expected_constraint = 0
            expected_function = "official_calendar_history_immutable"
        elif name.endswith("_no_truncate"):
            expected_type = 34
            expected_deferrable = False
            expected_constraint = 0
            expected_function = "official_calendar_no_truncate"
        elif name.endswith("_append_guard"):
            expected_type = 5
            expected_deferrable = True
            expected_constraint = None
            expected_function = "official_calendar_validate_append"
        elif name == "official_calendar_scan_runs_complete":
            expected_type = 5
            expected_deferrable = True
            expected_constraint = None
            expected_function = "official_calendar_validate_run"
        elif name == "official_calendar_snapshots_complete":
            expected_type = 5
            expected_deferrable = True
            expected_constraint = None
            expected_function = "official_calendar_validate_snapshot"
        else:
            raise ValueError("official calendar schema drift: trigger definition")
        if (
            int(trigger_type) != expected_type
            or str(enabled) != "O"
            or bool(deferrable) != expected_deferrable
            or bool(initially_deferred) != expected_deferrable
            or (expected_constraint == 0 and int(constraint_oid) != 0)
            or (expected_constraint is None and int(constraint_oid) == 0)
            or int(function_oid) != function_oids[expected_function]
            or str(function_name) != expected_function
            or str(function_kind) != "f"
            or str(return_type) != "trigger"
            or str(language) != "plpgsql"
            or int(argument_count) != 0
            or bytes(arguments) != b""
            or condition is not None
        ):
            raise ValueError("official calendar schema drift: trigger definition")
    expected_constraints_by_name: dict[str, tuple[str, str]] = {
        "official_calendar_capture_attempts_identity_uk": (
            "u",
            "unique (run_id, capture_id)",
        ),
        "official_calendar_capture_attempts_edge_ck": (
            "c",
            "check (ordinal = 1 and endpoint_kind = 'root'::text and pass_number is null "
            "and month is null or ordinal = 2 and endpoint_kind = 'path'::text "
            "and pass_number is null and month is null or ordinal = 3 "
            "and endpoint_kind = 'concat'::text and pass_number is null and month is null "
            "or ordinal = 4 and endpoint_kind = 'js'::text and pass_number is null "
            "and month is null or ordinal > 4 and endpoint_kind = 'page'::text "
            "and pass_number = ((ordinal - 5) / 12 + 1) and month = ((ordinal - 5) % 12 + 1))",
        ),
        "official_calendar_capture_attempts_ordinal_ck": (
            "c",
            "check (ordinal >= 1 and ordinal <= 28)",
        ),
        "official_calendar_capture_attempts_pass_month_ck": (
            "c",
            "check (ordinal <= 4 and pass_number is null and month is null or ordinal > 4 "
            "and (pass_number = any (array[1, 2])) and month >= 1 and month <= 12)",
        ),
        "official_calendar_capture_attempts_pkey": ("p", "primary key (run_id, ordinal)"),
        "official_calendar_capture_attempts_raw_fkey": (
            "f",
            "foreign key (run_id, raw_evidence_ref_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_capture_attempts_raw_capture_fkey": (
            "f",
            "foreign key (run_id, capture_id) references "
            "official_calendar_evidence_refs(run_id, raw_capture_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_capture_attempts_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_capture_attempts_state_fkey": (
            "f",
            "foreign key (run_id, state_evidence_ref_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_capture_attempts_status_ck": (
            "c",
            "check (status_code = 200 and error_code is null and replay_allowed)",
        ),
        "official_calendar_capture_attempts_window_ck": (
            "c",
            "check (observed_at <= available_at)",
        ),
        "official_calendar_evidence_refs_digest_ck": (
            "c",
            "check (octet_length(object_sha256) = 32 and octet_length(route_sha256) = 32)",
        ),
        "official_calendar_evidence_refs_identity_uk": (
            "u",
            "unique (run_id, source, raw_capture_id)",
        ),
        "official_calendar_evidence_refs_capture_uk": (
            "u",
            "unique (run_id, raw_capture_id)",
        ),
        "official_calendar_evidence_refs_pkey": ("p", "primary key (evidence_ref_id)"),
        "official_calendar_evidence_refs_role_ck": (
            "c",
            "check (role = any (array['identity_root'::text, 'identity_path'::text, "
            "'identity_concat'::text, "
            "'identity_js'::text, "
            "'catalog'::text, 'response'::text, 'state'::text, 'manifest'::text]))",
        ),
        "official_calendar_evidence_refs_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_evidence_refs_scope_uk": (
            "u",
            "unique (run_id, evidence_ref_id)",
        ),
        "official_calendar_evidence_refs_size_ck": ("c", "check (raw_size >= 0)"),
        "official_calendar_evidence_refs_window_ck": (
            "c",
            "check (observed_at <= available_at)",
        ),
        "official_calendar_evidence_refs_verification_ck": (
            "c",
            "check (identity_verified and replay_verified)",
        ),
        "official_calendar_run_catalogs_catalog_uk": (
            "u",
            "unique (run_id, catalog_id)",
        ),
        "official_calendar_run_catalogs_scope_id_uk": (
            "u",
            "unique (run_id, month, catalog_id)",
        ),
        "official_calendar_run_catalogs_digest_ck": (
            "c",
            "check (octet_length(raw_artifact_sha256) = 32)",
        ),
        "official_calendar_run_catalogs_month_ck": (
            "c",
            "check (month >= 1 and month <= 12)",
        ),
        "official_calendar_run_catalogs_pkey": ("p", "primary key (run_id, month)"),
        "official_calendar_run_catalogs_raw_fkey": (
            "f",
            "foreign key (run_id, raw_evidence_ref_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_catalogs_resource_ck": (
            "c",
            "check (resource_id <> ''::text)",
        ),
        "official_calendar_run_catalogs_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_capture_uk": (
            "u",
            "unique (run_id, capture_id)",
        ),
        "official_calendar_run_pages_catalog_fkey": (
            "f",
            "foreign key (run_id, month) references official_calendar_run_catalogs(run_id, month) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_catalog_scope_fkey": (
            "f",
            "foreign key (run_id, month, catalog_id) references "
            "official_calendar_run_catalogs(run_id, month, catalog_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_digest_ck": (
            "c",
            "check (octet_length(raw_artifact_sha256) = 32 and "
            "octet_length(canonical_payload_sha256) = 32)",
        ),
        "official_calendar_run_pages_month_ck": (
            "c",
            "check (month >= 1 and month <= 12)",
        ),
        "official_calendar_run_pages_page_uk": ("u", "unique (run_id, page_id)"),
        "official_calendar_run_pages_pass_fkey": (
            "f",
            "foreign key (run_id, pass_number) references "
            "official_calendar_run_passes(run_id, pass_number) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_pass_id_fkey": (
            "f",
            "foreign key (run_id, pass_id) references "
            "official_calendar_run_passes(run_id, pass_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_pass_scope_fkey": (
            "f",
            "foreign key (run_id, pass_number, pass_id) references "
            "official_calendar_run_passes(run_id, pass_number, pass_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_pass_number_ck": (
            "c",
            "check (pass_number = any (array[1, 2]))",
        ),
        "official_calendar_run_pages_pkey": (
            "p",
            "primary key (run_id, pass_number, month)",
        ),
        "official_calendar_run_pages_raw_fkey": (
            "f",
            "foreign key (run_id, raw_evidence_ref_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_catalog_id_fkey": (
            "f",
            "foreign key (run_id, catalog_id) references "
            "official_calendar_run_catalogs(run_id, catalog_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_resource_ck": (
            "c",
            "check (resource_id <> ''::text)",
        ),
        "official_calendar_run_pages_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_pages_window_ck": (
            "c",
            "check (opened_at <= observed_at and observed_at <= available_at)",
        ),
        "official_calendar_run_passes_digest_ck": (
            "c",
            "check (octet_length(member_sha256) = 32)",
        ),
        "official_calendar_run_passes_id_uk": ("u", "unique (run_id, pass_id)"),
        "official_calendar_run_passes_scope_id_uk": (
            "u",
            "unique (run_id, pass_number, pass_id)",
        ),
        "official_calendar_run_passes_number_ck": (
            "c",
            "check (pass_number = any (array[1, 2]))",
        ),
        "official_calendar_run_passes_pkey": ("p", "primary key (run_id, pass_number)"),
        "official_calendar_run_passes_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_run_passes_window_ck": (
            "c",
            "check (opened_at < finished_at)",
        ),
        "official_calendar_scan_runs_authority_ck": (
            "c",
            "check (authority = 'szse'::text)",
        ),
        "official_calendar_scan_runs_contract_version_ck": (
            "c",
            "check (contract_version = 'calendar-scan-run-v4'::text)",
        ),
        "official_calendar_scan_runs_catalog_digest_ck": (
            "c",
            "check (octet_length(compiled_catalog_sha256) = 32)",
        ),
        "official_calendar_scan_runs_complete": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_evidence_refs_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_capture_attempts_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_run_catalogs_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_run_passes_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_run_pages_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_snapshots_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_snapshot_evidence_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_snapshot_days_append_guard": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_scan_runs_coverage_ck": (
            "c",
            "check (coverage_level = 'indeterminate'::text and confirmed_through is null "
            "or (coverage_level = any (array['confirmed_horizon'::text, 'final_year'::text])) "
            "and confirmed_through >= make_date(calendar_year, 1, 1) "
            "and confirmed_through <= make_date(calendar_year, 12, 31))",
        ),
        "official_calendar_scan_runs_exchange_ck": (
            "c",
            "check (exchange = 'sz'::text)",
        ),
        "official_calendar_scan_runs_final_ck": (
            "c",
            "check (coverage_level <> 'final_year'::text "
            "or confirmed_through = make_date(calendar_year, 12, 31))",
        ),
        "official_calendar_scan_runs_manifest_member_digest_ck": (
            "c",
            "check (octet_length(manifest_member_sha256) = 32)",
        ),
        "official_calendar_scan_runs_manifest_fkey": (
            "f",
            "foreign key (run_id, manifest_raw_evidence_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict deferrable initially deferred",
        ),
        "official_calendar_scan_runs_manifest_raw_digest_ck": (
            "c",
            "check (octet_length(manifest_raw_sha256) = 32)",
        ),
        "official_calendar_scan_runs_pkey": ("p", "primary key (run_id)"),
        "official_calendar_scan_runs_policy_ck": (
            "c",
            "check (policy_id = 'szse-direct-daily-v1'::text)",
        ),
        "official_calendar_scan_runs_parser_version_ck": (
            "c",
            "check (parser_version = 'szse-direct-daily-v4'::text)",
        ),
        "official_calendar_scan_runs_proof_digest_ck": (
            "c",
            "check (octet_length(proof_sha256) = 32)",
        ),
        "official_calendar_scan_runs_source_version_ck": (
            "c",
            "check (source_version = 'szse-direct-daily-v4'::text)",
        ),
        "official_calendar_scan_runs_disposition_ck": (
            "c",
            "check (run_disposition = any (array['confirmed'::text, 'out_of_order'::text, "
            "'duplicate'::text, 'conflict'::text]))",
        ),
        "official_calendar_scan_runs_window_ck": (
            "c",
            "check (opened_at <= cutoff_at)",
        ),
        "official_calendar_scan_runs_year_ck": (
            "c",
            "check (calendar_year >= 1 and calendar_year <= 9999)",
        ),
        "official_calendar_snapshots_authority_ck": (
            "c",
            "check (authority = 'szse'::text)",
        ),
        "official_calendar_snapshots_complete": (
            "t",
            "trigger deferrable initially deferred",
        ),
        "official_calendar_snapshots_coverage_ck": (
            "c",
            "check (coverage_level = 'indeterminate'::text and confirmed_through is null "
            "or (coverage_level = any (array['confirmed_horizon'::text, 'final_year'::text])) "
            "and confirmed_through >= make_date(calendar_year, 1, 1) "
            "and confirmed_through <= make_date(calendar_year, 12, 31))",
        ),
        "official_calendar_snapshots_disposition_ck": (
            "c",
            "check (disposition = 'snapshot_created'::text)",
        ),
        "official_calendar_snapshots_exchange_ck": (
            "c",
            "check (exchange = 'sz'::text)",
        ),
        "official_calendar_snapshots_parent_fkey": (
            "f",
            "foreign key (supersedes_snapshot_id) references "
            "official_calendar_snapshots(snapshot_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_snapshots_pkey": ("p", "primary key (snapshot_id)"),
        "official_calendar_snapshots_run_fkey": (
            "f",
            "foreign key (run_id) references official_calendar_scan_runs(run_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_snapshots_run_uk": ("u", "unique (run_id)"),
        "official_calendar_snapshots_scope_uk": (
            "u",
            "unique (snapshot_id, authority, exchange, calendar_year)",
        ),
        "official_calendar_snapshots_snapshot_run_uk": (
            "u",
            "unique (snapshot_id, run_id)",
        ),
        "official_calendar_snapshots_terminal_ck": (
            "c",
            "check (terminal = any (array['complete'::text, 'indeterminate'::text]))",
        ),
        "official_calendar_snapshots_terminal_coverage_ck": (
            "c",
            "check (coverage_level = 'final_year'::text and terminal = 'complete'::text "
            "or coverage_level <> 'final_year'::text and terminal = 'indeterminate'::text)",
        ),
        "official_calendar_snapshots_window_ck": (
            "c",
            "check (captured_at <= available_at)",
        ),
        "official_calendar_snapshots_year_ck": (
            "c",
            "check (calendar_year >= 1 and calendar_year <= 9999)",
        ),
        "official_calendar_snapshot_days_date_uk": (
            "u",
            "unique (snapshot_id, calendar_date)",
        ),
        "official_calendar_snapshot_days_ordinal_ck": ("c", "check (ordinal >= 0)"),
        "official_calendar_snapshot_days_pkey": (
            "p",
            "primary key (snapshot_id, ordinal)",
        ),
        "official_calendar_snapshot_days_reason_ck": (
            "c",
            "check (is_trading_day and reason is null or not is_trading_day "
            "and reason = 'special'::text)",
        ),
        "official_calendar_snapshot_days_snapshot_fkey": (
            "f",
            "foreign key (snapshot_id) references official_calendar_snapshots(snapshot_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_snapshot_evidence_pkey": (
            "p",
            "primary key (snapshot_id, ordinal)",
        ),
        "official_calendar_snapshot_evidence_ordinal_ck": (
            "c",
            "check (ordinal >= 0 and ordinal <= 68)",
        ),
        "official_calendar_snapshot_evidence_ref_uk": (
            "u",
            "unique (snapshot_id, evidence_ref_id)",
        ),
        "official_calendar_snapshot_evidence_run_ref_fkey": (
            "f",
            "foreign key (run_id, evidence_ref_id) references "
            "official_calendar_evidence_refs(run_id, evidence_ref_id) "
            "on update restrict on delete restrict",
        ),
        "official_calendar_snapshot_evidence_role_ck": (
            "c",
            "check (role = any (array['identity_root'::text, 'identity_path'::text, "
            "'identity_concat'::text, "
            "'identity_js'::text, "
            "'catalog'::text, 'response'::text, 'state'::text, 'manifest'::text]))",
        ),
        "official_calendar_snapshot_evidence_snapshot_run_fkey": (
            "f",
            "foreign key (snapshot_id, run_id) references "
            "official_calendar_snapshots(snapshot_id, run_id) "
            "on update restrict on delete restrict",
        ),
    }
    cursor.execute("SELECT current_schema()")
    schema_row = cursor.fetchone()
    if schema_row is None:
        raise ValueError("official calendar schema drift: constraint schema is unavailable")
    schema_name = str(schema_row[0])
    expected_constraints: dict[tuple[str, str, str], tuple[str, str]] = {}
    for name, specification in expected_constraints_by_name.items():
        matching_tables = tuple(
            table for table in _OFFICIAL_CALENDAR_TABLES if name.startswith(f"{table}_")
        )
        if len(matching_tables) != 1:
            raise ValueError(f"official calendar schema drift: constraint mapping {name}")
        expected_constraints[(schema_name, matching_tables[0], name)] = specification
    cursor.execute(
        "SELECT n.nspname, c.relname, con.conname, con.contype, "
        "pg_get_constraintdef(con.oid, TRUE), "
        "condeferrable, condeferred, convalidated, connoinherit "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS c ON c.oid=con.conrelid "
        "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname LIKE 'official_calendar_%'"
    )
    constraint_rows = cursor.fetchall()
    actual_constraints = {
        (str(row[0]), str(row[1]), str(row[2])): (
            str(row[3]),
            _canonical_pg_definition(row[4]),
        )
        for row in constraint_rows
    }
    if actual_constraints != expected_constraints:
        missing = sorted(set(expected_constraints) - set(actual_constraints))
        extra = sorted(set(actual_constraints) - set(expected_constraints))
        mismatched = sorted(
            name
            for name in set(expected_constraints) & set(actual_constraints)
            if expected_constraints[name] != actual_constraints[name]
        )
        raise ValueError(
            "official calendar schema drift: constraints "
            f"missing={missing!r} extra={extra!r} mismatched={mismatched!r}"
        )
    for row in constraint_rows:
        (
            schema,
            table,
            name,
            constraint_type,
            _definition,
            deferrable,
            deferred,
            validated,
            no_inherit,
        ) = row
        expected_definition = expected_constraints[(str(schema), str(table), str(name))][1]
        if (
            bool(deferrable) != ("deferrable" in expected_definition)
            or bool(deferred) != ("initially deferred" in expected_definition)
            or not bool(validated)
            or bool(no_inherit) != (str(constraint_type) != "c")
        ):
            raise ValueError(
                f"official calendar schema drift: constraint metadata {schema}.{table}.{name}"
            )
    cursor.execute(
        "SELECT i.oid, i.relname, c.relname, am.amname, ix.indisunique, "
        "ix.indnkeyatts, ix.indnatts, ix.indkey, ix.indoption, ix.indclass, "
        "ix.indcollation, ix.indnullsnotdistinct, pg_get_expr(ix.indpred, ix.indrelid, TRUE), "
        "i.reloptions, ix.indisvalid, ix.indisready, owner.conname "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid=c.relnamespace "
        "JOIN pg_index AS ix ON ix.indrelid=c.oid "
        "JOIN pg_class AS i ON i.oid=ix.indexrelid "
        "JOIN pg_am AS am ON am.oid=i.relam "
        "LEFT JOIN pg_constraint AS owner "
        "ON owner.conindid=i.oid AND owner.contype IN ('p', 'u') "
        "WHERE n.nspname=current_schema() AND i.relname IN (%s, %s)"
        " ORDER BY i.relname",
        tuple(_OFFICIAL_CALENDAR_INDEX_COLUMNS),
    )
    index_rows = cursor.fetchall()
    actual_index_names = {str(row[1]) for row in index_rows}
    if actual_index_names != set(_OFFICIAL_CALENDAR_INDEX_COLUMNS):
        raise ValueError("official calendar schema drift: resolution index set mismatch")
    index_attribute_names = _catalog_attribute_names(cursor, _OFFICIAL_CALENDAR_TABLES)
    index_collations = _catalog_attribute_type_collations(cursor, _OFFICIAL_CALENDAR_TABLES)
    for row in index_rows:
        (
            index_oid,
            index_name,
            table,
            access_method,
            unique,
            key_count,
            total_count,
            key_vector,
            key_options,
            opclass_vector,
            collation_vector,
            nulls_not_distinct,
            predicate,
            options,
            valid,
            ready,
            owner,
        ) = row
        expected_table, expected_keys = _OFFICIAL_CALENDAR_INDEX_COLUMNS[str(index_name)]
        keys, included = _index_keys(
            cursor,
            int(index_oid),
            str(table),
            key_vector,
            int(key_count),
            int(total_count),
            index_attribute_names,
        )
        expected_collations = tuple(
            index_collations[(expected_table, column)] for column in expected_keys
        )
        actual_opclasses = _index_opclass_specs(cursor, opclass_vector, int(key_count))
        expected_opclasses = tuple(
            (
                "pg_catalog",
                {
                    "uuid": "uuid_ops",
                    "text": "text_ops",
                    "integer": "int4_ops",
                    "date": "date_ops",
                    "timestamp with time zone": "timestamptz_ops",
                }[
                    next(
                        data_type
                        for column_name, data_type, _nullable, _default in (
                            _OFFICIAL_CALENDAR_COLUMNS[expected_table]
                        )
                        if column_name == column
                    )
                ],
                "btree",
            )
            for column in expected_keys
        )
        if (
            str(table) != expected_table
            or str(access_method) != "btree"
            or bool(unique)
            or int(key_count) != len(expected_keys)
            or int(total_count) != len(expected_keys)
            or keys != expected_keys
            or included
            or _int_vector(key_options) != (0,) * len(expected_keys)
            or actual_opclasses != expected_opclasses
            or _int_vector(collation_vector) != expected_collations
            or bool(nulls_not_distinct)
            or predicate is not None
            or tuple(options or ())
            or owner is not None
            or not bool(valid)
            or not bool(ready)
        ):
            raise ValueError(f"official calendar schema drift: index {index_name}")


_CALENDAR_SNAPSHOT_TABLES = (
    "calendar_snapshot_versions",
    "calendar_snapshot_holidays",
    "calendar_snapshot_latest",
    "calendar_snapshot_corrections",
    "calendar_snapshot_audit",
)
_CALENDAR_SNAPSHOT_COLUMNS: dict[str, tuple[tuple[str, str, bool, bool], ...]] = {
    "calendar_snapshot_versions": (
        ("version_id", "uuid", False, False),
        ("source", "text", False, False),
        ("exchange", "text", False, False),
        ("year", "integer", False, False),
        ("fingerprint", "bytea", False, False),
        ("operation_key_hash", "bytea", True, False),
        ("persisted_at", "timestamp with time zone", False, True),
    ),
    "calendar_snapshot_holidays": (
        ("version_id", "uuid", False, False),
        ("source", "text", False, False),
        ("exchange", "text", False, False),
        ("year", "integer", False, False),
        ("ordinal", "integer", False, False),
        ("holiday_date", "date", False, False),
        ("reason", "text", False, False),
        ("note", "text", True, False),
    ),
    "calendar_snapshot_latest": (
        ("source", "text", False, False),
        ("exchange", "text", False, False),
        ("year", "integer", False, False),
        ("version_id", "uuid", False, False),
    ),
    "calendar_snapshot_corrections": (
        ("correction_id", "uuid", False, False),
        ("version_id", "uuid", False, False),
        ("source", "text", False, False),
        ("exchange", "text", False, False),
        ("year", "integer", False, False),
        ("correction_date", "date", False, False),
        ("reason", "text", False, False),
        ("note", "text", False, False),
        ("author", "text", False, False),
        ("persisted_at", "timestamp with time zone", False, True),
    ),
    "calendar_snapshot_audit": (
        ("audit_id", "uuid", False, False),
        ("version_id", "uuid", False, False),
        ("source", "text", False, False),
        ("exchange", "text", False, False),
        ("year", "integer", False, False),
        ("kind", "text", False, False),
        ("entry", "text", False, False),
        ("persisted_at", "timestamp with time zone", False, True),
    ),
}
_CALENDAR_SNAPSHOT_CONSTRAINTS = frozenset(
    {
        "calendar_snapshot_versions_pkey",
        "calendar_snapshot_versions_source_ck",
        "calendar_snapshot_versions_exchange_ck",
        "calendar_snapshot_versions_year_ck",
        "calendar_snapshot_versions_fingerprint_ck",
        "calendar_snapshot_versions_operation_hash_ck",
        "calendar_snapshot_versions_scope_uk",
        "calendar_snapshot_versions_operation_key_uk",
        "calendar_snapshot_holidays_pkey",
        "calendar_snapshot_holidays_version_scope_fkey",
        "calendar_snapshot_holidays_source_ck",
        "calendar_snapshot_holidays_exchange_ck",
        "calendar_snapshot_holidays_year_ck",
        "calendar_snapshot_holidays_ordinal_ck",
        "calendar_snapshot_holidays_reason_ck",
        "calendar_snapshot_holidays_date_year_ck",
        "calendar_snapshot_latest_pkey",
        "calendar_snapshot_latest_version_scope_fkey",
        "calendar_snapshot_latest_source_ck",
        "calendar_snapshot_latest_exchange_ck",
        "calendar_snapshot_latest_year_ck",
        "calendar_snapshot_corrections_pkey",
        "calendar_snapshot_corrections_version_scope_fkey",
        "calendar_snapshot_corrections_source_ck",
        "calendar_snapshot_corrections_exchange_ck",
        "calendar_snapshot_corrections_year_ck",
        "calendar_snapshot_corrections_date_year_ck",
        "calendar_snapshot_audit_pkey",
        "calendar_snapshot_audit_version_scope_fkey",
        "calendar_snapshot_audit_source_ck",
        "calendar_snapshot_audit_exchange_ck",
        "calendar_snapshot_audit_year_ck",
    }
)


def _calendar_primary(table: str, name: str, *columns: str) -> _ConstraintSpec:
    return _ConstraintSpec(table, name, "p", columns, no_inherit=True)


def _calendar_unique(table: str, name: str, *columns: str) -> _ConstraintSpec:
    return _ConstraintSpec(table, name, "u", columns, no_inherit=True)


def _calendar_check(
    table: str,
    name: str,
    columns: tuple[str, ...],
    expression: str,
) -> _ConstraintSpec:
    return _ConstraintSpec(
        table,
        name,
        "c",
        columns,
        expression=_canonical_catalog_expression(expression),
    )


def _calendar_foreign(
    table: str,
    name: str,
    columns: tuple[str, ...],
    referenced_columns: tuple[str, ...],
) -> _ConstraintSpec:
    return _ConstraintSpec(
        table,
        name,
        "f",
        columns,
        "calendar_snapshot_versions",
        referenced_columns,
        "s",
        "r",
        "r",
        referenced_schema=_CURRENT_SCHEMA_SENTINEL,
        no_inherit=True,
    )


_CALENDAR_EXPECTED_CONSTRAINTS = (
    _calendar_primary(
        "calendar_snapshot_versions", "calendar_snapshot_versions_pkey", "version_id"
    ),
    _calendar_check(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_source_ck",
        ("source",),
        "source <> ''::text",
    ),
    _calendar_check(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_year_ck",
        ("year",),
        "year >= 1 AND year <= 9999",
    ),
    _calendar_check(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_fingerprint_ck",
        ("fingerprint",),
        "octet_length(fingerprint) = 32",
    ),
    _calendar_check(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_operation_hash_ck",
        ("operation_key_hash",),
        "operation_key_hash IS NULL OR octet_length(operation_key_hash) = 32",
    ),
    _calendar_unique(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_scope_uk",
        "version_id",
        "source",
        "exchange",
        "year",
    ),
    _calendar_unique(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_operation_key_uk",
        "operation_key_hash",
    ),
    _calendar_primary(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_pkey",
        "version_id",
        "ordinal",
    ),
    _calendar_foreign(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_version_scope_fkey",
        ("version_id", "source", "exchange", "year"),
        ("version_id", "source", "exchange", "year"),
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_source_ck",
        ("source",),
        "source <> ''::text",
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_year_ck",
        ("year",),
        "year >= 1 AND year <= 9999",
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_ordinal_ck",
        ("ordinal",),
        "ordinal >= 0",
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_reason_ck",
        ("reason",),
        "reason = ANY (ARRAY['PUBLIC_HOLIDAY'::text, 'TEMPORARY_CLOSURE'::text, 'SPECIAL'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_date_year_ck",
        ("year", "holiday_date"),
        "year = EXTRACT(year FROM holiday_date)::integer",
    ),
    _calendar_primary(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_pkey",
        "source",
        "exchange",
        "year",
    ),
    _calendar_foreign(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_version_scope_fkey",
        ("version_id", "source", "exchange", "year"),
        ("version_id", "source", "exchange", "year"),
    ),
    _calendar_check(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_source_ck",
        ("source",),
        "source <> ''::text",
    ),
    _calendar_check(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_year_ck",
        ("year",),
        "year >= 1 AND year <= 9999",
    ),
    _calendar_primary(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_pkey",
        "correction_id",
    ),
    _calendar_foreign(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_version_scope_fkey",
        ("version_id", "source", "exchange", "year"),
        ("version_id", "source", "exchange", "year"),
    ),
    _calendar_check(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_source_ck",
        ("source",),
        "source <> ''::text",
    ),
    _calendar_check(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_year_ck",
        ("year",),
        "year >= 1 AND year <= 9999",
    ),
    _calendar_check(
        "calendar_snapshot_corrections",
        "calendar_snapshot_corrections_date_year_ck",
        ("year", "correction_date"),
        "year = EXTRACT(year FROM correction_date)::integer",
    ),
    _calendar_primary("calendar_snapshot_audit", "calendar_snapshot_audit_pkey", "audit_id"),
    _calendar_foreign(
        "calendar_snapshot_audit",
        "calendar_snapshot_audit_version_scope_fkey",
        ("version_id", "source", "exchange", "year"),
        ("version_id", "source", "exchange", "year"),
    ),
    _calendar_check(
        "calendar_snapshot_audit",
        "calendar_snapshot_audit_source_ck",
        ("source",),
        "source <> ''::text",
    ),
    _calendar_check(
        "calendar_snapshot_audit",
        "calendar_snapshot_audit_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _calendar_check(
        "calendar_snapshot_audit",
        "calendar_snapshot_audit_year_ck",
        ("year",),
        "year >= 1 AND year <= 9999",
    ),
)


_CALENDAR_COLUMN_TYPES = {
    (table, column): data_type
    for table, columns in _CALENDAR_SNAPSHOT_COLUMNS.items()
    for column, data_type, _nullable, _has_default in columns
}
_CALENDAR_INDEX_OPCLASSES = {
    "uuid": "uuid_ops",
    "text": "text_ops",
    "integer": "int4_ops",
    "bytea": "bytea_ops",
}
_CALENDAR_IMMUTABLE_FUNCTION_BODY = (
    "begin raise exception 'calendar snapshot history is immutable'; end;"
)


def _canonical_function_body(value: object) -> str:
    return " ".join(str(value).split()).lower().replace("( ", "(").replace(" )", ")")


def _calendar_constraint_index(table: str, name: str, *columns: str) -> _IndexSpec:
    return _IndexSpec(
        table,
        name,
        "btree",
        columns,
        unique=True,
        key_opclasses=tuple(
            (
                "pg_catalog",
                _CALENDAR_INDEX_OPCLASSES[_CALENDAR_COLUMN_TYPES[(table, column)]],
                "btree",
            )
            for column in columns
        ),
        owner=name,
    )


_CALENDAR_EXPECTED_INDEXES = (
    _calendar_constraint_index(
        "calendar_snapshot_versions", "calendar_snapshot_versions_pkey", "version_id"
    ),
    _calendar_constraint_index(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_scope_uk",
        "version_id",
        "source",
        "exchange",
        "year",
    ),
    _calendar_constraint_index(
        "calendar_snapshot_versions",
        "calendar_snapshot_versions_operation_key_uk",
        "operation_key_hash",
    ),
    _calendar_constraint_index(
        "calendar_snapshot_holidays",
        "calendar_snapshot_holidays_pkey",
        "version_id",
        "ordinal",
    ),
    _calendar_constraint_index(
        "calendar_snapshot_latest",
        "calendar_snapshot_latest_pkey",
        "source",
        "exchange",
        "year",
    ),
    _calendar_constraint_index(
        "calendar_snapshot_corrections", "calendar_snapshot_corrections_pkey", "correction_id"
    ),
    _calendar_constraint_index(
        "calendar_snapshot_audit", "calendar_snapshot_audit_pkey", "audit_id"
    ),
)
_CALENDAR_SNAPSHOT_TRIGGERS = frozenset(
    {
        ("calendar_snapshot_versions", "calendar_snapshot_versions_immutable"),
        ("calendar_snapshot_holidays", "calendar_snapshot_holidays_immutable"),
        ("calendar_snapshot_corrections", "calendar_snapshot_corrections_immutable"),
        ("calendar_snapshot_audit", "calendar_snapshot_audit_immutable"),
    }
)


_CALENDAR_QUALITY_TABLES = (
    "calendar_quality_assessments",
    "calendar_quality_assessment_sources",
    "calendar_quality_assessment_days",
    "calendar_quality_missing_dates",
    "calendar_quality_alerts",
    "calendar_quality_alert_sources",
    "calendar_quality_manual_overlays",
    "calendar_quality_audit",
)
_CALENDAR_QUALITY_COLUMNS: dict[str, tuple[tuple[str, str, bool, bool], ...]] = {
    "calendar_quality_assessments": (
        ("assessment_id", "uuid", False, False),
        ("operation_id", "text", False, False),
        ("operation_key_hash", "bytea", False, False),
        ("content_fingerprint", "bytea", False, False),
        ("exchange", "text", False, False),
        ("calendar_year", "integer", False, False),
        ("status", "text", False, False),
        ("coverage_level", "text", False, False),
        ("confirmed_through", "date", True, False),
        ("detected_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("source_count", "integer", False, False),
        ("missing_date_count", "integer", False, False),
        ("conflict_date_count", "integer", False, False),
        ("confirmed_days_json", "jsonb", False, False),
        ("created_at", "timestamp with time zone", False, True),
    ),
    "calendar_quality_assessment_sources": (
        ("assessment_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("source_id", "uuid", False, False),
        ("source_kind", "text", False, False),
        ("source_name", "text", False, False),
        ("exchange", "text", False, False),
        ("calendar_year", "integer", False, False),
        ("coverage_level", "text", False, False),
        ("confirmed_through", "date", True, False),
        ("captured_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("content_fingerprint", "bytea", False, False),
        ("source_fingerprint", "bytea", False, False),
        ("evidence_links_json", "jsonb", False, False),
        ("days_json", "jsonb", False, False),
        ("closures_json", "jsonb", False, False),
    ),
    "calendar_quality_assessment_days": (
        ("assessment_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("calendar_date", "date", False, False),
        ("is_trading_day", "boolean", False, False),
        ("reason", "text", True, False),
    ),
    "calendar_quality_missing_dates": (
        ("assessment_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("calendar_date", "date", False, False),
    ),
    "calendar_quality_alerts": (
        ("alert_id", "uuid", False, False),
        ("assessment_id", "uuid", False, False),
        ("kind", "text", False, False),
        ("calendar_date", "date", True, False),
        ("detail_code", "text", False, False),
        ("detected_at", "timestamp with time zone", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("source_count", "integer", False, False),
        ("evidence_fingerprint", "bytea", False, False),
    ),
    "calendar_quality_alert_sources": (
        ("alert_id", "uuid", False, False),
        ("ordinal", "integer", False, False),
        ("source_id", "uuid", False, False),
        ("evidence_ref", "text", False, False),
        ("artifact_sha256", "bytea", False, False),
    ),
    "calendar_quality_manual_overlays": (
        ("overlay_id", "uuid", False, False),
        ("operation_id", "text", False, False),
        ("operation_key_hash", "bytea", False, False),
        ("assessment_id", "uuid", False, False),
        ("source_id", "uuid", False, False),
        ("calendar_date", "date", False, False),
        ("decision", "text", False, False),
        ("reason_code", "text", False, False),
        ("note", "text", False, False),
        ("author", "text", False, False),
        ("available_at", "timestamp with time zone", False, False),
        ("created_at", "timestamp with time zone", False, True),
    ),
    "calendar_quality_audit": (
        ("audit_id", "uuid", False, False),
        ("assessment_id", "uuid", False, False),
        ("operation_key_hash", "bytea", False, False),
        ("action", "text", False, False),
        ("entry", "text", False, False),
        ("created_at", "timestamp with time zone", False, True),
    ),
}


def _quality_primary(table: str, name: str, *columns: str) -> _ConstraintSpec:
    return _ConstraintSpec(table, name, "p", columns, no_inherit=True)


def _quality_unique(table: str, name: str, *columns: str) -> _ConstraintSpec:
    return _ConstraintSpec(table, name, "u", columns, no_inherit=True)


def _quality_check(
    table: str,
    name: str,
    columns: tuple[str, ...],
    expression: str,
) -> _ConstraintSpec:
    return _ConstraintSpec(
        table,
        name,
        "c",
        columns,
        expression=_canonical_catalog_expression(expression),
    )


def _quality_foreign(
    table: str,
    name: str,
    columns: tuple[str, ...],
    referenced_table: str,
    referenced_columns: tuple[str, ...],
) -> _ConstraintSpec:
    return _ConstraintSpec(
        table,
        name,
        "f",
        columns,
        referenced_table,
        referenced_columns,
        "s",
        "r",
        "r",
        referenced_schema=_CURRENT_SCHEMA_SENTINEL,
        no_inherit=True,
    )


_CALENDAR_QUALITY_EXPECTED_CONSTRAINTS = (
    _quality_primary(
        "calendar_quality_assessments", "calendar_quality_assessments_pkey", "assessment_id"
    ),
    _quality_unique(
        "calendar_quality_assessments",
        "calendar_quality_assessments_operation_uk",
        "operation_key_hash",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_operation_id_ck",
        ("operation_id",),
        "operation_id <> ''",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_operation_hash_ck",
        ("operation_key_hash",),
        "octet_length(operation_key_hash) = 32",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_content_hash_ck",
        ("content_fingerprint",),
        "octet_length(content_fingerprint) = 32",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_year_ck",
        ("calendar_year",),
        "calendar_year >= 1 AND calendar_year <= 9999",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_status_ck",
        ("status",),
        "status = ANY (ARRAY['COMPLETE'::text, 'INDETERMINATE'::text, "
        "'MISSING_COVERAGE'::text, 'CONFLICT'::text])",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_coverage_ck",
        ("coverage_level",),
        "coverage_level = ANY (ARRAY['UNKNOWN'::text, 'INDETERMINATE'::text, "
        "'CONFIRMED_HORIZON'::text, 'FINAL_YEAR'::text])",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_confirmed_ck",
        ("coverage_level", "confirmed_through", "calendar_year"),
        "(coverage_level = ANY (ARRAY['UNKNOWN'::text, 'INDETERMINATE'::text]) "
        "AND confirmed_through IS NULL) OR "
        "(coverage_level = 'CONFIRMED_HORIZON'::text AND confirmed_through >= "
        "make_date(calendar_year, 1, 1) AND confirmed_through <= "
        "make_date(calendar_year, 12, 31)) OR "
        "(coverage_level = 'FINAL_YEAR'::text AND confirmed_through = "
        "make_date(calendar_year, 12, 31))",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_window_ck",
        ("detected_at", "available_at"),
        "detected_at <= available_at",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_counts_ck",
        ("source_count", "missing_date_count", "conflict_date_count"),
        "source_count >= 0 AND missing_date_count >= 0 AND conflict_date_count >= 0",
    ),
    _quality_check(
        "calendar_quality_assessments",
        "calendar_quality_assessments_confirmed_days_ck",
        ("confirmed_days_json",),
        "jsonb_typeof(confirmed_days_json) = 'array'",
    ),
    _quality_unique(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_id_uk",
        "assessment_id",
        "source_id",
    ),
    _quality_primary(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_pkey",
        "assessment_id",
        "ordinal",
    ),
    _quality_foreign(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_ordinal_ck",
        ("ordinal",),
        "ordinal >= 0",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_kind_ck",
        ("source_kind",),
        "source_kind = ANY (ARRAY['SPARSE'::text, 'OFFICIAL'::text, 'SECONDARY'::text])",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_exchange_ck",
        ("exchange",),
        "exchange = ANY (ARRAY['SH'::text, 'SZ'::text, 'BJ'::text])",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_year_ck",
        ("calendar_year",),
        "calendar_year >= 1 AND calendar_year <= 9999",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_coverage_ck",
        ("coverage_level",),
        "coverage_level = ANY (ARRAY['UNKNOWN'::text, 'INDETERMINATE'::text, "
        "'CONFIRMED_HORIZON'::text, 'FINAL_YEAR'::text])",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_hash_ck",
        ("content_fingerprint",),
        "octet_length(content_fingerprint) = 32",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_source_hash_ck",
        ("source_fingerprint",),
        "octet_length(source_fingerprint) = 32",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_links_ck",
        ("evidence_links_json",),
        "jsonb_typeof(evidence_links_json) = 'array' AND "
        "jsonb_array_length(evidence_links_json) > 0",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_days_ck",
        ("days_json",),
        "jsonb_typeof(days_json) = 'array'",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_closures_ck",
        ("closures_json",),
        "jsonb_typeof(closures_json) = 'array'",
    ),
    _quality_check(
        "calendar_quality_assessment_sources",
        "calendar_quality_assessment_sources_window_ck",
        ("captured_at", "available_at"),
        "captured_at <= available_at",
    ),
    _quality_primary(
        "calendar_quality_assessment_days",
        "calendar_quality_assessment_days_pkey",
        "assessment_id",
        "ordinal",
    ),
    _quality_unique(
        "calendar_quality_assessment_days",
        "calendar_quality_assessment_days_date_uk",
        "assessment_id",
        "calendar_date",
    ),
    _quality_foreign(
        "calendar_quality_assessment_days",
        "calendar_quality_assessment_days_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_check(
        "calendar_quality_assessment_days",
        "calendar_quality_assessment_days_ordinal_ck",
        ("ordinal",),
        "ordinal >= 0",
    ),
    _quality_check(
        "calendar_quality_assessment_days",
        "calendar_quality_assessment_days_reason_ck",
        ("reason",),
        "reason IS NULL OR reason = ANY (ARRAY['WEEKEND'::text, 'PUBLIC_HOLIDAY'::text, "
        "'TEMPORARY_CLOSURE'::text, 'SPECIAL'::text])",
    ),
    _quality_primary(
        "calendar_quality_missing_dates",
        "calendar_quality_missing_dates_pkey",
        "assessment_id",
        "ordinal",
    ),
    _quality_unique(
        "calendar_quality_missing_dates",
        "calendar_quality_missing_dates_date_uk",
        "assessment_id",
        "calendar_date",
    ),
    _quality_foreign(
        "calendar_quality_missing_dates",
        "calendar_quality_missing_dates_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_check(
        "calendar_quality_missing_dates",
        "calendar_quality_missing_dates_ordinal_ck",
        ("ordinal",),
        "ordinal >= 0",
    ),
    _quality_primary("calendar_quality_alerts", "calendar_quality_alerts_pkey", "alert_id"),
    _quality_foreign(
        "calendar_quality_alerts",
        "calendar_quality_alerts_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_check(
        "calendar_quality_alerts",
        "calendar_quality_alerts_kind_ck",
        ("kind",),
        "kind = ANY (ARRAY['MISSING_COVERAGE'::text, 'SOURCE_CONFLICT'::text, "
        "'TEMPORARY_CLOSURE'::text])",
    ),
    _quality_check(
        "calendar_quality_alerts",
        "calendar_quality_alerts_detail_ck",
        ("detail_code",),
        "detail_code = ANY (ARRAY['DATE_NOT_CONFIRMED'::text, "
        "'DAY_STATUS_DISAGREEMENT'::text, 'EXPLICIT_CLOSURE_EVIDENCE'::text])",
    ),
    _quality_check(
        "calendar_quality_alerts",
        "calendar_quality_alerts_hash_ck",
        ("evidence_fingerprint",),
        "octet_length(evidence_fingerprint) = 32",
    ),
    _quality_check(
        "calendar_quality_alerts",
        "calendar_quality_alerts_counts_ck",
        ("source_count",),
        "source_count >= 0",
    ),
    _quality_check(
        "calendar_quality_alerts",
        "calendar_quality_alerts_window_ck",
        ("detected_at", "available_at"),
        "detected_at <= available_at",
    ),
    _quality_unique(
        "calendar_quality_alerts",
        "calendar_quality_alerts_identity_uk",
        "assessment_id",
        "kind",
        "calendar_date",
        "evidence_fingerprint",
    ),
    _quality_primary(
        "calendar_quality_alert_sources",
        "calendar_quality_alert_sources_pkey",
        "alert_id",
        "ordinal",
    ),
    _quality_foreign(
        "calendar_quality_alert_sources",
        "calendar_quality_alert_sources_alert_fkey",
        ("alert_id",),
        "calendar_quality_alerts",
        ("alert_id",),
    ),
    _quality_check(
        "calendar_quality_alert_sources",
        "calendar_quality_alert_sources_ordinal_ck",
        ("ordinal",),
        "ordinal >= 0",
    ),
    _quality_check(
        "calendar_quality_alert_sources",
        "calendar_quality_alert_sources_ref_ck",
        ("evidence_ref",),
        "evidence_ref <> ''",
    ),
    _quality_check(
        "calendar_quality_alert_sources",
        "calendar_quality_alert_sources_digest_ck",
        ("artifact_sha256",),
        "octet_length(artifact_sha256) = 32",
    ),
    _quality_primary(
        "calendar_quality_manual_overlays", "calendar_quality_manual_overlays_pkey", "overlay_id"
    ),
    _quality_unique(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_operation_uk",
        "operation_key_hash",
    ),
    _quality_check(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_operation_id_ck",
        ("operation_id",),
        "operation_id <> ''",
    ),
    _quality_check(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_operation_hash_ck",
        ("operation_key_hash",),
        "octet_length(operation_key_hash) = 32",
    ),
    _quality_foreign(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_foreign(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_source_fkey",
        ("assessment_id", "source_id"),
        "calendar_quality_assessment_sources",
        ("assessment_id", "source_id"),
    ),
    _quality_check(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_decision_ck",
        ("decision",),
        "decision = ANY (ARRAY['TRADING'::text, 'NON_TRADING'::text, 'REVIEW'::text])",
    ),
    _quality_check(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_reason_ck",
        ("reason_code",),
        "reason_code <> ''",
    ),
    _quality_check(
        "calendar_quality_manual_overlays",
        "calendar_quality_manual_overlays_author_ck",
        ("author",),
        "author <> ''",
    ),
    _quality_primary("calendar_quality_audit", "calendar_quality_audit_pkey", "audit_id"),
    _quality_foreign(
        "calendar_quality_audit",
        "calendar_quality_audit_assessment_fkey",
        ("assessment_id",),
        "calendar_quality_assessments",
        ("assessment_id",),
    ),
    _quality_check(
        "calendar_quality_audit",
        "calendar_quality_audit_operation_hash_ck",
        ("operation_key_hash",),
        "octet_length(operation_key_hash) = 32",
    ),
    _quality_check(
        "calendar_quality_audit",
        "calendar_quality_audit_action_ck",
        ("action",),
        "action = ANY (ARRAY['ASSESSMENT_CREATED'::text, 'MANUAL_OVERLAY_CREATED'::text])",
    ),
    _quality_check(
        "calendar_quality_audit", "calendar_quality_audit_entry_ck", ("entry",), "entry <> ''"
    ),
)

_CALENDAR_QUALITY_INDEX_TYPES = {
    (table, column): data_type
    for table, columns in _CALENDAR_QUALITY_COLUMNS.items()
    for column, data_type, _nullable, _has_default in columns
}
_CALENDAR_QUALITY_INDEX_OPCLASSES = {
    "uuid": "uuid_ops",
    "text": "text_ops",
    "integer": "int4_ops",
    "date": "date_ops",
    "bytea": "bytea_ops",
}


def _quality_constraint_index(table: str, name: str, *columns: str) -> _IndexSpec:
    return _IndexSpec(
        table,
        name,
        "btree",
        columns,
        unique=True,
        key_opclasses=tuple(
            (
                "pg_catalog",
                _CALENDAR_QUALITY_INDEX_OPCLASSES[_CALENDAR_QUALITY_INDEX_TYPES[(table, column)]],
                "btree",
            )
            for column in columns
        ),
        owner=name,
    )


_CALENDAR_QUALITY_EXPECTED_INDEXES = tuple(
    _quality_constraint_index(spec.table, spec.name, *spec.columns)
    for spec in _CALENDAR_QUALITY_EXPECTED_CONSTRAINTS
    if spec.contype in {"p", "u"}
)
_CALENDAR_QUALITY_IMMUTABLE_FUNCTION_BODY = (
    "begin raise exception 'calendar quality history is immutable'; end;"
)
_CALENDAR_QUALITY_NO_TRUNCATE_FUNCTION_BODY = (
    "begin raise exception 'calendar quality history is immutable'; end;"
)
_CALENDAR_QUALITY_TRIGGERS = frozenset(
    {(table, f"{table}_immutable") for table in _CALENDAR_QUALITY_TABLES}
)
_CALENDAR_QUALITY_TRUNCATE_TRIGGERS = frozenset(
    {(table, f"{table}_no_truncate") for table in _CALENDAR_QUALITY_TABLES}
)
_CALENDAR_QUALITY_V4_READ_TABLES = (
    "official_calendar_scan_runs",
    "official_calendar_evidence_refs",
    "official_calendar_snapshots",
    "official_calendar_snapshot_evidence",
    "official_calendar_snapshot_days",
)
_CALENDAR_QUALITY_ALLOWED_SHARED_RELATIONS = frozenset(
    {
        *_CALENDAR_QUALITY_TABLES,
        *_CALENDAR_QUALITY_V4_READ_TABLES,
        "data_worker_schema_migrations",
    }
)
_CALENDAR_QUALITY_TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)
_CALENDAR_QUALITY_SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
_CALENDAR_QUALITY_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_CALENDAR_QUALITY_DEFAULT_ROLES = CalendarQualityRoles()


def _calendar_quality_identifier(value: str, field_name: str) -> str:
    if type(value) is not str or _CALENDAR_QUALITY_ROLE_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _calendar_quality_schema_name(schema: str) -> str:
    return _calendar_quality_identifier(schema, "calendar quality schema")


def _calendar_quality_role_contract(roles: CalendarQualityRoles) -> CalendarQualityRoles:
    if type(roles) is not CalendarQualityRoles:
        raise ValueError("calendar quality role contract is invalid")
    for field_name in ("owner", "migrator", "runtime", "reader"):
        _calendar_quality_identifier(
            getattr(roles, field_name), f"calendar quality role {field_name}"
        )
    if len(set(roles)) != 4:
        raise ValueError("calendar quality role contract is invalid")
    return roles


def _calendar_quality_context(
    cursor: Any,
    schema: str,
    *,
    current_user: str | None = None,
) -> None:
    schema = _calendar_quality_schema_name(schema)
    cursor.execute("SELECT current_schema(), current_setting('search_path')")
    row = cursor.fetchone()
    if row is None:
        raise ValueError("calendar quality schema context is unavailable")
    observed_schema = str(row[0])
    observed_search_path = str(row[1]).replace('"', "").replace(" ", "")
    expected_search_path = f"{schema},pg_catalog,pg_temp"
    if observed_schema != schema or observed_search_path != expected_search_path:
        raise ValueError("calendar quality schema context is invalid")
    if current_user is not None:
        cursor.execute("SELECT CURRENT_USER")
        identity = cursor.fetchone()
        if identity is None or str(identity[0]) != current_user:
            raise ValueError("calendar quality database role is invalid")


def _set_calendar_quality_search_path(cursor: Any, schema: str) -> None:
    """Keep permanent relations ahead of the implicit temporary namespace."""

    schema = _calendar_quality_schema_name(schema)
    cursor.execute(
        "SELECT pg_catalog.set_config('search_path', %s, TRUE)",
        (f'"{schema}", pg_catalog, pg_temp',),
    )


def _verify_calendar_quality_role_attributes(
    cursor: Any,
    roles: CalendarQualityRoles,
) -> None:
    roles = _calendar_quality_role_contract(roles)
    names = list(roles)
    cursor.execute(
        "SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolcreatedb, "
        "rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
        (names,),
    )
    rows = cursor.fetchall()
    if len(rows) != len(names) or {str(row[0]) for row in rows} != set(names):
        raise ValueError("calendar quality role contract is invalid")
    login_roles = {roles.migrator, roles.runtime}
    for row in rows:
        name = str(row[0])
        if (
            bool(row[1]) != (name in login_roles)
            or bool(row[2])
            or bool(row[3])
            or bool(row[4])
            or bool(row[5])
            or bool(row[6])
            or bool(row[7])
        ):
            raise ValueError("calendar quality role contract is invalid")


def _verify_calendar_quality_membership(
    cursor: Any,
    roles: CalendarQualityRoles,
    *,
    migration_window: bool,
) -> None:
    names = list(roles)
    cursor.execute(
        "SELECT member.rolname, granted.rolname, m.inherit_option, "
        "m.set_option, m.admin_option "
        "FROM pg_catalog.pg_auth_members AS m "
        "JOIN pg_catalog.pg_roles AS member ON member.oid = m.member "
        "JOIN pg_catalog.pg_roles AS granted ON granted.oid = m.roleid "
        "WHERE member.rolname = ANY(%s) OR granted.rolname = ANY(%s)",
        (names, names),
    )
    observed = {
        (str(row[0]), str(row[1]), bool(row[2]), bool(row[3]), bool(row[4]))
        for row in cursor.fetchall()
    }
    expected: set[tuple[str, str, bool, bool, bool]] = (
        {(roles.migrator, roles.owner, False, True, False)} if migration_window else set()
    )
    if observed != expected:
        raise ValueError("calendar quality role membership is invalid")


def _verify_calendar_quality_roles(
    cursor: Any,
    roles: CalendarQualityRoles,
    *,
    migration_window: bool,
) -> None:
    _verify_calendar_quality_role_attributes(cursor, roles)
    _verify_calendar_quality_membership(cursor, roles, migration_window=migration_window)


def _calendar_quality_acl_entries(
    cursor: Any,
    statement: str,
    parameters: tuple[object, ...],
) -> set[tuple[str, str, bool, str]]:
    cursor.execute(statement, parameters)
    return {(str(row[1]), str(row[2]), bool(row[3]), str(row[0])) for row in cursor.fetchall()}


def _calendar_quality_shared_acl_entries(
    entries: set[tuple[str, str, bool, str]],
    roles: CalendarQualityRoles,
) -> set[tuple[str, str, bool, str]]:
    """Select only PUBLIC/CQ entries from an ACL on a shared object."""

    role_names = set(_calendar_quality_role_contract(roles))
    return {
        entry
        for entry in entries
        if entry[0] == "PUBLIC" or entry[0] in role_names or entry[3] in role_names
    }


def _verify_calendar_quality_acl_entries(
    entries: set[tuple[str, str, bool, str]],
    *,
    owner: str,
    allowed: set[tuple[str, str, bool]],
    grantor: str,
    subject: str,
    owner_privileges: set[str] | None = None,
) -> None:
    observed: set[tuple[str, str, bool]] = set()
    for grantee, privilege, grantable, entry_grantor in entries:
        if grantee == owner and entry_grantor == owner:
            if owner_privileges is None:
                continue
            if privilege not in owner_privileges or grantable:
                raise ValueError(f"calendar quality schema ACL drift: {subject}")
            observed.add((grantee, privilege, grantable))
            continue
        candidate = (grantee, privilege, grantable)
        if entry_grantor != grantor or candidate not in allowed:
            raise ValueError(f"calendar quality schema ACL drift: {subject}")
        observed.add(candidate)
    expected = set(allowed)
    if owner_privileges is not None:
        expected.update((owner, privilege, False) for privilege in owner_privileges)
    if observed != expected:
        raise ValueError(f"calendar quality schema ACL drift: {subject}")


def _verify_calendar_quality_object_owners(
    cursor: Any,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    placeholders = ", ".join("%s" for _ in _CALENDAR_QUALITY_TABLES)
    cursor.execute(
        "SELECT c.relname, c.relkind, c.relpersistence, c.relrowsecurity, "
        "c.relforcerowsecurity, pg_catalog.pg_get_userbyid(c.relowner) "
        "FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        f"WHERE n.nspname=%s AND c.relname IN ({placeholders})",
        (schema, *_CALENDAR_QUALITY_TABLES),
    )
    rows = cursor.fetchall()
    if {str(row[0]) for row in rows} != set(_CALENDAR_QUALITY_TABLES):
        raise ValueError("calendar quality schema ACL drift: table owners")
    for row in rows:
        if (
            str(row[1]) != "r"
            or str(row[2]) != "p"
            or bool(row[3])
            or bool(row[4])
            or str(row[5]) != roles.owner
        ):
            raise ValueError(f"calendar quality schema ACL drift: table {row[0]}")

    cursor.execute(
        "SELECT p.proname, pg_catalog.pg_get_userbyid(p.proowner) "
        "FROM pg_catalog.pg_proc AS p "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
        "WHERE n.nspname=%s AND p.proname LIKE 'calendar_quality_%%'",
        (schema,),
    )
    function_rows = cursor.fetchall()
    expected_functions = {
        "calendar_quality_history_immutable",
        "calendar_quality_no_truncate",
    }
    if {str(row[0]) for row in function_rows} != expected_functions:
        raise ValueError("calendar quality schema ACL drift: function owners")
    if any(str(row[1]) != roles.owner for row in function_rows):
        raise ValueError("calendar quality schema ACL drift: function owner")


def _verify_calendar_quality_no_column_grants(
    cursor: Any,
    *,
    schema: str,
    table: str,
    roles: CalendarQualityRoles,
    subject: str,
) -> None:
    """Reject column ACLs for CQ principals or PUBLIC on an allowed relation."""

    cursor.execute(
        "SELECT x.grantee FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
        "JOIN pg_catalog.pg_attribute AS a ON a.attrelid=c.oid "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) AS x "
        "WHERE n.nspname=%s AND c.relname=%s "
        "AND a.attnum>0 AND NOT a.attisdropped "
        "AND (x.grantee=0 OR pg_catalog.pg_get_userbyid(x.grantee)=ANY(%s))",
        (schema, table, list(roles)),
    )
    if cursor.fetchall():
        raise ValueError(f"calendar quality schema ACL drift: {subject} column")


def _verify_calendar_quality_runtime_acl(
    cursor: Any,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    roles = _calendar_quality_role_contract(roles)
    _verify_calendar_quality_object_owners(cursor, schema, roles)
    cursor.execute(
        "SELECT pg_catalog.pg_get_userbyid(n.nspowner) "
        "FROM pg_catalog.pg_namespace AS n WHERE n.nspname=%s",
        (schema,),
    )
    schema_owner_row = cursor.fetchone()
    if schema_owner_row is None or schema_owner_row[0] is None:
        raise ValueError("calendar quality schema ACL drift: schema owner")
    schema_owner = str(schema_owner_row[0])
    privileges = ("USAGE", "CREATE")
    expected_schema = {
        (roles.owner, "USAGE", False),
        (roles.runtime, "USAGE", False),
        (roles.reader, "USAGE", False),
    }
    for principal in ("public", roles.migrator, roles.owner, roles.runtime, roles.reader):
        for privilege in privileges:
            cursor.execute(
                "SELECT pg_catalog.has_schema_privilege(%s, %s, %s)",
                (principal, schema, privilege),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("calendar quality schema ACL drift: schema privilege")
            expected = (
                (principal == "public" and False)
                or (principal == roles.owner and privilege == "USAGE")
                or (principal in {roles.runtime, roles.reader} and privilege == "USAGE")
            )
            if bool(row[0]) != expected:
                raise ValueError("calendar quality schema ACL drift: schema privilege")
    _verify_calendar_quality_acl_entries(
        _calendar_quality_shared_acl_entries(
            _calendar_quality_acl_entries(
                cursor,
                "SELECT pg_catalog.pg_get_userbyid(x.grantor), "
                "CASE WHEN x.grantee=0 THEN 'PUBLIC' "
                "ELSE pg_catalog.pg_get_userbyid(x.grantee) END, "
                "x.privilege_type, x.is_grantable "
                "FROM pg_catalog.pg_namespace AS n "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) AS x "
                "WHERE n.nspname=%s",
                (schema,),
            ),
            roles,
        ),
        owner=schema_owner,
        grantor=schema_owner,
        allowed=expected_schema,
        subject="schema",
    )

    table_privileges = (
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
        "MAINTAIN",
    )
    ledger_table = "data_worker_schema_migrations"
    qualified_ledger = f'"{schema}"."{ledger_table}"'
    cursor.execute(
        "SELECT pg_catalog.pg_get_userbyid(c.relowner) "
        "FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p')",
        (schema, ledger_table),
    )
    ledger_owner_row = cursor.fetchone()
    if (
        ledger_owner_row is None
        or ledger_owner_row[0] is None
        or str(ledger_owner_row[0]) in set(roles)
    ):
        raise ValueError("calendar quality schema ACL drift: migration ledger owner")
    for principal in ("public", *roles):
        for privilege in table_privileges:
            cursor.execute(
                "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                (principal, qualified_ledger, privilege),
            )
            ledger_privilege_row = cursor.fetchone()
            if ledger_privilege_row is None or bool(ledger_privilege_row[0]):
                raise ValueError("calendar quality schema ACL drift: migration ledger")
    cursor.execute(
        "SELECT x.grantee FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
        "WHERE n.nspname=%s AND c.relname=%s "
        "AND (x.grantee=0 OR pg_catalog.pg_get_userbyid(x.grantee)=ANY(%s))",
        (schema, ledger_table, list(roles)),
    )
    if cursor.fetchall():
        raise ValueError("calendar quality schema ACL drift: migration ledger")
    _verify_calendar_quality_no_column_grants(
        cursor,
        schema=schema,
        table=ledger_table,
        roles=roles,
        subject="migration ledger",
    )

    runtime_insert_tables = set(_CALENDAR_QUALITY_TABLES) - {"calendar_quality_audit"}
    reader_select_tables = runtime_insert_tables
    for table in _CALENDAR_QUALITY_TABLES:
        qualified = f'"{schema}"."{table}"'
        allowed_table: set[tuple[str, str, bool]] = set()
        for privilege in table_privileges:
            cursor.execute(
                "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                (roles.owner, qualified, privilege),
            )
            owner_row = cursor.fetchone()
            if owner_row is None or not bool(owner_row[0]):
                raise ValueError(f"calendar quality schema ACL drift: table owner {table}")
        for privilege in table_privileges:
            cursor.execute(
                "SELECT pg_catalog.has_table_privilege(%s, %s, %s), "
                "pg_catalog.has_table_privilege(%s, %s, %s), "
                "pg_catalog.has_table_privilege(%s, %s, %s), "
                "pg_catalog.has_table_privilege('public', %s, %s)",
                (
                    roles.runtime,
                    qualified,
                    privilege,
                    roles.reader,
                    qualified,
                    privilege,
                    roles.migrator,
                    qualified,
                    privilege,
                    qualified,
                    privilege,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("calendar quality schema ACL drift: table privilege")
            runtime_allowed = privilege == "INSERT" or (
                privilege == "SELECT" and table != "calendar_quality_audit"
            )
            reader_allowed = privilege == "SELECT" and table in reader_select_tables
            if bool(row[0]) != runtime_allowed or bool(row[1]) != reader_allowed or bool(row[2]):
                raise ValueError(f"calendar quality schema ACL drift: table {table}")
            if bool(row[3]):
                raise ValueError(f"calendar quality schema ACL drift: public table {table}")
            if runtime_allowed:
                allowed_table.add((roles.runtime, privilege, False))
            if reader_allowed:
                allowed_table.add((roles.reader, privilege, False))
        _verify_calendar_quality_acl_entries(
            _calendar_quality_acl_entries(
                cursor,
                "SELECT pg_catalog.pg_get_userbyid(x.grantor), "
                "CASE WHEN x.grantee=0 THEN 'PUBLIC' "
                "ELSE pg_catalog.pg_get_userbyid(x.grantee) END, "
                "x.privilege_type, x.is_grantable "
                "FROM pg_catalog.pg_class AS c "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
                "WHERE n.nspname=%s AND c.relname=%s",
                (schema, table),
            ),
            owner=roles.owner,
            grantor=roles.owner,
            allowed=allowed_table,
            subject=f"table {table}",
            owner_privileges=set(table_privileges),
        )
        _verify_calendar_quality_no_column_grants(
            cursor,
            schema=schema,
            table=table,
            roles=roles,
            subject=f"table {table}",
        )

    for table in _CALENDAR_QUALITY_V4_READ_TABLES:
        qualified = f'"{schema}"."{table}"'
        cursor.execute(
            "SELECT pg_catalog.pg_get_userbyid(c.relowner) "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p')",
            (schema, table),
        )
        owner_row = cursor.fetchone()
        if owner_row is None or owner_row[0] is None:
            raise ValueError(f"calendar quality schema ACL drift: V4 table {table}")
        v4_owner = str(owner_row[0])
        if v4_owner in set(roles):
            raise ValueError(f"calendar quality schema ACL drift: V4 table owner {table}")
        for principal in ("public", roles.migrator, roles.runtime, roles.reader):
            for privilege in table_privileges:
                cursor.execute(
                    "SELECT pg_catalog.has_table_privilege(%s, %s, %s)",
                    (principal, qualified, privilege),
                )
                row = cursor.fetchone()
                if row is None or bool(row[0]) != (
                    principal == roles.runtime and privilege == "SELECT"
                ):
                    raise ValueError(f"calendar quality schema ACL drift: V4 table {table}")
        _verify_calendar_quality_acl_entries(
            _calendar_quality_shared_acl_entries(
                _calendar_quality_acl_entries(
                    cursor,
                    "SELECT pg_catalog.pg_get_userbyid(x.grantor), "
                    "CASE WHEN x.grantee=0 THEN 'PUBLIC' "
                    "ELSE pg_catalog.pg_get_userbyid(x.grantee) END, "
                    "x.privilege_type, x.is_grantable "
                    "FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
                    "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
                    "WHERE n.nspname=%s AND c.relname=%s",
                    (schema, table),
                ),
                roles,
            ),
            owner=v4_owner,
            grantor=v4_owner,
            allowed={(roles.runtime, "SELECT", False)},
            subject=f"V4 table {table}",
        )
        _verify_calendar_quality_no_column_grants(
            cursor,
            schema=schema,
            table=table,
            roles=roles,
            subject=f"V4 table {table}",
        )

    cursor.execute(
        "SELECT c.relname FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind='S' AND c.relname LIKE 'calendar_quality_%%'",
        (schema,),
    )
    if cursor.fetchall():
        raise ValueError("calendar quality schema ACL drift: sequence")

    function_names = ("calendar_quality_history_immutable", "calendar_quality_no_truncate")
    for name in function_names:
        cursor.execute(
            "SELECT p.oid, pg_catalog.pg_get_userbyid(p.proowner) "
            "FROM pg_catalog.pg_proc AS p "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
            "WHERE n.nspname=%s AND p.proname=%s AND p.pronargs=0",
            (schema, name),
        )
        row = cursor.fetchone()
        if row is None or str(row[1]) != roles.owner:
            raise ValueError(f"calendar quality schema ACL drift: function {name}")
        for principal in ("public", roles.migrator, roles.runtime, roles.reader):
            cursor.execute(
                "SELECT pg_catalog.has_function_privilege(%s, %s::pg_catalog.oid, 'EXECUTE')",
                (principal, row[0]),
            )
            privilege_row = cursor.fetchone()
            if privilege_row is None or bool(privilege_row[0]):
                raise ValueError(f"calendar quality schema ACL drift: function {name}")
        cursor.execute(
            "SELECT pg_catalog.has_function_privilege(%s, %s::pg_catalog.oid, 'EXECUTE')",
            (roles.owner, row[0]),
        )
        owner_privilege_row = cursor.fetchone()
        if owner_privilege_row is None or not bool(owner_privilege_row[0]):
            raise ValueError(f"calendar quality schema ACL drift: function owner {name}")
        _verify_calendar_quality_acl_entries(
            _calendar_quality_acl_entries(
                cursor,
                "SELECT pg_catalog.pg_get_userbyid(x.grantor), "
                "CASE WHEN x.grantee=0 THEN 'PUBLIC' "
                "ELSE pg_catalog.pg_get_userbyid(x.grantee) END, "
                "x.privilege_type, x.is_grantable "
                "FROM pg_catalog.pg_proc AS p "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(p.proacl) AS x "
                "WHERE n.nspname=%s AND p.proname=%s AND p.pronargs=0",
                (schema, name),
            ),
            owner=roles.owner,
            grantor=roles.owner,
            allowed=set(),
            subject=f"function {name}",
            owner_privileges={"EXECUTE"},
        )

    cursor.execute(
        "SELECT d.defaclobjtype "
        "FROM pg_catalog.pg_default_acl AS d "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=d.defaclnamespace "
        "WHERE n.nspname=%s "
        "AND d.defaclrole=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s)",
        (schema, roles.owner),
    )
    default_object_types = [str(row[0]) for row in cursor.fetchall()]
    if sorted(default_object_types) != ["f", "r"]:
        raise ValueError("calendar quality schema ACL drift: default privileges")
    cursor.execute(
        "SELECT d.defaclobjtype, "
        "pg_catalog.pg_get_userbyid(x.grantor), "
        "CASE WHEN x.grantee=0 THEN 'PUBLIC' "
        "ELSE pg_catalog.pg_get_userbyid(x.grantee) END, "
        "x.privilege_type, x.is_grantable "
        "FROM pg_catalog.pg_default_acl AS d "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=d.defaclnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) AS x "
        "WHERE n.nspname=%s "
        "AND d.defaclrole=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=%s)",
        (schema, roles.owner),
    )
    observed_defaults = {
        (str(row[0]), str(row[2]), str(row[3]), bool(row[4]), str(row[1]))
        for row in cursor.fetchall()
    }
    expected_defaults = {
        ("r", roles.owner, privilege, False, roles.owner) for privilege in table_privileges
    }
    expected_defaults.update({("f", roles.owner, "EXECUTE", False, roles.owner)})
    if observed_defaults != expected_defaults:
        raise ValueError("calendar quality schema ACL drift: default privileges")


def _calendar_quality_tables(cursor: Any) -> set[str]:
    cursor.execute(
        "SELECT c.relname "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        "AND position('calendar_quality_' IN c.relname) = 1"
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _calendar_quality_orphaned_objects(cursor: Any) -> set[str]:
    cursor.execute(
        "SELECT c.relname "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() "
        "AND position('calendar_quality_' IN c.relname) = 1"
    )
    objects = {str(row[0]) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT p.proname FROM pg_proc AS p "
        "JOIN pg_namespace AS n ON n.oid = p.pronamespace "
        "WHERE n.nspname = current_schema() "
        "AND p.proname IN ('calendar_quality_history_immutable', 'calendar_quality_no_truncate')"
    )
    objects.update(str(row[0]) for row in cursor.fetchall())
    return objects


def _calendar_quality_existing_role_names(
    cursor: Any,
    roles: CalendarQualityRoles,
) -> set[str]:
    roles = _calendar_quality_role_contract(roles)
    cursor.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)",
        (list(roles),),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _calendar_quality_all_owned_object_names(cursor: Any) -> set[str]:
    """Return every V5-prefixed relation/function name, including odd relkinds."""

    cursor.execute(
        "SELECT c.relname FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() "
        "AND c.relname LIKE 'calendar_quality_%%'"
    )
    names = {str(row[0]) for row in cursor.fetchall()}
    cursor.execute(
        "SELECT p.proname FROM pg_catalog.pg_proc AS p "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
        "WHERE n.nspname = current_schema() "
        "AND p.proname LIKE 'calendar_quality_%%'"
    )
    names.update(str(row[0]) for row in cursor.fetchall())
    return names


def _verify_calendar_quality_shared_complement(
    cursor: Any,
    schema: str,
    roles: CalendarQualityRoles,
    *,
    existing_roles: set[str] | None = None,
) -> None:
    """Reject CQ ownership/privileges leaking onto unrelated shared objects.

    V1-V4 are intentionally shared with other workers.  This verifier never
    changes their ACLs; it only proves that the calendar-quality identities do
    not own or receive privileges on the complement of the explicitly allowed
    V4 read surface and sealed ledger.  Other application-role grants remain
    untouched.
    """

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    role_names = set(roles)
    if existing_roles is None:
        existing_roles = _calendar_quality_existing_role_names(cursor, roles)

    cursor.execute(
        "SELECT pg_catalog.pg_get_userbyid(n.nspowner) "
        "FROM pg_catalog.pg_namespace AS n WHERE n.nspname=%s",
        (schema,),
    )
    schema_owner_row = cursor.fetchone()
    if schema_owner_row is None:
        raise ValueError("calendar quality schema complement is unavailable")
    if str(schema_owner_row[0]) in role_names:
        raise ValueError("calendar quality schema complement owner drift")

    cursor.execute(
        "SELECT c.oid, c.relname, c.relkind, "
        "pg_catalog.pg_get_userbyid(c.relowner) "
        "FROM pg_catalog.pg_class AS c "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind IN ('r','p','v','m','f','S')",
        (schema,),
    )
    relation_rows = cursor.fetchall()
    for oid, relname_value, relkind_value, owner_value in relation_rows:
        relname = str(relname_value)
        relkind = str(relkind_value)
        if relname in _CALENDAR_QUALITY_ALLOWED_SHARED_RELATIONS:
            continue
        if relname.startswith("calendar_quality_") or str(owner_value) in role_names:
            raise ValueError("calendar quality schema complement object drift")

        cursor.execute(
            "SELECT x.grantee, pg_catalog.pg_get_userbyid(x.grantor), "
            "x.privilege_type, x.is_grantable "
            "FROM pg_catalog.pg_class AS c "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
            "WHERE c.oid=%s",
            (oid,),
        )
        for grantee_value, _grantor, _privilege, _grantable in cursor.fetchall():
            if int(grantee_value) == 0:
                raise ValueError("calendar quality schema complement PUBLIC ACL drift")
            grantee_row = str(grantee_value)
            cursor.execute(
                "SELECT pg_catalog.pg_get_userbyid(%s)",
                (grantee_value,),
            )
            name_row = cursor.fetchone()
            if name_row is not None:
                grantee_row = str(name_row[0])
            if grantee_row in role_names:
                raise ValueError("calendar quality schema complement role ACL drift")

        if relkind != "S":
            cursor.execute(
                "SELECT x.grantee FROM pg_catalog.pg_attribute AS a "
                "CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) AS x "
                "WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped",
                (oid,),
            )
            for (grantee_value,) in cursor.fetchall():
                if int(grantee_value) == 0:
                    raise ValueError("calendar quality schema complement PUBLIC column ACL drift")
                cursor.execute(
                    "SELECT pg_catalog.pg_get_userbyid(%s)",
                    (grantee_value,),
                )
                name_row = cursor.fetchone()
                if name_row is not None and str(name_row[0]) in role_names:
                    raise ValueError("calendar quality schema complement role column ACL drift")

        privileges = (
            _CALENDAR_QUALITY_SEQUENCE_PRIVILEGES
            if relkind == "S"
            else _CALENDAR_QUALITY_TABLE_PRIVILEGES
        )
        for principal in ("public", *sorted(existing_roles)):
            for privilege in privileges:
                if relkind == "S":
                    cursor.execute(
                        "SELECT pg_catalog.has_sequence_privilege(%s, %s::pg_catalog.oid, %s)",
                        (principal, oid, privilege),
                    )
                else:
                    cursor.execute(
                        "SELECT pg_catalog.has_table_privilege(%s, %s::pg_catalog.oid, %s)",
                        (principal, oid, privilege),
                    )
                privilege_row = cursor.fetchone()
                if privilege_row is None:
                    raise ValueError("calendar quality schema complement privilege unavailable")
                if bool(privilege_row[0]):
                    if principal == "public":
                        raise ValueError("calendar quality schema complement PUBLIC ACL drift")
                    if principal in role_names:
                        raise ValueError("calendar quality schema complement role ACL drift")
            if relkind != "S":
                for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                    cursor.execute(
                        "SELECT pg_catalog.has_any_column_privilege(%s, %s::pg_catalog.oid, %s)",
                        (principal, oid, privilege),
                    )
                    column_privilege_row = cursor.fetchone()
                    if column_privilege_row is None:
                        raise ValueError(
                            "calendar quality schema complement column privilege unavailable"
                        )
                    if bool(column_privilege_row[0]):
                        if principal == "public":
                            raise ValueError(
                                "calendar quality schema complement PUBLIC column ACL drift"
                            )
                        if principal in role_names:
                            raise ValueError(
                                "calendar quality schema complement role column ACL drift"
                            )

    cursor.execute(
        "SELECT p.proname FROM pg_catalog.pg_proc AS p "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid=p.pronamespace "
        "WHERE n.nspname=%s AND p.proname LIKE 'calendar_quality_%%'",
        (schema,),
    )
    function_names = {str(row[0]) for row in cursor.fetchall()}
    if function_names - {
        "calendar_quality_history_immutable",
        "calendar_quality_no_truncate",
    }:
        raise ValueError("calendar quality schema complement function drift")


def _verify_calendar_quality_clean_allowed_public_acl(
    cursor: Any,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    """Refuse to erase pre-existing PUBLIC ACLs during the first seal."""

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    cursor.execute(
        "SELECT x.grantee FROM pg_catalog.pg_namespace AS n "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(n.nspacl) AS x "
        "WHERE n.nspname=%s AND x.grantee=0",
        (schema,),
    )
    if cursor.fetchall():
        raise ValueError("calendar quality clean preflight PUBLIC schema ACL drift")
    for privilege in ("USAGE", "CREATE"):
        cursor.execute(
            "SELECT pg_catalog.has_schema_privilege('public', %s, %s)",
            (schema, privilege),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("calendar quality clean preflight schema privilege unavailable")
        if bool(row[0]):
            raise ValueError("calendar quality clean preflight PUBLIC schema ACL drift")

    for table in (
        "data_worker_schema_migrations",
        *_CALENDAR_QUALITY_V4_READ_TABLES,
    ):
        qualified = f'"{schema}"."{table}"'
        cursor.execute(
            "SELECT x.grantee FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid=c.relnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) AS x "
            "WHERE n.nspname=%s AND c.relname=%s AND x.grantee=0",
            (schema, table),
        )
        if cursor.fetchall():
            raise ValueError(f"calendar quality clean preflight PUBLIC table ACL drift: {table}")
        for privilege in _CALENDAR_QUALITY_TABLE_PRIVILEGES:
            cursor.execute(
                "SELECT pg_catalog.has_table_privilege('public', %s, %s)",
                (qualified, privilege),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("calendar quality clean preflight table privilege unavailable")
            if bool(row[0]):
                raise ValueError(
                    f"calendar quality clean preflight PUBLIC table ACL drift: {table}"
                )
        _verify_calendar_quality_no_column_grants(
            cursor,
            schema=schema,
            table=table,
            roles=roles,
            subject=f"clean preflight {table}",
        )
        for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
            cursor.execute(
                "SELECT pg_catalog.has_any_column_privilege('public', %s, %s)",
                (qualified, privilege),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("calendar quality clean preflight column privilege unavailable")
            if bool(row[0]):
                raise ValueError(
                    f"calendar quality clean preflight PUBLIC column ACL drift: {table}"
                )


def _verify_calendar_quality_columns(cursor: Any) -> None:
    tables = tuple(_CALENDAR_QUALITY_COLUMNS)
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT c.relname, a.attnum, a.attname, format_type(a.atttypid, -1), "
        "NOT a.attnotnull, pg_get_expr(d.adbin, d.adrelid), a.attidentity, "
        "a.attgenerated, a.attcollation, t.typcollation "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "JOIN pg_attribute AS a ON a.attrelid = c.oid "
        "JOIN pg_type AS t ON t.oid = a.atttypid "
        "LEFT JOIN pg_attrdef AS d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        f"AND c.relname IN ({placeholders}) "
        "AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY c.relname, a.attnum",
        tables,
    )
    actual: dict[str, list[tuple[str, str, bool, object, str, str, int, int]]] = {}
    for row in cursor.fetchall():
        (
            table,
            _attnum,
            column,
            data_type,
            nullable,
            default,
            identity,
            generated,
            collation,
            type_collation,
        ) = row
        actual.setdefault(str(table), []).append(
            (
                str(column),
                str(data_type),
                bool(nullable),
                default,
                str(identity),
                str(generated),
                int(str(collation)),
                int(str(type_collation)),
            )
        )
    for table, expected_columns in _CALENDAR_QUALITY_COLUMNS.items():
        observed = actual.get(table)
        if observed is None:
            raise ValueError(f"calendar quality schema drift: missing table {table}")
        if len(observed) != len(expected_columns):
            raise ValueError(f"calendar quality schema drift: columns in {table}")
        for observed_item, expected_item in zip(observed, expected_columns, strict=True):
            (
                column,
                data_type,
                nullable,
                default,
                identity,
                generated,
                collation,
                type_collation,
            ) = observed_item
            expected_column, expected_type, expected_nullable, expected_default = expected_item
            if (
                column != expected_column
                or data_type != expected_type
                or nullable != expected_nullable
                or bool(default is not None) != expected_default
                or identity
                or generated
                or collation != type_collation
            ):
                raise ValueError(f"calendar quality schema drift: column {table}.{column}")
            if expected_default and _canonical_catalog_expression(default) != "current_timestamp":
                raise ValueError(f"calendar quality schema drift: default {table}.{column}")


def _verify_calendar_quality_triggers(cursor: Any) -> None:
    cursor.execute("SELECT current_schema()")
    row = cursor.fetchone()
    if row is None:
        raise ValueError("calendar quality schema drift: current schema unavailable")
    current_schema = str(row[0])
    cursor.execute(
        "SELECT table_catalog.relname, trigger_catalog.tgname, trigger_catalog.tgtype, "
        "trigger_catalog.tgenabled, trigger_catalog.tgnargs, trigger_catalog.tgargs, "
        "pg_get_expr(trigger_catalog.tgqual, trigger_catalog.tgrelid, TRUE), "
        "function_namespace.nspname, function_catalog.proname, function_catalog.pronargs, "
        "function_catalog.prokind, return_type.typname, language_catalog.lanname, "
        "function_catalog.prosrc "
        "FROM pg_trigger AS trigger_catalog "
        "JOIN pg_class AS table_catalog ON table_catalog.oid = trigger_catalog.tgrelid "
        "JOIN pg_namespace AS table_namespace ON table_namespace.oid = table_catalog.relnamespace "
        "JOIN pg_proc AS function_catalog ON function_catalog.oid = trigger_catalog.tgfoid "
        "JOIN pg_namespace AS function_namespace "
        "ON function_namespace.oid = function_catalog.pronamespace "
        "JOIN pg_type AS return_type ON return_type.oid = function_catalog.prorettype "
        "JOIN pg_language AS language_catalog ON language_catalog.oid = function_catalog.prolang "
        "WHERE table_namespace.nspname = current_schema() "
        "AND position('calendar_quality_' IN table_catalog.relname) = 1 "
        "AND NOT trigger_catalog.tgisinternal"
    )
    actual: set[tuple[str, str]] = set()
    for trigger_row in cursor.fetchall():
        (
            table,
            name,
            trigger_type,
            enabled,
            argument_count,
            arguments,
            condition,
            function_schema,
            function_name,
            function_argument_count,
            function_kind,
            return_type,
            language,
            function_body,
        ) = trigger_row
        identity = (str(table), str(name))
        actual.add(identity)
        try:
            empty_arguments = bytes(arguments) == b""
        except (TypeError, ValueError):
            empty_arguments = False
        expected_trigger_type = 34 if str(name).endswith("_no_truncate") else 27
        expected_function_name = (
            "calendar_quality_no_truncate"
            if expected_trigger_type == 34
            else "calendar_quality_history_immutable"
        )
        expected_function_body = (
            _CALENDAR_QUALITY_NO_TRUNCATE_FUNCTION_BODY
            if expected_trigger_type == 34
            else _CALENDAR_QUALITY_IMMUTABLE_FUNCTION_BODY
        )
        if (
            int(trigger_type) != expected_trigger_type
            or str(enabled) != "O"
            or int(argument_count) != 0
            or not empty_arguments
            or condition is not None
            or str(function_schema) != current_schema
            or str(function_name) != expected_function_name
            or int(function_argument_count) != 0
            or str(function_kind) != "f"
            or str(return_type) != "trigger"
            or str(language) != "plpgsql"
            or _canonical_function_body(function_body) != expected_function_body
        ):
            raise ValueError(f"calendar quality schema drift: trigger {identity[1]}")
    if actual != set(_CALENDAR_QUALITY_TRIGGERS | _CALENDAR_QUALITY_TRUNCATE_TRIGGERS):
        raise ValueError("calendar quality schema drift: immutable trigger set mismatch")

    cursor.execute(
        "SELECT function_namespace.nspname, function_catalog.proname, "
        "function_catalog.pronargs, function_catalog.prokind, return_type.typname, "
        "language_catalog.lanname, function_catalog.prosrc, "
        "function_catalog.prosecdef, function_catalog.proconfig "
        "FROM pg_proc AS function_catalog "
        "JOIN pg_namespace AS function_namespace "
        "ON function_namespace.oid = function_catalog.pronamespace "
        "JOIN pg_type AS return_type ON return_type.oid = function_catalog.prorettype "
        "JOIN pg_language AS language_catalog ON language_catalog.oid = function_catalog.prolang "
        "WHERE function_namespace.nspname = current_schema() "
        "AND function_catalog.proname IN ('calendar_quality_history_immutable', "
        "'calendar_quality_no_truncate')"
    )
    functions = cursor.fetchall()
    if len(functions) != 2 or {str(function[1]) for function in functions} != {
        "calendar_quality_history_immutable",
        "calendar_quality_no_truncate",
    }:
        raise ValueError("calendar quality schema drift: immutable function mismatch")
    for function in functions:
        expected_body = (
            _CALENDAR_QUALITY_NO_TRUNCATE_FUNCTION_BODY
            if str(function[1]) == "calendar_quality_no_truncate"
            else _CALENDAR_QUALITY_IMMUTABLE_FUNCTION_BODY
        )
        if (
            str(function[0]) != current_schema
            or int(function[2]) != 0
            or str(function[3]) != "f"
            or str(function[4]) != "trigger"
            or str(function[5]) != "plpgsql"
            or _canonical_function_body(function[6]) != expected_body
            or bool(function[7])
            or function[8] is not None
        ):
            raise ValueError("calendar quality schema drift: immutable function mismatch")


def _verify_calendar_quality_schema(cursor: Any) -> None:
    if _calendar_quality_tables(cursor) != set(_CALENDAR_QUALITY_TABLES):
        raise ValueError("calendar quality schema drift: table set mismatch")
    _verify_calendar_quality_columns(cursor)
    _verify_constraint_specs(
        cursor,
        _CALENDAR_QUALITY_TABLES,
        _CALENDAR_QUALITY_EXPECTED_CONSTRAINTS,
        normalize_expressions=True,
        drift_prefix="calendar quality schema drift",
    )
    _verify_index_specs(
        cursor,
        _CALENDAR_QUALITY_TABLES,
        _CALENDAR_QUALITY_EXPECTED_INDEXES,
        drift_prefix="calendar quality schema drift",
    )
    _verify_calendar_quality_triggers(cursor)


def verify_calendar_quality_schema(
    connection: Connection[Any],
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
) -> None:
    """Verify the additive V5 quality schema without changing it."""

    schema = _calendar_quality_schema_name(schema)
    if connection.info.transaction_status == TransactionStatus.INERROR:
        raise ValueError("calendar quality schema verification requires a usable transaction")
    with connection.transaction(), connection.cursor() as cursor:
        _set_calendar_quality_search_path(cursor, schema)
        _calendar_quality_context(cursor, schema)
        _verify_calendar_quality_schema(cursor)


def _verify_calendar_quality_identity(
    cursor: Any,
    schema: str,
    expected_role: str,
) -> None:
    cursor.execute("SELECT SESSION_USER, CURRENT_USER")
    row = cursor.fetchone()
    if row is None or len(row) != 2 or any(str(value) != expected_role for value in row):
        raise ValueError("calendar quality database role is invalid")
    _calendar_quality_context(cursor, schema)


def prepare_calendar_quality_runtime_context(
    cursor: Any,
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
    expected_role: str = CALENDAR_QUALITY_RUNTIME_ROLE,
) -> None:
    """Pin a runtime transaction to the approved schema and database role.

    The setting is local to the caller's transaction.  Checking both session
    and current identities prevents an administrator connection using
    ``SET ROLE`` from masquerading as the dedicated runtime login.
    """

    schema = _calendar_quality_schema_name(schema)
    expected_role = _calendar_quality_identifier(expected_role, "calendar quality role")
    _set_calendar_quality_search_path(cursor, schema)
    _verify_calendar_quality_identity(cursor, schema, expected_role)


def verify_calendar_quality_runtime(
    connection: Connection[Any],
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
    roles: CalendarQualityRoles = _CALENDAR_QUALITY_DEFAULT_ROLES,
) -> None:
    """Verify the sealed V5 schema for the dedicated runtime role only."""

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    if connection.info.transaction_status == TransactionStatus.INERROR:
        raise ValueError("calendar quality runtime verification requires a usable transaction")
    with connection.transaction(), connection.cursor() as cursor:
        prepare_calendar_quality_runtime_context(
            cursor,
            schema=schema,
            expected_role=roles.runtime,
        )
        _verify_calendar_quality_roles(cursor, roles, migration_window=False)
        _verify_calendar_quality_schema(cursor)
        _verify_calendar_quality_runtime_acl(cursor, schema, roles)
        _verify_calendar_quality_shared_complement(cursor, schema, roles)


def verify_calendar_quality_reader(
    connection: Connection[Any],
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
    roles: CalendarQualityRoles = _CALENDAR_QUALITY_DEFAULT_ROLES,
) -> None:
    """Verify the sealed V5 schema for the dedicated reader role only."""

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    if connection.info.transaction_status == TransactionStatus.INERROR:
        raise ValueError("calendar quality reader verification requires a usable transaction")
    with connection.transaction(), connection.cursor() as cursor:
        _set_calendar_quality_search_path(cursor, schema)
        _verify_calendar_quality_identity(cursor, schema, roles.reader)
        _verify_calendar_quality_roles(cursor, roles, migration_window=False)
        _verify_calendar_quality_schema(cursor)
        _verify_calendar_quality_runtime_acl(cursor, schema, roles)
        _verify_calendar_quality_shared_complement(cursor, schema, roles)


def _calendar_snapshot_tables(cursor: Any) -> set[str]:
    cursor.execute(
        "SELECT c.relname "
        "FROM pg_class AS c "
        "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = current_schema() "
        "AND c.relkind IN ('r', 'p') "
        "AND c.relname LIKE 'calendar_snapshot_%'"
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _verify_calendar_snapshot_schema(cursor: Any) -> None:
    tables = tuple(_CALENDAR_SNAPSHOT_COLUMNS)
    placeholders = ", ".join("%s" for _ in tables)
    cursor.execute(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        f"AND table_name IN ({placeholders}) "
        "ORDER BY table_name, ordinal_position",
        tables,
    )
    actual: dict[str, list[tuple[str, str, bool, bool, object]]] = {}
    for table, column, data_type, nullable, default in cursor.fetchall():
        actual.setdefault(str(table), []).append(
            (
                str(column),
                str(data_type),
                str(nullable).upper() == "YES",
                default is not None,
                default,
            )
        )
    if _calendar_snapshot_tables(cursor) != set(_CALENDAR_SNAPSHOT_TABLES):
        raise ValueError("calendar snapshot schema drift: table set mismatch")
    for table, expected_columns in _CALENDAR_SNAPSHOT_COLUMNS.items():
        observed = actual.get(table)
        if observed is None:
            raise ValueError(f"calendar snapshot schema drift: missing table {table}")
        expected_names = tuple(item[0] for item in expected_columns)
        if tuple(item[0] for item in observed) != expected_names:
            raise ValueError(f"calendar snapshot schema drift: columns in {table}")
        for observed_item, expected_item in zip(observed, expected_columns, strict=True):
            column, data_type, nullable, has_default, default = observed_item
            expected_column, expected_type, expected_nullable, expected_default = expected_item
            if (
                column != expected_column
                or data_type != expected_type
                or nullable != expected_nullable
                or has_default != expected_default
            ):
                raise ValueError(f"calendar snapshot schema drift: column {table}.{column}")
            if expected_default and _canonical_catalog_expression(default) != "current_timestamp":
                raise ValueError(f"calendar snapshot schema drift: default {table}.{column}")

    cursor.execute(
        "SELECT relation.relname, attribute.attname, attribute.attcollation, "
        "type_catalog.typcollation "
        "FROM pg_class AS relation "
        "JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace "
        "JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid "
        "JOIN pg_type AS type_catalog ON type_catalog.oid = attribute.atttypid "
        "WHERE namespace.nspname = current_schema() "
        f"AND relation.relname IN ({placeholders}) "
        "AND attribute.attnum > 0 AND NOT attribute.attisdropped"
        " AND type_catalog.typname = 'text'",
        tables,
    )
    for table, column, column_collation, type_collation in cursor.fetchall():
        if int(column_collation) != int(type_collation):
            raise ValueError(f"calendar snapshot schema drift: collation {table}.{column}")

    _verify_constraint_specs(
        cursor,
        _CALENDAR_SNAPSHOT_TABLES,
        _CALENDAR_EXPECTED_CONSTRAINTS,
        normalize_expressions=True,
        drift_prefix="calendar snapshot schema drift",
    )
    _verify_index_specs(
        cursor,
        _CALENDAR_SNAPSHOT_TABLES,
        _CALENDAR_EXPECTED_INDEXES,
        drift_prefix="calendar snapshot schema drift",
    )
    cursor.execute("SELECT current_schema()")
    current_schema_row = cursor.fetchone()
    if current_schema_row is None:
        raise ValueError("calendar snapshot schema drift: current schema unavailable")
    current_schema = str(current_schema_row[0])

    cursor.execute(
        "SELECT table_catalog.relname, trigger_catalog.tgname, trigger_catalog.tgtype, "
        "trigger_catalog.tgenabled, trigger_catalog.tgfoid, trigger_catalog.tgnargs, "
        "trigger_catalog.tgargs, "
        "pg_get_expr(trigger_catalog.tgqual, trigger_catalog.tgrelid, TRUE), "
        "function_namespace.nspname, function_catalog.proname, function_catalog.pronargs, "
        "function_catalog.prokind, return_type.typname, language_catalog.lanname, "
        "function_catalog.prosrc "
        "FROM pg_trigger AS trigger_catalog "
        "JOIN pg_class AS table_catalog ON table_catalog.oid = trigger_catalog.tgrelid "
        "JOIN pg_namespace AS table_namespace ON table_namespace.oid = table_catalog.relnamespace "
        "JOIN pg_proc AS function_catalog ON function_catalog.oid = trigger_catalog.tgfoid "
        "JOIN pg_namespace AS function_namespace "
        "ON function_namespace.oid = function_catalog.pronamespace "
        "JOIN pg_type AS return_type ON return_type.oid = function_catalog.prorettype "
        "JOIN pg_language AS language_catalog ON language_catalog.oid = function_catalog.prolang "
        "WHERE table_namespace.nspname = current_schema() "
        "AND table_catalog.relname LIKE 'calendar_snapshot_%' "
        "AND NOT trigger_catalog.tgisinternal"
    )
    trigger_rows = cursor.fetchall()
    actual_triggers: set[tuple[str, str]] = set()
    for row in trigger_rows:
        (
            table,
            name,
            trigger_type,
            enabled,
            _function_oid,
            argument_count,
            arguments,
            condition,
            function_schema,
            function_name,
            function_argument_count,
            function_kind,
            return_type,
            language,
            function_body,
        ) = row
        identity = (str(table), str(name))
        actual_triggers.add(identity)
        try:
            empty_arguments = bytes(arguments) == b""
        except (TypeError, ValueError):
            empty_arguments = False
        if (
            int(trigger_type) != 27
            or str(enabled) != "O"
            or int(argument_count) != 0
            or not empty_arguments
            or condition is not None
            or str(function_schema) != current_schema
            or str(function_name) != "calendar_snapshot_history_immutable"
            or int(function_argument_count) != 0
            or str(function_kind) != "f"
            or str(return_type) != "trigger"
            or str(language) != "plpgsql"
            or _canonical_function_body(function_body) != _CALENDAR_IMMUTABLE_FUNCTION_BODY
        ):
            raise ValueError(f"calendar snapshot schema drift: trigger {identity[1]}")
    if actual_triggers != set(_CALENDAR_SNAPSHOT_TRIGGERS):
        raise ValueError("calendar snapshot schema drift: immutable trigger set mismatch")

    cursor.execute(
        "SELECT function_namespace.nspname, function_catalog.proname, "
        "function_catalog.pronargs, function_catalog.prokind, return_type.typname, "
        "language_catalog.lanname, function_catalog.prosrc "
        "FROM pg_proc AS function_catalog "
        "JOIN pg_namespace AS function_namespace "
        "ON function_namespace.oid = function_catalog.pronamespace "
        "JOIN pg_type AS return_type ON return_type.oid = function_catalog.prorettype "
        "JOIN pg_language AS language_catalog ON language_catalog.oid = function_catalog.prolang "
        "WHERE function_namespace.nspname = current_schema() "
        "AND function_catalog.proname = 'calendar_snapshot_history_immutable'"
    )
    function_rows = cursor.fetchall()
    if (
        len(function_rows) != 1
        or str(function_rows[0][0]) != current_schema
        or int(function_rows[0][2]) != 0
        or str(function_rows[0][3]) != "f"
        or str(function_rows[0][4]) != "trigger"
        or str(function_rows[0][5]) != "plpgsql"
        or _canonical_function_body(function_rows[0][6]) != _CALENDAR_IMMUTABLE_FUNCTION_BODY
    ):
        raise ValueError("calendar snapshot schema drift: immutable function mismatch")


def apply_calendar_snapshot_migration(connection: Connection[Any]) -> None:
    """Apply the calendar snapshot schema as version 3 of the worker ledger."""

    checksum = _calendar_snapshot_migration_checksum()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        if "data_worker_schema_migrations" not in _task_owned_tables(cursor):
            if _calendar_snapshot_tables(cursor):
                raise ValueError("untracked calendar snapshot schema exists without ledger")
            raise ValueError("calendar snapshot migration requires worker migration ledger")
        _verify_ledger(cursor, _migration_checksum())

        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version = %s",
            (CALENDAR_SNAPSHOT_MIGRATION_VERSION,),
        )
        rows = cursor.fetchall()
        if rows:
            if len(rows) != 1 or tuple(rows[0]) != (
                CALENDAR_SNAPSHOT_MIGRATION_VERSION,
                CALENDAR_SNAPSHOT_MIGRATION_NAME,
                checksum,
            ):
                raise ValueError("calendar snapshot migration ledger checksum or name drift")
            _verify_calendar_snapshot_schema(cursor)
            return

        cursor.execute("SELECT version FROM data_worker_schema_migrations")
        prior_versions = {int(row[0]) for row in cursor.fetchall()}
        if not {MIGRATION_VERSION, SEAT_MIGRATION_VERSION}.issubset(prior_versions):
            raise ValueError("calendar snapshot migration requires V1 and V2")
        if _calendar_snapshot_tables(cursor):
            raise ValueError("untracked calendar snapshot schema exists without ledger")

        cursor.execute(cast(Any, load_calendar_snapshot_migration().decode("utf-8")))
        _verify_calendar_snapshot_schema(cursor)
        cursor.execute(
            "INSERT INTO data_worker_schema_migrations "
            "(version, name, checksum, applied_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            (CALENDAR_SNAPSHOT_MIGRATION_VERSION, CALENDAR_SNAPSHOT_MIGRATION_NAME, checksum),
        )
        _verify_ledger(cursor, _migration_checksum())


def apply_official_calendar_migration(connection: Connection[Any]) -> None:
    """Apply the immutable official-calendar schema as ledger version 4."""

    checksum = _official_calendar_migration_checksum()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        if "data_worker_schema_migrations" not in _task_owned_tables(cursor):
            if _official_calendar_tables(cursor):
                raise ValueError("untracked official calendar schema exists without ledger")
            raise ValueError("official calendar migration requires worker migration ledger")
        _verify_ledger(cursor, _migration_checksum())

        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version = %s",
            (OFFICIAL_CALENDAR_MIGRATION_VERSION,),
        )
        rows = cursor.fetchall()
        if rows:
            if len(rows) != 1 or tuple(rows[0]) != (
                OFFICIAL_CALENDAR_MIGRATION_VERSION,
                OFFICIAL_CALENDAR_MIGRATION_NAME,
                checksum,
            ):
                raise ValueError("official calendar migration ledger checksum or name drift")
            _verify_official_calendar_schema(cursor)
            return

        cursor.execute("SELECT version FROM data_worker_schema_migrations")
        prior_versions = {int(row[0]) for row in cursor.fetchall()}
        required = {MIGRATION_VERSION, SEAT_MIGRATION_VERSION, CALENDAR_SNAPSHOT_MIGRATION_VERSION}
        if not required.issubset(prior_versions):
            raise ValueError("official calendar migration requires V1, V2 and V3")
        if _official_calendar_tables(cursor):
            raise ValueError("untracked official calendar schema exists without V4 ledger")

        cursor.execute(cast(Any, load_official_calendar_migration().decode("utf-8")))
        _verify_official_calendar_schema(cursor)
        cursor.execute(
            "INSERT INTO data_worker_schema_migrations "
            "(version, name, checksum, applied_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            (OFFICIAL_CALENDAR_MIGRATION_VERSION, OFFICIAL_CALENDAR_MIGRATION_NAME, checksum),
        )
        _verify_ledger(cursor, _migration_checksum())


def _apply_calendar_quality_migration_in_transaction(
    cursor: Any,
    *,
    schema: str,
    roles: CalendarQualityRoles,
) -> None:
    """Apply V5 using the caller's already-open transaction and cursor."""

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    checksum = _calendar_quality_migration_checksum()
    cursor.execute("SELECT SESSION_USER, CURRENT_USER")
    identity = cursor.fetchone()
    if identity is None or any(str(value) != roles.migrator for value in identity):
        raise ValueError("calendar quality database role is invalid")
    _set_calendar_quality_search_path(cursor, schema)
    _verify_calendar_quality_roles(cursor, roles, migration_window=True)
    cursor.execute(
        "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(%s))",
        (f"{CALENDAR_QUALITY_LOCK_KEY}:{schema}",),
    )
    cursor.execute(f'SET LOCAL ROLE "{roles.owner}"')
    _calendar_quality_context(cursor, schema, current_user=roles.owner)
    if "data_worker_schema_migrations" not in _task_owned_tables(cursor):
        if _calendar_quality_orphaned_objects(cursor):
            raise ValueError("untracked calendar quality schema exists without ledger")
        raise ValueError("calendar quality migration requires worker migration ledger")
    _verify_ledger(cursor, _migration_checksum())
    cursor.execute(
        "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version = %s",
        (CALENDAR_QUALITY_MIGRATION_VERSION,),
    )
    rows = cursor.fetchall()
    if rows:
        if len(rows) != 1 or tuple(rows[0]) != (
            CALENDAR_QUALITY_MIGRATION_VERSION,
            CALENDAR_QUALITY_MIGRATION_NAME,
            checksum,
        ):
            raise ValueError("calendar quality migration ledger checksum or name drift")
        _verify_calendar_quality_schema(cursor)
        return

    cursor.execute("SELECT version FROM data_worker_schema_migrations")
    prior_versions = {int(row[0]) for row in cursor.fetchall()}
    if not {
        MIGRATION_VERSION,
        SEAT_MIGRATION_VERSION,
        CALENDAR_SNAPSHOT_MIGRATION_VERSION,
        OFFICIAL_CALENDAR_MIGRATION_VERSION,
    }.issubset(prior_versions):
        raise ValueError("calendar quality migration requires worker migrations V1-V4")
    if _calendar_quality_orphaned_objects(cursor):
        raise ValueError("untracked calendar quality schema exists without ledger")

    cursor.execute(cast(Any, load_calendar_quality_migration().decode("utf-8")))
    _verify_calendar_quality_schema(cursor)
    cursor.execute(
        "INSERT INTO data_worker_schema_migrations "
        "(version, name, checksum, applied_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
        (CALENDAR_QUALITY_MIGRATION_VERSION, CALENDAR_QUALITY_MIGRATION_NAME, checksum),
    )
    _verify_ledger(cursor, _migration_checksum())


def _seal_calendar_quality_in_transaction(
    cursor: Any,
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
    roles: CalendarQualityRoles = _CALENDAR_QUALITY_DEFAULT_ROLES,
) -> None:
    """Seal V5 using the caller's already-open administrator transaction.

    This operation is intentionally administrator-owned and transactional.  A
    failed verification rolls back every grant/revoke, leaving the runtime
    role disabled until a later successful seal.
    """

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    qualified_schema = f'"{schema}"'
    role_list = ", ".join(f'"{role}"' for role in roles)
    non_owner_roles = ", ".join(
        f'"{role}"' for role in (roles.migrator, roles.runtime, roles.reader)
    )
    all_principals = f"PUBLIC, {role_list}"
    if cursor is None:
        raise ValueError("calendar quality seal cursor is unavailable")
    if cursor is not None:
        _set_calendar_quality_search_path(cursor, schema)
        _calendar_quality_context(cursor, schema)
        cursor.execute("SELECT SESSION_USER, CURRENT_USER")
        identity = cursor.fetchone()
        if identity is None or any(str(value) in set(roles) for value in identity):
            raise ValueError("calendar quality seal requires administrator role")
        try:
            _verify_calendar_quality_roles(cursor, roles, migration_window=True)
        except ValueError:
            _verify_calendar_quality_roles(cursor, roles, migration_window=False)
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(%s))",
            (f"{CALENDAR_QUALITY_LOCK_KEY}:{schema}",),
        )
        if "data_worker_schema_migrations" not in _task_owned_tables(cursor):
            raise ValueError("calendar quality seal requires worker migration ledger")
        _verify_ledger(cursor, _migration_checksum())
        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version=%s",
            (CALENDAR_QUALITY_MIGRATION_VERSION,),
        )
        ledger_row = cursor.fetchone()
        if ledger_row is None or tuple(ledger_row) != (
            CALENDAR_QUALITY_MIGRATION_VERSION,
            CALENDAR_QUALITY_MIGRATION_NAME,
            _calendar_quality_migration_checksum(),
        ):
            raise ValueError("calendar quality seal requires V5 migration")
        _verify_calendar_quality_schema(cursor)
        _verify_calendar_quality_object_owners(cursor, schema, roles)

        cursor.execute(f"REVOKE ALL ON SCHEMA {qualified_schema} FROM {all_principals}")
        cursor.execute(
            f"GRANT USAGE ON SCHEMA {qualified_schema} TO "
            f'"{roles.owner}", "{roles.runtime}", "{roles.reader}"'
        )
        cursor.execute(
            f'REVOKE CREATE ON SCHEMA {qualified_schema} FROM {non_owner_roles}, "{roles.owner}"'
        )
        cursor.execute(
            f"REVOKE ALL ON TABLE {qualified_schema}.data_worker_schema_migrations "
            f"FROM {all_principals}"
        )

        for table in _CALENDAR_QUALITY_V4_READ_TABLES:
            qualified_table = f'{qualified_schema}."{table}"'
            cursor.execute(f"REVOKE ALL ON TABLE {qualified_table} FROM {all_principals}")
            cursor.execute(f'GRANT SELECT ON TABLE {qualified_table} TO "{roles.runtime}"')
        for table in _CALENDAR_QUALITY_TABLES:
            qualified_table = f'{qualified_schema}."{table}"'
            cursor.execute(f"REVOKE ALL ON TABLE {qualified_table} FROM PUBLIC, {non_owner_roles}")
            cursor.execute(f'GRANT ALL PRIVILEGES ON TABLE {qualified_table} TO "{roles.owner}"')
            if table == "calendar_quality_audit":
                cursor.execute(f'GRANT INSERT ON TABLE {qualified_table} TO "{roles.runtime}"')
            else:
                cursor.execute(
                    f'GRANT SELECT, INSERT ON TABLE {qualified_table} TO "{roles.runtime}"'
                )
                cursor.execute(f'GRANT SELECT ON TABLE {qualified_table} TO "{roles.reader}"')

        for function_name in ("calendar_quality_history_immutable", "calendar_quality_no_truncate"):
            cursor.execute(
                f"REVOKE ALL ON FUNCTION {qualified_schema}.{function_name}() "
                f"FROM PUBLIC, {non_owner_roles}"
            )
            cursor.execute(
                f'GRANT EXECUTE ON FUNCTION {qualified_schema}.{function_name}() TO "{roles.owner}"'
            )
        cursor.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{roles.owner}" '
            f"IN SCHEMA {qualified_schema} REVOKE ALL ON TABLES "
            f"FROM PUBLIC, {non_owner_roles}"
        )
        cursor.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{roles.owner}" '
            f'IN SCHEMA {qualified_schema} GRANT ALL ON TABLES TO "{roles.owner}"'
        )
        cursor.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{roles.owner}" '
            f"IN SCHEMA {qualified_schema} REVOKE ALL ON FUNCTIONS "
            f"FROM PUBLIC, {non_owner_roles}"
        )
        cursor.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{roles.owner}" '
            f'IN SCHEMA {qualified_schema} GRANT ALL ON FUNCTIONS TO "{roles.owner}"'
        )
        cursor.execute(f'REVOKE "{roles.owner}" FROM "{roles.migrator}"')
        cursor.execute(f'REVOKE "{roles.owner}" FROM "{roles.runtime}", "{roles.reader}"')
        _verify_calendar_quality_roles(cursor, roles, migration_window=False)
        _verify_calendar_quality_schema(cursor)
        _verify_calendar_quality_runtime_acl(cursor, schema, roles)
        _verify_calendar_quality_shared_complement(cursor, schema, roles)


def _calendar_quality_assert_identity(
    cursor: Any,
    *,
    session_user: str,
    current_user: str,
) -> None:
    cursor.execute("SELECT SESSION_USER, CURRENT_USER")
    row = cursor.fetchone()
    if row is None or len(row) != 2 or str(row[0]) != session_user or str(row[1]) != current_user:
        raise ValueError("calendar quality database role is invalid")


def _calendar_quality_assert_admin(cursor: Any, roles: CalendarQualityRoles) -> None:
    roles = _calendar_quality_role_contract(roles)
    cursor.execute("SELECT SESSION_USER, CURRENT_USER")
    identity = cursor.fetchone()
    if identity is None or len(identity) != 2 or str(identity[0]) != str(identity[1]):
        raise ValueError("calendar quality publish requires administrator role")
    if str(identity[0]) in set(roles):
        raise ValueError("calendar quality publish requires administrator role")
    cursor.execute(
        "SELECT r.rolsuper FROM pg_catalog.pg_roles AS r WHERE r.rolname=%s",
        (str(identity[0]),),
    )
    role_row = cursor.fetchone()
    if role_row is None or not bool(role_row[0]):
        raise ValueError("calendar quality publish requires administrator role")


def _calendar_quality_set_bounded_timeouts(cursor: Any) -> None:
    cursor.execute("SET LOCAL lock_timeout = '5s'")
    cursor.execute("SET LOCAL statement_timeout = '30s'")
    cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '60s'")


def _calendar_quality_require_shared_ledger(cursor: Any, *, include_v5: bool) -> None:
    if "data_worker_schema_migrations" not in _task_owned_tables(cursor):
        raise ValueError("calendar quality publish requires worker migration ledger")
    _verify_ledger(cursor, _migration_checksum())
    cursor.execute("SELECT version FROM data_worker_schema_migrations ORDER BY version")
    versions = [int(row[0]) for row in cursor.fetchall()]
    expected = {
        MIGRATION_VERSION,
        SEAT_MIGRATION_VERSION,
        CALENDAR_SNAPSHOT_MIGRATION_VERSION,
        OFFICIAL_CALENDAR_MIGRATION_VERSION,
    }
    if include_v5:
        expected.add(CALENDAR_QUALITY_MIGRATION_VERSION)
    if len(versions) != len(expected) or set(versions) != expected:
        raise ValueError("calendar quality shared migration ledger is incomplete")


def _calendar_quality_preflight_state(
    cursor: Any,
    *,
    schema: str,
    roles: CalendarQualityRoles,
) -> CalendarQualityPublishDisposition | None:
    """Return ALREADY_SEALED or None for a clean first-install state."""

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    existing_roles = _calendar_quality_existing_role_names(cursor, roles)
    expected_roles = set(roles)
    if existing_roles:
        if existing_roles != expected_roles:
            raise ValueError("calendar quality publish role set is partial")
        _verify_calendar_quality_roles(cursor, roles, migration_window=False)
        _calendar_quality_require_shared_ledger(cursor, include_v5=True)
        _verify_calendar_quality_schema(cursor)
        _verify_calendar_quality_runtime_acl(cursor, schema, roles)
        _verify_calendar_quality_shared_complement(
            cursor, schema, roles, existing_roles=existing_roles
        )
        return CalendarQualityPublishDisposition.ALREADY_SEALED

    if _calendar_quality_all_owned_object_names(cursor):
        raise ValueError("calendar quality publish found untracked V5 objects")
    _calendar_quality_require_shared_ledger(cursor, include_v5=False)
    _verify_calendar_quality_clean_allowed_public_acl(cursor, schema, roles)
    _verify_calendar_quality_shared_complement(cursor, schema, roles, existing_roles=existing_roles)
    return None


def _calendar_quality_validate_password(value: str, field_name: str) -> str:
    if type(value) is not str or not value or len(value) > 4096 or "\x00" in value:
        raise ValueError(f"{field_name} is invalid")
    return value


def _calendar_quality_create_roles(
    cursor: Any,
    *,
    schema: str,
    roles: CalendarQualityRoles,
    migrator_password: str,
    runtime_password: str,
) -> None:
    """Create the four roles and migration-window grants in the outer tx."""

    from psycopg import sql

    schema = _calendar_quality_schema_name(schema)
    migrator_password = _calendar_quality_validate_password(
        migrator_password, "calendar quality migrator password"
    )
    runtime_password = _calendar_quality_validate_password(
        runtime_password, "calendar quality runtime password"
    )
    common = sql.SQL("NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    role_specs = (
        (roles.owner, sql.SQL("NOLOGIN"), sql.SQL("PASSWORD NULL")),
        (
            roles.migrator,
            sql.SQL("LOGIN"),
            sql.SQL("PASSWORD {}").format(sql.Literal(migrator_password)),
        ),
        (
            roles.runtime,
            sql.SQL("LOGIN"),
            sql.SQL("PASSWORD {}").format(sql.Literal(runtime_password)),
        ),
        (roles.reader, sql.SQL("NOLOGIN"), sql.SQL("PASSWORD NULL")),
    )
    for role, login_clause, password_clause in role_specs:
        cursor.execute(
            sql.SQL("CREATE ROLE {} {} {}").format(
                sql.Identifier(role), login_clause, common + sql.SQL(" ") + password_clause
            )
        )

    cursor.execute(
        sql.SQL("GRANT {} TO {} WITH INHERIT FALSE, SET TRUE, ADMIN FALSE").format(
            sql.Identifier(roles.owner), sql.Identifier(roles.migrator)
        )
    )
    cursor.execute(
        sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(
            sql.Identifier(schema), sql.Identifier(roles.owner)
        )
    )
    cursor.execute(
        sql.SQL("GRANT SELECT, INSERT ON TABLE {}.{} TO {}").format(
            sql.Identifier(schema),
            sql.Identifier("data_worker_schema_migrations"),
            sql.Identifier(roles.owner),
        )
    )


def publish_calendar_quality(
    connection: Connection[Any],
    *,
    schema: str = CALENDAR_QUALITY_SCHEMA,
    roles: CalendarQualityRoles = _CALENDAR_QUALITY_DEFAULT_ROLES,
    migrator_password: str,
    runtime_password: str,
) -> CalendarQualityPublishResult:
    """Atomically install and seal V5, or verify an existing sealed install.

    The administrator connection owns the only outer transaction.  Role
    creation, temporary migration privileges, V5 DDL, sealing, and final
    verification therefore either commit together or roll back together.
    """

    schema = _calendar_quality_schema_name(schema)
    roles = _calendar_quality_role_contract(roles)
    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise ValueError("calendar quality publish requires an idle connection")
    _calendar_quality_validate_password(migrator_password, "calendar quality migrator password")
    _calendar_quality_validate_password(runtime_password, "calendar quality runtime password")
    with connection.transaction(), connection.cursor() as raw_cursor:
        cursor = cast(Any, raw_cursor)
        _calendar_quality_assert_admin(cursor, roles)
        _set_calendar_quality_search_path(cursor, schema)
        _calendar_quality_context(cursor, schema)
        _calendar_quality_set_bounded_timeouts(cursor)
        cursor.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext(%s))",
            (f"{CALENDAR_QUALITY_LOCK_KEY}:{schema}",),
        )
        disposition = _calendar_quality_preflight_state(cursor, schema=schema, roles=roles)
        if disposition is not None:
            return CalendarQualityPublishResult(disposition)

        _calendar_quality_create_roles(
            cursor,
            schema=schema,
            roles=roles,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        )
        _verify_calendar_quality_roles(cursor, roles, migration_window=True)

        cursor.execute(f'SET LOCAL SESSION AUTHORIZATION "{roles.migrator}"')
        _calendar_quality_assert_identity(
            cursor, session_user=roles.migrator, current_user=roles.migrator
        )
        _apply_calendar_quality_migration_in_transaction(cursor, schema=schema, roles=roles)
        _calendar_quality_assert_identity(
            cursor, session_user=roles.migrator, current_user=roles.owner
        )

        cursor.execute("RESET ROLE")
        _calendar_quality_assert_identity(
            cursor, session_user=roles.migrator, current_user=roles.migrator
        )
        cursor.execute("RESET SESSION AUTHORIZATION")
        _calendar_quality_assert_admin(cursor, roles)
        _seal_calendar_quality_in_transaction(cursor, schema=schema, roles=roles)
        _calendar_quality_require_shared_ledger(cursor, include_v5=True)
        _verify_calendar_quality_shared_complement(cursor, schema, roles, existing_roles=set(roles))
        return CalendarQualityPublishResult(CalendarQualityPublishDisposition.PUBLISHED)


def apply_seat_collection_migration(connection: Connection[Any]) -> None:
    """Apply the seat schema as version 2 in the existing worker ledger."""

    checksum = _seat_migration_checksum()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        _verify_ledger(cursor, _migration_checksum())
        cursor.execute(
            "SELECT version, name, checksum FROM data_worker_schema_migrations WHERE version = %s",
            (SEAT_MIGRATION_VERSION,),
        )
        rows = cursor.fetchall()
        if rows:
            if len(rows) != 1 or tuple(rows[0]) != (
                SEAT_MIGRATION_VERSION,
                SEAT_MIGRATION_NAME,
                checksum,
            ):
                raise ValueError("seat migration ledger checksum or name drift")
            _verify_seat_collection_schema(cursor)
            return

        cursor.execute(cast(Any, load_seat_collection_migration().decode("utf-8")))
        _verify_seat_collection_schema(cursor)
        cursor.execute(
            "INSERT INTO data_worker_schema_migrations "
            "(version, name, checksum, applied_at) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            (SEAT_MIGRATION_VERSION, SEAT_MIGRATION_NAME, checksum),
        )


def apply_data_worker_migrations(connection: Connection[Any]) -> None:
    """Apply only the shared V1-V4 data-worker migrations."""

    apply_precious_metals_migration(connection)
    apply_seat_collection_migration(connection)
    apply_calendar_snapshot_migration(connection)
    apply_official_calendar_migration(connection)


def apply_precious_metals_migration(connection: Connection[Any]) -> None:
    """Apply and verify the additive fund schema atomically on one connection."""

    checksum = _migration_checksum()
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (MIGRATION_LOCK_KEY,))
        _verify_base_schema(cursor)
        task_owned = _task_owned_tables(cursor)
        ledger_exists = "data_worker_schema_migrations" in task_owned

        if not ledger_exists and task_owned:
            raise ValueError("untracked or partial fund schema exists without migration ledger")
        if ledger_exists:
            _verify_task_owned_tables(cursor)
            _verify_ledger(cursor, checksum)
            _verify_fund_schema(cursor)
            return

        # The packaged SQL is a verified, canonical migration script.  Psycopg's
        # execute overload models single statements, so this script is an
        # intentional dynamic-SQL boundary within the adapter.
        cursor.execute(cast(Any, load_precious_metals_migration().decode("utf-8")))
        _verify_task_owned_tables(cursor)
        _verify_fund_schema(cursor)
        cursor.execute(
            "INSERT INTO data_worker_schema_migrations "
            "(version, name, checksum, applied_at) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            (MIGRATION_VERSION, MIGRATION_NAME, checksum),
        )
        _verify_ledger(cursor, checksum)
        _verify_fund_schema(cursor)


run_migration = apply_data_worker_migrations
