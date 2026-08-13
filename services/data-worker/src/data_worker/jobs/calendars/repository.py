"""Calendar repository.

Stores versioned exchange calendars with source provenance and an append-only
audit log. Manual corrections are recorded separately and never silently
overwrite the source data — the original sourced version stays intact.
"""

from __future__ import annotations

import itertools
from typing import Protocol

from ashare_contracts.calendar_holiday import Holiday


class CalendarRepository(Protocol):
    """Storage for versioned exchange calendars."""

    def save_version(self, source: str, year: int, holidays: list[Holiday]) -> str: ...

    def source_holidays(self, source: str) -> list[Holiday]: ...

    def apply_correction(self, date: str, reason: str, note: str, author: str) -> None: ...

    def audit_log(self) -> list[str]: ...


class InMemoryCalendarRepository:
    """In-memory implementation for tests and single-run jobs."""

    def __init__(self) -> None:
        self._by_source: dict[str, list[Holiday]] = {}
        self._audit: list[str] = []
        self._version_counter = itertools.count(1)

    def save_version(self, source: str, year: int, holidays: list[Holiday]) -> str:
        version_id = f"{source}:{year}:v{next(self._version_counter)}"
        self._by_source[source] = list(holidays)
        self._audit.append(f"SAVE {version_id} ({len(holidays)} holidays)")
        return version_id

    def source_holidays(self, source: str) -> list[Holiday]:
        return list(self._by_source.get(source, []))

    def apply_correction(self, date: str, reason: str, note: str, author: str) -> None:
        # Recorded as an audit entry only — the sourced version is not modified.
        self._audit.append(f"CORRECTION {date} {reason} by {author}: {note}")

    def audit_log(self) -> list[str]:
        return list(self._audit)
