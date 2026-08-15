"""Verified additive PostgreSQL migration for precious-metals fund storage.

The SQL lives only in the packaged ``precious_metals_migration.sql`` resource.
This module owns the transaction, advisory lock, base-schema preflight, ledger
checksum, and exact post-apply schema verification.  It never rewrites the
P1-R05 version-1 tables.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
from typing import TYPE_CHECKING, Any, NamedTuple, cast

if TYPE_CHECKING:
    from psycopg import Connection


MIGRATION_VERSION = 1
MIGRATION_NAME = "precious_metals_migration"
MIGRATION_LOCK_KEY = "kunlun-alpha.schema-migrations"
_RESOURCE_NAME = "precious_metals_migration.sql"

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


# Kept as a compatibility export for existing callers; the source of truth is
# still the packaged bytes above, never a duplicated SQL literal.
PRECIOUS_METALS_MIGRATION = load_precious_metals_migration().decode("utf-8")


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


def _verify_constraints(cursor: Any) -> None:
    tables = _FUND_TABLES
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
                str(expression) if expression is not None else None,
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
        for spec in _EXPECTED_CONSTRAINTS
    }
    missing = expected - actual
    extra = actual - expected
    if missing:
        item = sorted(missing, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"schema drift: missing constraint {item.table}.{item.name}")
    if extra:
        item = sorted(extra, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"schema drift: unexpected constraint {item.table}.{item.name}")


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


def _verify_indexes(cursor: Any) -> None:
    tables = _FUND_TABLES
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
        for spec in (*_EXPECTED_INDEXES, *_EXPECTED_CONSTRAINT_INDEXES)
    }
    missing = expected - actual
    extra = actual - expected
    if missing:
        item = sorted(missing, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"schema drift: missing index {item.table}.{item.name}")
    if extra:
        item = sorted(extra, key=lambda spec: (spec.table, spec.name))[0]
        raise ValueError(f"schema drift: unexpected index {item.table}.{item.name}")


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
    if len(rows) != 1:
        raise ValueError("schema migration ledger has unexpected rows")
    version, name, recorded_checksum = rows[0]
    if (version, name, recorded_checksum) != (MIGRATION_VERSION, MIGRATION_NAME, checksum):
        raise ValueError("schema migration ledger checksum or name drift")


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


run_migration = apply_precious_metals_migration
