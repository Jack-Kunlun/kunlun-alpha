"""PostgreSQL durability and isolated fault injection for the paper runtime."""

from __future__ import annotations

import re
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import datetime
from secrets import token_hex
from typing import Any, Final, cast
from uuid import uuid4

import psycopg
from psycopg import Connection, Cursor, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .reliability import (
    GENESIS_DIGEST,
    AppendOutcome,
    ConcurrentWriteConflictError,
    DuplicateEventConflictError,
    EnduranceEvidenceScope,
    PaperDurableEventStore,
    PaperRuntimeEvent,
    PersistenceUnavailableError,
    RecoveryInvariantError,
    normalize_payload_items,
)

ISOLATED_DATABASE_PREFIX: Final = "kunlun_paper_endurance_"
_IDENTIFIER_PATTERN: Final = re.compile(r"^[a-z_][a-z0-9_]*$")
_DATABASE_SUFFIX_PATTERN: Final = re.compile(r"^[a-z0-9_]*[0-9a-f]{32}$")
_OWNERSHIP_MARKER_PREFIX: Final = "kunlun-paper-endurance-owner:"
_STREAMS_TABLE: Final = "paper_runtime_streams"
_EVENTS_TABLE: Final = "paper_runtime_events"

# Any is confined to the Psycopg row-factory boundary; every domain field is
# validated before it becomes a PaperRuntimeEvent.
Row = dict[str, Any]


def _validate_identifier(identifier: str, name: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"{name} must be a lowercase PostgreSQL identifier")


def _resolve_database_name(database_name: str | None) -> str:
    resolved = (
        database_name if database_name is not None else f"{ISOLATED_DATABASE_PREFIX}{uuid4().hex}"
    )
    _validate_identifier(resolved, "database_name")
    if not resolved.startswith(ISOLATED_DATABASE_PREFIX):
        raise ValueError(
            f"database_name must identify an isolated endurance database with prefix "
            f"{ISOLATED_DATABASE_PREFIX!r}"
        )
    suffix = resolved[len(ISOLATED_DATABASE_PREFIX) :]
    if not _DATABASE_SUFFIX_PATTERN.fullmatch(suffix):
        raise ValueError("database_name must end with an unpredictable 32-character UUID")
    return resolved


def _qualified(schema: str, table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def _require_string(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise RecoveryInvariantError(f"persisted {key} must be a non-empty string")
    return value


def _event_from_row(row: Row) -> PaperRuntimeEvent:
    occurred_at = row.get("occurred_at")
    sequence = row.get("sequence")
    payload = row.get("payload")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise RecoveryInvariantError("persisted occurred_at must be timezone-aware")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
        raise RecoveryInvariantError("persisted sequence must be a positive integer")
    if not isinstance(payload, Mapping):
        raise RecoveryInvariantError("persisted payload must be a JSON object")
    try:
        payload_items = normalize_payload_items(cast(Mapping[str, object], payload))
    except (TypeError, ValueError) as exc:
        raise RecoveryInvariantError(
            "persisted payload is outside the paper event contract"
        ) from exc
    return PaperRuntimeEvent(
        stream_id=_require_string(row, "stream_id"),
        event_id=_require_string(row, "event_id"),
        event_type=_require_string(row, "event_type"),
        sequence=sequence,
        occurred_at=occurred_at,
        payload_items=payload_items,
        prior_digest=_require_string(row, "prior_digest"),
        digest=_require_string(row, "digest"),
    )


class PostgresPaperEventStore(PaperDurableEventStore):
    """Persist hash-linked paper events with per-stream PostgreSQL CAS locking."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "public",
        connect_timeout_seconds: int = 2,
    ) -> None:
        if not dsn:
            raise ValueError("dsn must not be empty")
        _validate_identifier(schema, "schema")
        if connect_timeout_seconds < 1:
            raise ValueError("connect_timeout_seconds must be positive")
        self._dsn = dsn
        self._schema = schema
        self._connect_timeout_seconds = connect_timeout_seconds

    def initialize(self) -> None:
        """Create the isolated event tables idempotently."""

        streams = _qualified(self._schema, _STREAMS_TABLE)
        events = _qualified(self._schema, _EVENTS_TABLE)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self._schema))
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            stream_id TEXT PRIMARY KEY,
                            head_sequence BIGINT NOT NULL CHECK (head_sequence >= 0),
                            head_digest CHAR(64) NOT NULL
                        )
                        """
                    ).format(streams)
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE TABLE IF NOT EXISTS {} (
                            stream_id TEXT NOT NULL REFERENCES {} (stream_id),
                            event_id TEXT NOT NULL,
                            event_type TEXT NOT NULL,
                            sequence BIGINT NOT NULL CHECK (sequence > 0),
                            occurred_at TIMESTAMPTZ NOT NULL,
                            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
                            prior_digest CHAR(64) NOT NULL,
                            digest CHAR(64) NOT NULL,
                            PRIMARY KEY (stream_id, sequence),
                            UNIQUE (stream_id, event_id)
                        )
                        """
                    ).format(events, streams)
                )
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise PersistenceUnavailableError(
                "paper PostgreSQL persistence is unavailable during initialization"
            ) from exc

    def read_stream(self, stream_id: str) -> tuple[PaperRuntimeEvent, ...]:
        if not stream_id:
            raise ValueError("stream_id must not be empty")
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                return self._read_stream(cursor, stream_id)
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise PersistenceUnavailableError(
                "paper PostgreSQL persistence is unavailable during read"
            ) from exc

    def append_event(
        self,
        event: PaperRuntimeEvent,
        *,
        expected_head_digest: str,
    ) -> tuple[AppendOutcome, tuple[PaperRuntimeEvent, ...]]:
        streams = _qualified(self._schema, _STREAMS_TABLE)
        events = _qualified(self._schema, _EVENTS_TABLE)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (stream_id, head_sequence, head_digest)
                        VALUES (%s, 0, %s)
                        ON CONFLICT (stream_id) DO NOTHING
                        """
                    ).format(streams),
                    (event.stream_id, GENESIS_DIGEST),
                )
                cursor.execute(
                    sql.SQL(
                        "SELECT head_sequence, head_digest FROM {} WHERE stream_id = %s FOR UPDATE"
                    ).format(streams),
                    (event.stream_id,),
                )
                head = cursor.fetchone()
                if head is None:
                    raise RecoveryInvariantError("durable stream head disappeared during append")

                cursor.execute(
                    sql.SQL(
                        """
                        SELECT stream_id, event_id, event_type, sequence, occurred_at,
                               payload, prior_digest, digest
                          FROM {}
                         WHERE stream_id = %s AND event_id = %s
                        """
                    ).format(events),
                    (event.stream_id, event.event_id),
                )
                duplicate_row = cursor.fetchone()
                if duplicate_row is not None:
                    persisted = _event_from_row(duplicate_row)
                    if (
                        persisted.event_type != event.event_type
                        or persisted.payload_items != event.payload_items
                    ):
                        raise DuplicateEventConflictError(
                            f"event_id {event.event_id!r} was reused with different content"
                        )
                    return AppendOutcome.DUPLICATE, self._read_stream(cursor, event.stream_id)

                head_sequence = head.get("head_sequence")
                current_head = head.get("head_digest")
                if not isinstance(head_sequence, int) or isinstance(head_sequence, bool):
                    raise RecoveryInvariantError("durable stream head sequence is invalid")
                if not isinstance(current_head, str):
                    raise RecoveryInvariantError("durable stream head digest is invalid")
                if current_head != expected_head_digest:
                    raise ConcurrentWriteConflictError("durable stream head changed before append")
                if event.sequence != head_sequence + 1:
                    raise RecoveryInvariantError("event sequence is not contiguous")
                if event.prior_digest != current_head:
                    raise RecoveryInvariantError(
                        "event prior digest does not match the durable stream head"
                    )

                cursor.execute(
                    sql.SQL(
                        """
                        INSERT INTO {} (
                            stream_id, event_id, event_type, sequence, occurred_at,
                            payload, prior_digest, digest
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """
                    ).format(events),
                    (
                        event.stream_id,
                        event.event_id,
                        event.event_type,
                        event.sequence,
                        event.occurred_at,
                        Jsonb(dict(event.payload_items)),
                        event.prior_digest,
                        event.digest,
                    ),
                )
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET head_sequence = %s, head_digest = %s WHERE stream_id = %s"
                    ).format(streams),
                    (event.sequence, event.digest, event.stream_id),
                )
                return AppendOutcome.APPLIED, self._read_stream(cursor, event.stream_id)
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise PersistenceUnavailableError(
                "paper PostgreSQL persistence is unavailable during append"
            ) from exc

    def _connect(self) -> Connection[Row]:
        return cast(
            Connection[Row],
            psycopg.connect(
                self._dsn,
                connect_timeout=self._connect_timeout_seconds,
                row_factory=cast(Any, dict_row),
            ),
        )

    def _read_stream(
        self,
        cursor: Cursor[Row],
        stream_id: str,
    ) -> tuple[PaperRuntimeEvent, ...]:
        cursor.execute(
            sql.SQL(
                """
                SELECT stream_id, event_id, event_type, sequence, occurred_at,
                       payload, prior_digest, digest
                  FROM {}
                 WHERE stream_id = %s
                 ORDER BY sequence
                """
            ).format(_qualified(self._schema, _EVENTS_TABLE)),
            (stream_id,),
        )
        return tuple(_event_from_row(row) for row in cursor.fetchall())


class PostgresPaperFaultHarness:
    """Operate a disposable PostgreSQL database for formal endurance evidence."""

    evidence_scope = EnduranceEvidenceScope.DURABLE_ADAPTER
    fault_injection = "postgresql-database-connectivity-disable-and-backend-termination"
    storage_adapter = "postgresql"

    def __init__(
        self,
        *,
        admin_dsn: str,
        database_name: str | None = None,
        schema: str = "public",
        connect_timeout_seconds: int = 2,
        recovery_timeout_seconds: int = 30,
    ) -> None:
        resolved_database_name = _resolve_database_name(database_name)
        _validate_identifier(schema, "schema")
        if not admin_dsn:
            raise ValueError("admin_dsn must not be empty")
        if connect_timeout_seconds < 1 or recovery_timeout_seconds < 1:
            raise ValueError("PostgreSQL timeouts must be positive")
        self._admin_dsn = admin_dsn
        self._database_name = resolved_database_name
        self.evidence_target = resolved_database_name
        self._schema = schema
        self._connect_timeout_seconds = connect_timeout_seconds
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._target_dsn = make_conninfo(admin_dsn, dbname=resolved_database_name)
        self._ownership_marker = f"{_OWNERSHIP_MARKER_PREFIX}{token_hex(32)}"

    @property
    def database_name(self) -> str:
        return self._database_name

    def prepare_database(self) -> None:
        """Create a fresh isolated database and initialize its tables."""

        with self._admin_connection() as connection, connection.cursor() as cursor:
            self._assert_admin_database(cursor)
            cursor.execute(
                "SELECT datallowconn FROM pg_database WHERE datname = %s",
                (self._database_name,),
            )
            row = cursor.fetchone()
            if row is not None:
                raise ValueError("database_name already exists and cannot be reused")
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(self._database_name)
                )
            )
            self._write_ownership_marker(cursor)
        PostgresPaperEventStore(
            self._target_dsn,
            schema=self._schema,
            connect_timeout_seconds=self._connect_timeout_seconds,
        ).initialize()

    def drop_database(self) -> None:
        """Delete only the database created and owned by this harness run."""

        with self._admin_connection() as connection, connection.cursor() as cursor:
            self._assert_admin_database(cursor)
            self._assert_owned_database(cursor)
            try:
                self._set_connections(cursor, allowed=False)
                self._terminate_target_connections(cursor)
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(self._database_name)
                    )
                )
            except Exception:
                self._restore_connections_if_owned(cursor)
                raise

    def new_store(self) -> PostgresPaperEventStore:
        return PostgresPaperEventStore(
            self._target_dsn,
            schema=self._schema,
            connect_timeout_seconds=self._connect_timeout_seconds,
        )

    def active_connection_count(self) -> int:
        with self._admin_connection() as connection, connection.cursor() as cursor:
            self._assert_admin_database(cursor)
            self._assert_owned_database(cursor)
            cursor.execute(
                "SELECT count(*) AS connection_count FROM pg_stat_activity WHERE datname = %s",
                (self._database_name,),
            )
            row = cursor.fetchone()
            if row is None or not isinstance(row.get("connection_count"), int):
                raise RecoveryInvariantError("PostgreSQL connection baseline is unavailable")
            return cast(int, row["connection_count"])

    @contextmanager
    def database_outage(self) -> Generator[None, None, None]:
        """Reject and terminate connections only for the isolated database."""

        disabled = False
        try:
            with self._admin_connection() as connection, connection.cursor() as cursor:
                self._assert_admin_database(cursor)
                self._assert_owned_database(cursor)
                disabled = True
                self._set_connections(cursor, allowed=False)
                self._terminate_target_connections(cursor)
            yield
        finally:
            if disabled:
                with self._admin_connection() as connection, connection.cursor() as cursor:
                    self._assert_admin_database(cursor)
                    self._assert_owned_database(cursor)
                    self._set_connections(cursor, allowed=True)
                self._wait_until_available()

    def _admin_connection(self) -> Connection[Row]:
        return cast(
            Connection[Row],
            psycopg.connect(
                self._admin_dsn,
                autocommit=True,
                connect_timeout=self._connect_timeout_seconds,
                row_factory=cast(Any, dict_row),
            ),
        )

    def _assert_admin_database(self, cursor: Cursor[Row]) -> None:
        cursor.execute("SELECT current_database() AS database_name")
        row = cursor.fetchone()
        database_name = None if row is None else row.get("database_name")
        if not isinstance(database_name, str):
            raise ValueError("admin_dsn control database could not be verified")
        if database_name == self._database_name or database_name.startswith(
            ISOLATED_DATABASE_PREFIX
        ):
            raise ValueError(
                "admin_dsn must connect to a control database outside the endurance namespace"
            )

    def _write_ownership_marker(self, cursor: Cursor[Row]) -> None:
        cursor.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(self._database_name),
                sql.Literal(self._ownership_marker),
            ),
        )

    def _assert_owned_database(self, cursor: Cursor[Row]) -> None:
        cursor.execute(
            """
            SELECT datname,
                   shobj_description(oid, 'pg_database') AS ownership_marker
              FROM pg_database
             WHERE datname = %s
            """,
            (self._database_name,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RecoveryInvariantError("isolated endurance database ownership marker is missing")
        if row.get("ownership_marker") != self._ownership_marker:
            raise RecoveryInvariantError(
                "isolated endurance database ownership marker does not match this harness"
            )

    def _restore_connections_if_owned(self, cursor: Cursor[Row]) -> None:
        self._assert_owned_database(cursor)
        self._set_connections(cursor, allowed=True)

    def _set_connections(self, cursor: Cursor[Row], *, allowed: bool) -> None:
        setting = sql.SQL("true") if allowed else sql.SQL("false")
        cursor.execute(
            sql.SQL("ALTER DATABASE {} WITH ALLOW_CONNECTIONS {}").format(
                sql.Identifier(self._database_name),
                setting,
            )
        )

    def _terminate_target_connections(self, cursor: Cursor[Row]) -> None:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
              FROM pg_stat_activity
             WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (self._database_name,),
        )

    def _wait_until_available(self) -> None:
        with self._admin_connection() as connection, connection.cursor() as cursor:
            self._assert_admin_database(cursor)
            self._assert_owned_database(cursor)
        deadline = time.monotonic() + self._recovery_timeout_seconds
        while True:
            try:
                with (
                    psycopg.connect(
                        self._target_dsn,
                        connect_timeout=self._connect_timeout_seconds,
                    ) as connection,
                    connection.cursor() as cursor,
                ):
                    cursor.execute("SELECT 1")
                return
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise PersistenceUnavailableError(
                        "isolated paper endurance database did not recover in time"
                    ) from None
                time.sleep(0.1)
