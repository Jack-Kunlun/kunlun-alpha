"""PostgreSQL persistence for versioned, sparse calendar snapshots."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date
from threading import RLock
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID, uuid4

from ashare_contracts.calendar_holiday import Exchange as HolidayExchange
from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.calendar_holiday import Reason as HolidayReason
from data_worker.jobs.calendars.repository import (
    CalendarCorrection,
    CalendarOperationConflictError,
    CalendarRepository,
    CalendarScopeAmbiguityError,
    CalendarScopeError,
    _CalendarScope,
    _operation_key_hash,
    _prepare_snapshot,
    _snapshot_fingerprint,
    _validate_correction_date,
    _validate_scope,
    _validate_source,
)
from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from psycopg import Connection


_TRANSACTION_ERROR = "calendar repository requires an idle connection"
_INVALID_SCOPE = "calendar scope is invalid"
_AMBIGUOUS_SCOPE = "calendar scope is ambiguous"
_UNKNOWN_VERSION = "unknown calendar version"
_UNKNOWN_OPERATION = "calendar operation is unavailable"
_INVALID_TEXT = "calendar correction text is invalid"
_PERSISTENCE_ERROR = "calendar persistence failed"
_OPERATION_CONFLICT = "calendar operation conflicts with existing content"

_VERSION_TABLE = "calendar_snapshot_versions"
_HOLIDAY_TABLE = "calendar_snapshot_holidays"
_LATEST_TABLE = "calendar_snapshot_latest"
_CORRECTION_TABLE = "calendar_snapshot_corrections"
_AUDIT_TABLE = "calendar_snapshot_audit"


class CalendarRepositoryTransactionError(RuntimeError):
    """The adapter was called while its connection already had a transaction."""


class CalendarPersistenceError(RuntimeError):
    """A durable calendar operation could not be completed safely."""


CalendarRepositoryStorageError = CalendarPersistenceError


class _PostgresCursor:
    def execute(self, query: str, params: Sequence[object] | None = None) -> object:
        raise NotImplementedError

    def fetchone(self) -> tuple[object, ...] | None:
        raise NotImplementedError

    def fetchall(self) -> list[tuple[object, ...]]:
        raise NotImplementedError


_T = TypeVar("_T")


def _version_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if type(value) is str:
        try:
            return UUID(value)
        except (AttributeError, ValueError, TypeError):
            pass
    raise KeyError(_UNKNOWN_VERSION) from None


def _digest_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        result = value
    elif isinstance(value, memoryview):
        result = value.tobytes()
    elif type(value) is str:
        try:
            result = bytes.fromhex(value)
        except ValueError:
            result = b""
    else:
        result = b""
    if len(result) != hashlib.sha256().digest_size:
        raise CalendarPersistenceError(_UNKNOWN_OPERATION)
    return result


def _text(value: object, error: str = _INVALID_SCOPE) -> str:
    if type(value) is not str:
        raise CalendarScopeError(error)
    return value


def _scope_from_header(row: tuple[object, ...]) -> _CalendarScope:
    try:
        if len(row) < 3:
            raise CalendarPersistenceError(_UNKNOWN_VERSION)
        source = _text(row[0])
        exchange = _text(row[1])
        year = row[2]
        if type(year) is not int:
            raise CalendarPersistenceError(_UNKNOWN_VERSION)
        return _validate_scope(source, exchange, year)
    except CalendarScopeError:
        raise CalendarPersistenceError(_UNKNOWN_VERSION) from None


def _scope_lock_key(scope: _CalendarScope) -> str:
    return f"calendar-snapshot:{scope.source}:{scope.exchange}:{scope.year}"


def _holiday_from_row(row: tuple[object, ...]) -> Holiday:
    if len(row) < 4 or type(row[0]) is not date:
        raise CalendarPersistenceError(_UNKNOWN_VERSION)
    try:
        return Holiday(
            date=cast(Any, row[0]),
            exchange=HolidayExchange(_text(row[1])),
            reason=HolidayReason(_text(row[2])),
            note=None if row[3] is None else _text(row[3]),
        )
    except (TypeError, ValueError):
        raise CalendarPersistenceError(_UNKNOWN_VERSION) from None


class PostgresCalendarRepository(CalendarRepository):
    """Durable calendar repository using one transaction per public method.

    A connection belongs to one repository instance and must not be shared by
    callers across threads. The local mutex only serializes this instance; the
    scope advisory lock provides the database-level ordering for writers.
    """

    def __init__(self, connection: Connection[Any]) -> None:
        self._connection = connection
        self._mutex = RLock()

    def initialize(self) -> None:
        """Apply the registered worker migrations on this idle connection."""
        with self._mutex:
            self._ensure_idle()
            from data_worker.storage.migrations import apply_data_worker_migrations

            try:
                apply_data_worker_migrations(self._connection)
            except (
                CalendarScopeError,
                CalendarRepositoryTransactionError,
                CalendarPersistenceError,
                KeyError,
                ValueError,
            ):
                raise
            except Exception:
                raise CalendarPersistenceError(_PERSISTENCE_ERROR) from None

    def _ensure_idle(self) -> None:
        try:
            status = self._connection.info.transaction_status
        except AttributeError:
            raise CalendarRepositoryTransactionError(_TRANSACTION_ERROR) from None
        if status != TransactionStatus.IDLE:
            raise CalendarRepositoryTransactionError(_TRANSACTION_ERROR)

    def _run(self, operation: Callable[[_PostgresCursor], _T]) -> _T:
        with self._mutex:
            self._ensure_idle()
            try:
                transaction = cast(AbstractContextManager[Any], self._connection.transaction())
                with transaction:
                    cursor_context = cast(AbstractContextManager[Any], self._connection.cursor())
                    with cursor_context as raw_cursor:
                        return operation(cast(_PostgresCursor, raw_cursor))
            except (
                CalendarScopeError,
                CalendarRepositoryTransactionError,
                CalendarPersistenceError,
                KeyError,
            ):
                raise
            except Exception:
                raise CalendarPersistenceError(_PERSISTENCE_ERROR) from None

    def _require_idle(self) -> None:
        with self._mutex:
            self._ensure_idle()

    @staticmethod
    def _lock_scope(cursor: _PostgresCursor, scope: _CalendarScope) -> None:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (_scope_lock_key(scope),),
        )

    @staticmethod
    def _header(cursor: _PostgresCursor, version_id: UUID) -> _CalendarScope | None:
        cursor.execute(
            f"SELECT source, exchange, year FROM {_VERSION_TABLE} WHERE version_id = %s",
            (version_id,),
        )
        row = cursor.fetchone()
        return None if row is None else _scope_from_header(row)

    @staticmethod
    def _holidays(cursor: _PostgresCursor, version_id: UUID) -> list[Holiday]:
        cursor.execute(
            f"SELECT holiday_date, exchange, reason, note "
            f"FROM {_HOLIDAY_TABLE} WHERE version_id = %s ORDER BY ordinal",
            (version_id,),
        )
        return [_holiday_from_row(row) for row in cursor.fetchall()]

    def _save(
        self,
        cursor: _PostgresCursor,
        scope: _CalendarScope,
        holidays: tuple[Holiday, ...],
        fingerprint: bytes,
        operation_hash: bytes | None,
        proposed_version_id: UUID,
    ) -> str:
        self._lock_scope(cursor, scope)
        version_id = proposed_version_id
        if operation_hash is not None:
            cursor.execute(
                f"INSERT INTO {_VERSION_TABLE} "
                "(version_id, source, exchange, year, fingerprint, operation_key_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (operation_key_hash) DO NOTHING RETURNING version_id",
                (
                    proposed_version_id,
                    scope.source,
                    scope.exchange,
                    scope.year,
                    fingerprint,
                    operation_hash,
                ),
            )
            inserted = cursor.fetchone()
            if inserted is None:
                cursor.execute(
                    f"SELECT version_id, source, exchange, year, fingerprint "
                    f"FROM {_VERSION_TABLE} WHERE operation_key_hash = %s FOR SHARE",
                    (operation_hash,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise CalendarPersistenceError(_UNKNOWN_OPERATION)
                existing_id = _version_uuid(existing[0])
                existing_scope = _scope_from_header(existing[1:4])
                existing_fingerprint = _digest_bytes(existing[4])
                if existing_scope == scope and existing_fingerprint == fingerprint:
                    return str(existing_id)
                raise CalendarOperationConflictError(_OPERATION_CONFLICT)
            version_id = _version_uuid(inserted[0])
        else:
            cursor.execute(
                f"INSERT INTO {_VERSION_TABLE} "
                "(version_id, source, exchange, year, fingerprint) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    proposed_version_id,
                    scope.source,
                    scope.exchange,
                    scope.year,
                    fingerprint,
                ),
            )

        for ordinal, holiday in enumerate(holidays):
            cursor.execute(
                f"INSERT INTO {_HOLIDAY_TABLE} "
                "(version_id, source, exchange, year, ordinal, holiday_date, reason, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    version_id,
                    scope.source,
                    scope.exchange,
                    scope.year,
                    ordinal,
                    holiday.date,
                    holiday.reason.value,
                    holiday.note,
                ),
            )
        cursor.execute(
            f"INSERT INTO {_LATEST_TABLE} (source, exchange, year, version_id) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (source, exchange, year) DO UPDATE SET version_id = EXCLUDED.version_id",
            (scope.source, scope.exchange, scope.year, version_id),
        )
        cursor.execute(
            f"INSERT INTO {_AUDIT_TABLE} "
            "(audit_id, version_id, source, exchange, year, kind, entry) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(),
                version_id,
                scope.source,
                scope.exchange,
                scope.year,
                "SAVE",
                "calendar version saved",
            ),
        )
        return str(version_id)

    def save_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str | None = None,
        operation_id: str | None = None,
    ) -> str:
        self._require_idle()
        scope, snapshot = _prepare_snapshot(source, year, holidays, exchange)
        fingerprint = bytes.fromhex(_snapshot_fingerprint(scope, snapshot))
        operation_hash = (
            None if operation_id is None else bytes.fromhex(_operation_key_hash(operation_id))
        )
        return self._run(
            lambda cursor: self._save(
                cursor,
                scope,
                snapshot,
                fingerprint,
                operation_hash,
                uuid4(),
            )
        )

    def source_holidays(
        self,
        source: str,
        *,
        exchange: str | None = None,
        year: int | None = None,
    ) -> list[Holiday]:
        self._require_idle()
        valid_source = _validate_source(source)
        if (exchange is None) != (year is None):
            raise CalendarScopeError("calendar exchange and year must be provided together")
        explicit_scope = (
            None
            if exchange is None and year is None
            else _validate_scope(valid_source, cast(str, exchange), cast(int, year))
        )

        def read(cursor: _PostgresCursor) -> list[Holiday]:
            if explicit_scope is None:
                cursor.execute(
                    f"SELECT source, exchange, year, version_id FROM {_LATEST_TABLE} "
                    "WHERE source = %s ORDER BY exchange, year",
                    (valid_source,),
                )
                rows = cursor.fetchall()
                if not rows:
                    return []
                if len(rows) != 1:
                    raise CalendarScopeAmbiguityError(_AMBIGUOUS_SCOPE)
                version_id = _version_uuid(rows[0][3])
            else:
                cursor.execute(
                    f"SELECT version_id FROM {_LATEST_TABLE} "
                    "WHERE source = %s AND exchange = %s AND year = %s",
                    (explicit_scope.source, explicit_scope.exchange, explicit_scope.year),
                )
                row = cursor.fetchone()
                if row is None:
                    return []
                version_id = _version_uuid(row[0])
            return self._holidays(cursor, version_id)

        return self._run(read)

    def latest_version_id(self, source: str, exchange: str, year: int) -> str | None:
        self._require_idle()
        scope = _validate_scope(source, exchange, year)

        def read(cursor: _PostgresCursor) -> str | None:
            cursor.execute(
                f"SELECT version_id FROM {_LATEST_TABLE} "
                "WHERE source = %s AND exchange = %s AND year = %s",
                (scope.source, scope.exchange, scope.year),
            )
            row = cursor.fetchone()
            return None if row is None else str(_version_uuid(row[0]))

        return self._run(read)

    def find_operation_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str,
        operation_id: str,
    ) -> str | None:
        self._require_idle()
        scope, snapshot = _prepare_snapshot(source, year, holidays, exchange)
        fingerprint = bytes.fromhex(_snapshot_fingerprint(scope, snapshot))
        operation_hash = bytes.fromhex(_operation_key_hash(operation_id))

        def read(cursor: _PostgresCursor) -> str | None:
            cursor.execute(
                f"SELECT version_id, source, exchange, year, fingerprint "
                f"FROM {_VERSION_TABLE} WHERE operation_key_hash = %s",
                (operation_hash,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            if len(row) < 5:
                raise CalendarPersistenceError(_UNKNOWN_OPERATION)
            existing_id = _version_uuid(row[0])
            existing_scope = _scope_from_header(row[1:4])
            existing_fingerprint = _digest_bytes(row[4])
            if existing_scope == scope and existing_fingerprint == fingerprint:
                return str(existing_id)
            raise CalendarOperationConflictError(_OPERATION_CONFLICT)

        return self._run(read)

    def get_version(self, version_id: str) -> list[Holiday]:
        self._require_idle()
        parsed_id = _version_uuid(version_id)

        def read(cursor: _PostgresCursor) -> list[Holiday]:
            if self._header(cursor, parsed_id) is None:
                raise KeyError(_UNKNOWN_VERSION) from None
            return self._holidays(cursor, parsed_id)

        return self._run(read)

    def _resolve_correction_target(
        self,
        cursor: _PostgresCursor,
        version_id: str | None,
    ) -> tuple[UUID, _CalendarScope]:
        if version_id is not None:
            parsed_id = _version_uuid(version_id)
            scope = self._header(cursor, parsed_id)
            if scope is None:
                raise KeyError(_UNKNOWN_VERSION) from None
            return parsed_id, scope
        cursor.execute(f"SELECT version_id, source, exchange, year FROM {_VERSION_TABLE}")
        rows = cursor.fetchall()
        if not rows:
            raise CalendarScopeError(_INVALID_SCOPE)
        if len(rows) != 1:
            raise CalendarScopeAmbiguityError(_AMBIGUOUS_SCOPE)
        target_id = _version_uuid(rows[0][0])
        return target_id, _scope_from_header(rows[0][1:4])

    @staticmethod
    def _correction_texts(reason: str, note: str, author: str) -> tuple[str, str, str]:
        return (
            _text(reason, _INVALID_TEXT),
            _text(note, _INVALID_TEXT),
            _text(author, _INVALID_TEXT),
        )

    def apply_correction(
        self,
        date: str,
        reason: str,
        note: str,
        author: str,
        version_id: str | None = None,
    ) -> None:
        self._require_idle()
        reason_text, note_text, author_text = self._correction_texts(reason, note, author)

        def write(cursor: _PostgresCursor) -> None:
            target_id, scope = self._resolve_correction_target(cursor, version_id)
            self._lock_scope(cursor, scope)
            canonical_date = _validate_correction_date(date, scope.year)
            cursor.execute(
                f"INSERT INTO {_CORRECTION_TABLE} "
                "(correction_id, version_id, source, exchange, year, correction_date, "
                "reason, note, author) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    target_id,
                    scope.source,
                    scope.exchange,
                    scope.year,
                    canonical_date,
                    reason_text,
                    note_text,
                    author_text,
                ),
            )
            cursor.execute(
                f"INSERT INTO {_AUDIT_TABLE} "
                "(audit_id, version_id, source, exchange, year, kind, entry) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    target_id,
                    scope.source,
                    scope.exchange,
                    scope.year,
                    "CORRECTION",
                    "calendar correction applied",
                ),
            )

        self._run(write)

    def correction_overlay(self, version_id: str | None = None) -> list[CalendarCorrection]:
        self._require_idle()

        def read(cursor: _PostgresCursor) -> list[CalendarCorrection]:
            if version_id is None:
                cursor.execute(f"SELECT version_id, source, exchange, year FROM {_VERSION_TABLE}")
                rows = cursor.fetchall()
                if not rows:
                    return []
            target_id, _scope = self._resolve_correction_target(cursor, version_id)
            cursor.execute(
                f"SELECT correction_date, reason, note, author FROM {_CORRECTION_TABLE} "
                "WHERE version_id = %s ORDER BY persisted_at, correction_id",
                (target_id,),
            )
            result: list[CalendarCorrection] = []
            for row in cursor.fetchall():
                if len(row) < 4 or type(row[0]) is not date:
                    raise CalendarPersistenceError(_UNKNOWN_VERSION)
                result.append(
                    CalendarCorrection(
                        date=cast(Any, row[0]).isoformat(),
                        reason=_text(row[1], _INVALID_TEXT),
                        note=_text(row[2], _INVALID_TEXT),
                        author=_text(row[3], _INVALID_TEXT),
                        version_id=str(target_id),
                    )
                )
            return result

        return self._run(read)

    def audit_log(self) -> list[str]:
        self._require_idle()

        def read(cursor: _PostgresCursor) -> list[str]:
            cursor.execute(f"SELECT entry FROM {_AUDIT_TABLE} ORDER BY persisted_at, audit_id")
            return [_text(row[0], _INVALID_TEXT) for row in cursor.fetchall()]

        return self._run(read)


__all__ = [
    "CalendarPersistenceError",
    "CalendarRepositoryStorageError",
    "CalendarRepositoryTransactionError",
    "PostgresCalendarRepository",
]
