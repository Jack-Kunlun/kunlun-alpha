"""Calendar source snapshots with compound exchange/year isolation.

Calendar source snapshots are immutable and corrections are kept as a separate
audited overlay. The in-memory implementation mirrors the later durable port
without introducing persistence into this node.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ashare_contracts.calendar_holiday import (
    Exchange as HolidayExchange,
)
from ashare_contracts.calendar_holiday import (
    Holiday,
)
from ashare_contracts.calendar_holiday import (
    Reason as HolidayReason,
)

_INVALID_SCOPE = "calendar scope is invalid"
_AMBIGUOUS_SCOPE = "calendar scope is ambiguous"
_SCOPE_PAIR_REQUIRED = "calendar exchange and year must be provided together"
_UNKNOWN_VERSION = "unknown calendar version"
_INVALID_OPERATION = "calendar operation is invalid"
_OPERATION_CONFLICT = "calendar operation conflicts with existing content"


class CalendarScopeError(ValueError):
    """The source, exchange, year, or correction scope is invalid."""


class CalendarScopeAmbiguityError(CalendarScopeError):
    """A source-only operation would need to guess between multiple scopes."""


class CalendarOperationConflictError(CalendarScopeError):
    """An idempotency key was reused for different calendar content."""


@dataclass(frozen=True)
class _CalendarScope:
    source: str
    exchange: str
    year: int


@dataclass(frozen=True)
class CalendarCorrection:
    """Audited correction metadata kept outside sourced calendar snapshots."""

    date: str
    reason: str
    note: str
    author: str
    version_id: str | None = None


def _validate_source(source: str) -> str:
    if type(source) is not str or not source:
        raise CalendarScopeError(_INVALID_SCOPE)
    return source


def _validate_exchange(exchange: str) -> str:
    if type(exchange) is not str:
        raise CalendarScopeError(_INVALID_SCOPE)
    try:
        return HolidayExchange(exchange).value
    except ValueError:
        raise CalendarScopeError(_INVALID_SCOPE) from None


def _validate_year(year: int) -> int:
    if type(year) is not int or not 1 <= year <= 9999:
        raise CalendarScopeError(_INVALID_SCOPE)
    return year


def _validate_scope(source: str, exchange: str, year: int) -> _CalendarScope:
    return _CalendarScope(
        source=_validate_source(source),
        exchange=_validate_exchange(exchange),
        year=_validate_year(year),
    )


def _validate_operation_id(operation_id: str) -> str:
    if type(operation_id) is not str or not operation_id:
        raise CalendarScopeError(_INVALID_OPERATION)
    return operation_id


def _operation_key_hash(operation_id: str) -> str:
    return hashlib.sha256(_validate_operation_id(operation_id).encode("utf-8")).hexdigest()


def _snapshot_fingerprint(scope: _CalendarScope, holidays: tuple[Holiday, ...]) -> str:
    payload = {
        "source": scope.source,
        "exchange": scope.exchange,
        "year": scope.year,
        "holidays": [
            {
                "date": holiday.date.isoformat(),
                "exchange": holiday.exchange.value,
                "reason": holiday.reason.value,
                "note": holiday.note,
            }
            for holiday in holidays
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _holiday_identity(holiday: Holiday) -> tuple[str, int]:
    if type(holiday) is not Holiday:
        raise CalendarScopeError(_INVALID_SCOPE)
    try:
        if (
            type(holiday.exchange) is not HolidayExchange
            or type(holiday.date) is not date
            or type(holiday.reason) is not HolidayReason
            or (holiday.note is not None and type(holiday.note) is not str)
        ):
            raise CalendarScopeError(_INVALID_SCOPE)
        exchange = holiday.exchange.value
        year = holiday.date.year
    except (AttributeError, TypeError, ValueError):
        raise CalendarScopeError(_INVALID_SCOPE) from None
    if type(exchange) is not str or type(year) is not int:
        raise CalendarScopeError(_INVALID_SCOPE)
    return exchange, year


def _prepare_snapshot(
    source: str,
    year: int,
    holidays: list[Holiday],
    exchange: str | None,
) -> tuple[_CalendarScope, tuple[Holiday, ...]]:
    valid_source = _validate_source(source)
    valid_year = _validate_year(year)
    if type(holidays) is not list:
        raise CalendarScopeError(_INVALID_SCOPE)

    canonical_exchange = _validate_exchange(exchange) if exchange is not None else None
    identities = [_holiday_identity(holiday) for holiday in holidays]
    if canonical_exchange is None:
        if not identities:
            raise CalendarScopeError(_INVALID_SCOPE)
        canonical_exchange = _validate_exchange(identities[0][0])

    for row_exchange, row_year in identities:
        if row_exchange != canonical_exchange or row_year != valid_year:
            raise CalendarScopeError(_INVALID_SCOPE)

    try:
        copied_holidays = tuple(holiday.model_copy(deep=True) for holiday in holidays)
    except (AttributeError, TypeError, ValueError):
        raise CalendarScopeError(_INVALID_SCOPE) from None

    return (
        _CalendarScope(
            source=valid_source,
            exchange=canonical_exchange,
            year=valid_year,
        ),
        copied_holidays,
    )


def _validate_correction_date(value: str, year: int) -> str:
    if type(value) is not str:
        raise CalendarScopeError(_INVALID_SCOPE)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise CalendarScopeError(_INVALID_SCOPE) from None
    if parsed.isoformat() != value or parsed.year != year:
        raise CalendarScopeError(_INVALID_SCOPE)
    return parsed.isoformat()


class CalendarRepository(Protocol):
    """Storage for versioned exchange calendars."""

    def save_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str | None = None,
        operation_id: str | None = None,
    ) -> str: ...

    def source_holidays(
        self,
        source: str,
        *,
        exchange: str | None = None,
        year: int | None = None,
    ) -> list[Holiday]: ...

    def latest_version_id(self, source: str, exchange: str, year: int) -> str | None: ...

    def find_operation_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str,
        operation_id: str,
    ) -> str | None: ...

    def get_version(self, version_id: str) -> list[Holiday]: ...

    def correction_overlay(self, version_id: str | None = None) -> list[CalendarCorrection]: ...

    def apply_correction(
        self,
        date: str,
        reason: str,
        note: str,
        author: str,
        version_id: str | None = None,
    ) -> None: ...

    def audit_log(self) -> list[str]: ...


class InMemoryCalendarRepository:
    """In-memory implementation for tests and single-run jobs."""

    def __init__(self) -> None:
        self._versions: dict[str, tuple[Holiday, ...]] = {}
        self._version_scopes: dict[str, _CalendarScope] = {}
        self._by_scope: dict[_CalendarScope, str] = {}
        self._scopes_by_source: dict[str, set[_CalendarScope]] = {}
        self._corrections: list[CalendarCorrection] = []
        self._audit: list[str] = []
        self._operation_keys: dict[str, tuple[_CalendarScope, str, str]] = {}
        self._version_counter = itertools.count(1)

    def save_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str | None = None,
        operation_id: str | None = None,
    ) -> str:
        scope, snapshot = _prepare_snapshot(source, year, holidays, exchange)
        fingerprint = _snapshot_fingerprint(scope, snapshot)
        operation_hash = None if operation_id is None else _operation_key_hash(operation_id)
        if operation_hash is not None:
            existing = self._operation_keys.get(operation_hash)
            if existing is not None:
                existing_scope, existing_fingerprint, existing_version = existing
                if existing_scope != scope or existing_fingerprint != fingerprint:
                    raise CalendarOperationConflictError(_OPERATION_CONFLICT)
                return existing_version
        version_id = f"{scope.source}:{scope.year}:v{next(self._version_counter)}"
        self._versions[version_id] = snapshot
        self._version_scopes[version_id] = scope
        self._by_scope[scope] = version_id
        self._scopes_by_source.setdefault(scope.source, set()).add(scope)
        if operation_hash is not None:
            self._operation_keys[operation_hash] = (scope, fingerprint, version_id)
        self._audit.append(f"SAVE {version_id} ({len(snapshot)} holidays)")
        return version_id

    def source_holidays(
        self,
        source: str,
        *,
        exchange: str | None = None,
        year: int | None = None,
    ) -> list[Holiday]:
        scope = self._resolve_read_scope(source, exchange=exchange, year=year)
        if scope is None:
            return []
        version_id = self._by_scope.get(scope)
        if version_id is None:
            return []
        return self.get_version(version_id)

    def latest_version_id(self, source: str, exchange: str, year: int) -> str | None:
        scope = _validate_scope(source, exchange, year)
        return self._by_scope.get(scope)

    def find_operation_version(
        self,
        source: str,
        year: int,
        holidays: list[Holiday],
        *,
        exchange: str,
        operation_id: str,
    ) -> str | None:
        scope, snapshot = _prepare_snapshot(source, year, holidays, exchange)
        fingerprint = _snapshot_fingerprint(scope, snapshot)
        operation_hash = _operation_key_hash(operation_id)
        existing = self._operation_keys.get(operation_hash)
        if existing is None:
            return None
        existing_scope, existing_fingerprint, existing_version = existing
        if existing_scope != scope or existing_fingerprint != fingerprint:
            raise CalendarOperationConflictError(_OPERATION_CONFLICT)
        return existing_version

    def _resolve_read_scope(
        self,
        source: str,
        *,
        exchange: str | None,
        year: int | None,
    ) -> _CalendarScope | None:
        valid_source = _validate_source(source)
        if (exchange is None) != (year is None):
            raise CalendarScopeError(_SCOPE_PAIR_REQUIRED)
        if exchange is None and year is None:
            scopes = self._scopes_by_source.get(valid_source, set())
            if not scopes:
                return None
            if len(scopes) != 1:
                raise CalendarScopeAmbiguityError(_AMBIGUOUS_SCOPE)
            return next(iter(scopes))
        assert exchange is not None and year is not None
        return _CalendarScope(
            source=valid_source,
            exchange=_validate_exchange(exchange),
            year=_validate_year(year),
        )

    def get_version(self, version_id: str) -> list[Holiday]:
        """Return an independent copy of one immutable sourced snapshot."""
        self._require_version(version_id)
        return [holiday.model_copy(deep=True) for holiday in self._versions[version_id]]

    def _require_version(self, version_id: str) -> _CalendarScope:
        if type(version_id) is not str or version_id not in self._versions:
            raise KeyError(_UNKNOWN_VERSION) from None
        return self._version_scopes[version_id]

    def version_holidays(self, version_id: str) -> list[Holiday]:
        """Compatibility alias for retrieving a historical version."""
        return self.get_version(version_id)

    def apply_correction(
        self,
        date: str,
        reason: str,
        note: str,
        author: str,
        version_id: str | None = None,
    ) -> None:
        target_version_id = self._resolve_correction_version(version_id)
        target_scope = self._version_scopes[target_version_id]
        canonical_date = _validate_correction_date(date, target_scope.year)
        correction = CalendarCorrection(
            date=canonical_date,
            reason=reason,
            note=note,
            author=author,
            version_id=target_version_id,
        )
        self._corrections.append(correction)
        self._audit.append(
            f"CORRECTION {canonical_date} {reason} for {target_version_id} by {author}: {note}"
        )

    def _resolve_correction_version(self, version_id: str | None) -> str:
        if version_id is not None:
            self._require_version(version_id)
            return version_id
        if not self._versions:
            raise CalendarScopeError(_INVALID_SCOPE)
        if len(self._versions) != 1:
            raise CalendarScopeAmbiguityError(_AMBIGUOUS_SCOPE)
        return next(iter(self._versions))

    def correction_overlay(self, version_id: str | None = None) -> list[CalendarCorrection]:
        """Return audited corrections for one exact sourced snapshot."""
        if version_id is None:
            if not self._versions:
                return []
            if len(self._versions) != 1:
                raise CalendarScopeAmbiguityError(_AMBIGUOUS_SCOPE)
            target_version_id = next(iter(self._versions))
        else:
            self._require_version(version_id)
            target_version_id = version_id
        return [
            correction
            for correction in self._corrections
            if correction.version_id == target_version_id
        ]

    def corrections(self, version_id: str | None = None) -> list[CalendarCorrection]:
        """Compatibility alias for the audited calendar correction overlay."""
        return self.correction_overlay(version_id)

    def audit_log(self) -> list[str]:
        return list(self._audit)
