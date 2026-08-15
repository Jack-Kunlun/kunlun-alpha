"""Synchronous PostgreSQL task store with database-time owner CAS leases."""

from __future__ import annotations

import copy
import re
import secrets
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, LiteralString, cast

import psycopg
from psycopg import Connection, Cursor
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from data_worker.scheduler.scheduler import JsonValue, TaskRecord, TaskStatus
from data_worker.scheduler.store import (
    LeaseToken,
    TaskStore,
    optional_utc_datetime,
    validate_error_category,
    validate_json_payload,
)

_IDENTIFIER_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_TASKS_TABLE = "tasks"
_CHECKPOINTS_TABLE = "checkpoints"

Row = dict[str, Any]


class PostgresTaskStore(TaskStore):
    """Persist scheduler state in PostgreSQL using synchronous Psycopg APIs.

    The store never compares lease timestamps with a process clock. Lease
    eligibility and expiry are evaluated by PostgreSQL's ``CURRENT_TIMESTAMP``
    in the conditional update statement, making acquisition a single owner-CAS
    operation that remains correct across process restarts.
    """

    def __init__(
        self,
        connection: str | Connection[Row],
        *,
        schema: str = "public",
        task_kind: str = "data-worker",
        max_attempts: int = 3,
    ) -> None:
        _validate_identifier(schema, "schema")
        if not task_kind:
            raise ValueError("task_kind must not be empty")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._connection: Connection[Row]
        self._owns_connection = isinstance(connection, str)
        if isinstance(connection, str):
            self._connection = cast(
                Connection[Row], psycopg.connect(connection, row_factory=cast(Any, dict_row))
            )
        else:
            self._connection = connection
        self._schema = schema
        self._task_kind = task_kind
        self._max_attempts = max_attempts

    def close(self) -> None:
        """Close a connection created by this store."""

        if self._owns_connection and not self._connection.closed:
            self._connection.close()

    def get(self, task_id: str) -> TaskRecord:
        _validate_task_id(task_id)
        with self._transaction() as cursor:
            cursor.execute(
                _sql(f"""
                INSERT INTO {self._table(_TASKS_TABLE)}
                  (id, kind, status, attempts, max_attempts, lease_token, lease_expires_at,
                   next_run_at, last_error_category, last_error_detail,
                   dead_letter_detail, created_at, updated_at)
                VALUES (%s, %s, 'PENDING', 0, %s, NULL, NULL, NULL, NULL, NULL,
                        NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO NOTHING
                """),
                (task_id, self._task_kind, self._max_attempts),
            )
            cursor.execute(
                _sql(f"SELECT * FROM {self._table(_TASKS_TABLE)} WHERE id = %s"),
                (task_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"task {task_id} was not found after insert")
            return _record_from_row(row)

    def acquire_lease(self, task_id: str, lease_seconds: float) -> LeaseToken | None:
        _validate_task_id(task_id)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        token = secrets.token_urlsafe(32)
        with self._transaction() as cursor:
            cursor.execute(
                _sql(f"""
                INSERT INTO {self._table(_TASKS_TABLE)} AS current_task
                  (id, kind, status, attempts, max_attempts, lease_token, lease_expires_at,
                   next_run_at, last_error_category, last_error_detail,
                   dead_letter_detail, created_at, updated_at)
                VALUES (%s, %s, 'RUNNING', 1, %s, %s,
                        CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                        NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE
                  SET status = CASE
                                   WHEN current_task.attempts >= current_task.max_attempts
                                     THEN 'DEAD'
                                   ELSE 'RUNNING'
                               END,
                      attempts = CASE
                                   WHEN current_task.attempts >= current_task.max_attempts
                                     THEN current_task.attempts
                                   ELSE current_task.attempts + 1
                                 END,
                      lease_token = CASE
                                      WHEN current_task.attempts >= current_task.max_attempts
                                        THEN NULL
                                      ELSE EXCLUDED.lease_token
                                    END,
                      lease_expires_at = CASE
                                          WHEN current_task.attempts >= current_task.max_attempts
                                            THEN NULL
                                          ELSE EXCLUDED.lease_expires_at
                                        END,
                      next_run_at = CASE
                                     WHEN current_task.attempts >= current_task.max_attempts
                                       THEN NULL
                                     ELSE current_task.next_run_at
                                   END,
                      dead_letter_detail = CASE
                                             WHEN current_task.attempts >= current_task.max_attempts
                                               THEN '{{"message":"retry limit reached"}}'::jsonb
                                             ELSE current_task.dead_letter_detail
                                           END,
                      updated_at = CURRENT_TIMESTAMP
                WHERE current_task.status IN ('PENDING', 'FAILED', 'RUNNING')
                  AND (current_task.next_run_at IS NULL
                       OR current_task.next_run_at <= CURRENT_TIMESTAMP)
                  AND (current_task.lease_token IS NULL
                       OR current_task.lease_expires_at IS NULL
                       OR current_task.lease_expires_at <= CURRENT_TIMESTAMP)
                RETURNING lease_token, status
                """),
                (task_id, self._task_kind, self._max_attempts, token, lease_seconds),
            )
            row = cursor.fetchone()
            if row is None or row["status"] == "DEAD":
                return None
            return cast(str, row["lease_token"])

    def release_lease(self, task_id: str, lease_token: LeaseToken) -> bool:
        return self._mutate_lease(
            task_id,
            lease_token,
            f"""
            UPDATE {self._table(_TASKS_TABLE)}
               SET lease_token = NULL,
                   lease_expires_at = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = %s AND lease_token = %s
               AND lease_expires_at > CURRENT_TIMESTAMP
            """,
        )

    def mark_succeeded(self, task_id: str, lease_token: LeaseToken) -> bool:
        return self._mutate_lease(
            task_id,
            lease_token,
            f"""
            UPDATE {self._table(_TASKS_TABLE)}
               SET status = 'SUCCEEDED',
                   lease_token = NULL,
                   lease_expires_at = NULL,
                   next_run_at = NULL,
                   last_error_category = NULL,
                   last_error_detail = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = %s AND lease_token = %s
               AND lease_expires_at > CURRENT_TIMESTAMP
            """,
        )

    def mark_failed(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        next_run_at: datetime | None = None,
    ) -> bool:
        validated_category = validate_error_category(error_category)
        validated_detail = validate_json_payload(error_detail, "error_detail")
        normalized_next_run = optional_utc_datetime(next_run_at)
        return self._mutate_lease(
            task_id,
            lease_token,
            f"""
            UPDATE {self._table(_TASKS_TABLE)}
               SET status = CASE
                                WHEN attempts >= max_attempts THEN 'DEAD'
                                ELSE 'FAILED'
                            END,
                   lease_token = NULL,
                   lease_expires_at = NULL,
                   next_run_at = CASE
                                     WHEN attempts >= max_attempts THEN NULL
                                     ELSE %s::timestamptz
                                 END,
                   last_error_category = %s,
                   last_error_detail = %s,
                   dead_letter_detail = CASE
                                           WHEN attempts >= max_attempts THEN %s
                                           ELSE dead_letter_detail
                                       END,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = %s AND lease_token = %s
               AND lease_expires_at > CURRENT_TIMESTAMP
            """,
            parameters=(
                normalized_next_run,
                validated_category,
                _json_parameter(validated_detail),
                _json_parameter({"message": "retry limit reached"}),
            ),
        )

    def mark_dead(
        self,
        task_id: str,
        lease_token: LeaseToken,
        *,
        error_category: str | None = None,
        error_detail: JsonValue | None = None,
        dead_letter_detail: JsonValue | None = None,
    ) -> bool:
        validated_category = validate_error_category(error_category)
        validated_error = validate_json_payload(error_detail, "error_detail")
        validated_dead = validate_json_payload(dead_letter_detail, "dead_letter_detail")
        return self._mutate_lease(
            task_id,
            lease_token,
            f"""
            UPDATE {self._table(_TASKS_TABLE)}
               SET status = 'DEAD',
                   lease_token = NULL,
                   lease_expires_at = NULL,
                   next_run_at = NULL,
                   last_error_category = %s,
                   last_error_detail = %s,
                   dead_letter_detail = %s,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = %s AND lease_token = %s
               AND lease_expires_at > CURRENT_TIMESTAMP
            """,
            parameters=(
                validated_category,
                _json_parameter(validated_error),
                _json_parameter(validated_dead),
            ),
        )

    def save_checkpoint(self, task_id: str, lease_token: LeaseToken, checkpoint: JsonValue) -> bool:
        _validate_task_id(task_id)
        validated = validate_json_payload(checkpoint, "checkpoint")
        with self._transaction() as cursor:
            cursor.execute(
                _sql(f"""
                UPDATE {self._table(_TASKS_TABLE)}
                   SET updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s AND lease_token = %s
                   AND lease_expires_at > CURRENT_TIMESTAMP
                """),
                (task_id, lease_token),
            )
            if cursor.rowcount != 1:
                return False
            cursor.execute(
                _sql(f"""
                INSERT INTO {self._table(_CHECKPOINTS_TABLE)} (task_id, state, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (task_id) DO UPDATE
                  SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at
                """),
                (task_id, _json_parameter(validated)),
            )
            return True

    def get_checkpoint(self, task_id: str) -> JsonValue | None:
        _validate_task_id(task_id)
        with self._transaction() as cursor:
            cursor.execute(
                _sql(f"SELECT state FROM {self._table(_CHECKPOINTS_TABLE)} WHERE task_id = %s"),
                (task_id,),
            )
            row = cursor.fetchone()
            return None if row is None else copy.deepcopy(row["state"])

    def _mutate_lease(
        self,
        task_id: str,
        lease_token: LeaseToken,
        statement: str,
        *,
        parameters: tuple[object, ...] = (),
    ) -> bool:
        _validate_task_id(task_id)
        with self._transaction() as cursor:
            cursor.execute(_sql(statement), (*parameters, task_id, lease_token))
            return cursor.rowcount == 1

    @contextmanager
    def _transaction(self) -> Generator[Cursor[Row], None, None]:
        with (
            self._connection.transaction(),
            self._connection.cursor(row_factory=cast(Any, dict_row)) as cursor,
        ):
            yield cursor

    def _table(self, name: str) -> str:
        return f"{_quote_identifier(self._schema)}.{_quote_identifier(name)}"


def _record_from_row(row: Mapping[str, object]) -> TaskRecord:
    status = row.get("status")
    if status not in {"PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DEAD"}:
        raise ValueError(f"unknown task status: {status!r}")
    created_at = _required_datetime(row, "created_at")
    updated_at = _required_datetime(row, "updated_at")
    return TaskRecord(
        task_id=cast(str, row["id"]),
        kind=cast(str, row["kind"]),
        status=cast(TaskStatus, status),
        attempts=cast(int, row["attempts"]),
        max_attempts=cast(int, row["max_attempts"]),
        lease_token=cast(str | None, row.get("lease_token")),
        lease_expires_at=_optional_datetime(row.get("lease_expires_at")),
        next_run_at=_optional_datetime(row.get("next_run_at")),
        error_category=cast(str | None, row.get("last_error_category")),
        error_detail=row.get("last_error_detail"),
        dead_letter_detail=row.get("dead_letter_detail"),
        created_at=created_at,
        updated_at=updated_at,
    )


def _json_parameter(value: JsonValue | None) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def _required_datetime(row: Mapping[str, object], field_name: str) -> datetime:
    value = row.get(field_name)
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    return _ensure_utc(value)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("timestamp field must be a datetime or null")
    return _ensure_utc(value)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _validate_task_id(task_id: str) -> None:
    if not task_id or len(task_id) > 256:
        raise ValueError("task_id must be 1-256 characters")


def _validate_identifier(identifier: str, name: str) -> None:
    if not _IDENTIFIER_PATTERN.fullmatch(identifier):
        raise ValueError(f"unsafe {name}: {identifier}")


def _quote_identifier(identifier: str) -> str:
    _validate_identifier(identifier, "SQL identifier")
    return f'"{identifier}"'


def _sql(statement: str) -> LiteralString:
    """Mark validated SQL templates for Psycopg's LiteralString boundary."""

    return cast(LiteralString, statement)
