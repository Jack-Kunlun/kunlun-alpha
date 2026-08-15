"""Calendar repository.

Calendar source snapshots are immutable and corrections are kept as a separate
audited overlay.  The in-memory implementation mirrors the later durable port
without introducing persistence into this node.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Protocol

from ashare_contracts.calendar_holiday import Holiday


@dataclass(frozen=True)
class CalendarCorrection:
    """Audited correction metadata kept outside sourced calendar snapshots."""

    date: str
    reason: str
    note: str
    author: str
    version_id: str | None = None


class CalendarRepository(Protocol):
    """Storage for versioned exchange calendars."""

    def save_version(self, source: str, year: int, holidays: list[Holiday]) -> str: ...

    def source_holidays(self, source: str) -> list[Holiday]: ...

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
        self._by_source: dict[str, str] = {}
        self._versions: dict[str, tuple[Holiday, ...]] = {}
        self._corrections: list[CalendarCorrection] = []
        self._audit: list[str] = []
        self._version_counter = itertools.count(1)

    def save_version(self, source: str, year: int, holidays: list[Holiday]) -> str:
        version_id = f"{source}:{year}:v{next(self._version_counter)}"
        self._versions[version_id] = tuple(holiday.model_copy(deep=True) for holiday in holidays)
        self._by_source[source] = version_id
        self._audit.append(f"SAVE {version_id} ({len(holidays)} holidays)")
        return version_id

    def source_holidays(self, source: str) -> list[Holiday]:
        version_id = self._by_source.get(source)
        if version_id is None:
            return []
        return self.get_version(version_id)

    def get_version(self, version_id: str) -> list[Holiday]:
        """Return an independent copy of one immutable sourced snapshot."""
        try:
            holidays = self._versions[version_id]
        except KeyError as exc:
            raise KeyError(f"unknown calendar version: {version_id}") from exc
        return [holiday.model_copy(deep=True) for holiday in holidays]

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
        if version_id is not None and version_id not in self._versions:
            raise KeyError(f"unknown calendar version: {version_id}")
        correction = CalendarCorrection(
            date=date,
            reason=reason,
            note=note,
            author=author,
            version_id=version_id,
        )
        self._corrections.append(correction)
        scope = f" for {version_id}" if version_id is not None else ""
        self._audit.append(f"CORRECTION {date} {reason}{scope} by {author}: {note}")

    def correction_overlay(self, version_id: str | None = None) -> list[CalendarCorrection]:
        """Return audited corrections without applying them to source history."""
        return [
            correction
            for correction in self._corrections
            if correction.version_id is None or correction.version_id == version_id
        ]

    def corrections(self, version_id: str | None = None) -> list[CalendarCorrection]:
        """Compatibility alias for the audited correction overlay."""
        return self.correction_overlay(version_id)

    def audit_log(self) -> list[str]:
        return list(self._audit)
