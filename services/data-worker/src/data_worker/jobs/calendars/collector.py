"""Calendar collection job.

Collects an exchange's holiday / temporary-closure calendar from a provider,
stores it as a versioned source, and raises alerts for missing dates (large
gaps in coverage), conflicting sources (same date, different reason) and
temporary closures. Manual corrections are audited and never overwrite source
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from ashare_contracts.calendar_holiday import Holiday
from data_worker.jobs.calendars.repository import CalendarRepository
from market_core.providers import CalendarProvider

AlertKind = Literal["MISSING_DATE", "SOURCE_CONFLICT", "TEMPORARY_CLOSURE"]

# A gap larger than this many days between consecutive records is treated as
# missing coverage (a trading calendar should never be silent for a quarter).
_MAX_GAP_DAYS = 90


@dataclass(frozen=True)
class CalendarAlert:
    """One calendar quality alert."""

    kind: AlertKind
    date: str
    detail: str


@dataclass(frozen=True)
class CalendarCollectResult:
    """Result of a calendar collection run."""

    version_id: str
    alerts: list[CalendarAlert]
    holiday_count: int


def detect_alerts(
    holidays: list[Holiday],
    year: int,
    other_sources: list[Holiday] | None = None,
) -> list[CalendarAlert]:
    """Detect missing dates, source conflicts and temporary closures."""
    alerts: list[CalendarAlert] = []

    for holiday in holidays:
        if holiday.reason.value == "TEMPORARY_CLOSURE":
            alerts.append(
                CalendarAlert(
                    kind="TEMPORARY_CLOSURE",
                    date=holiday.date.isoformat(),
                    detail=holiday.note or "temporary closure",
                )
            )

    sorted_dates = sorted({h.date for h in holidays})
    if not sorted_dates:
        alerts.append(
            CalendarAlert(kind="MISSING_DATE", date=f"{year}-01-01", detail="no calendar data")
        )
    else:
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        boundaries = [start, *sorted_dates, end]
        for i in range(1, len(boundaries)):
            gap = (boundaries[i] - boundaries[i - 1]).days
            if gap > _MAX_GAP_DAYS:
                alerts.append(
                    CalendarAlert(
                        kind="MISSING_DATE",
                        date=boundaries[i - 1].isoformat(),
                        detail=f"{gap} days without a record",
                    )
                )

    if other_sources:
        primary = {h.date: h.reason for h in holidays}
        for other in other_sources:
            if other.date in primary and primary[other.date] != other.reason:
                alerts.append(
                    CalendarAlert(
                        kind="SOURCE_CONFLICT",
                        date=other.date.isoformat(),
                        detail=f"{primary[other.date].value} vs {other.reason.value}",
                    )
                )

    return alerts


class CalendarCollector:
    """Collects and versions an exchange's calendar."""

    def __init__(
        self, provider: CalendarProvider, repository: CalendarRepository, source: str
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._source = source

    def collect(self, exchange: str, year: int) -> CalendarCollectResult:
        holidays = self._fetch_all(exchange, year)
        version_id = self._repository.save_version(self._source, year, holidays)
        alerts = detect_alerts(holidays, year)
        return CalendarCollectResult(
            version_id=version_id, alerts=alerts, holiday_count=len(holidays)
        )

    def _fetch_all(self, exchange: str, year: int) -> list[Holiday]:
        holidays: list[Holiday] = []
        cursor: str | None = None
        while True:
            page = self._provider.fetch_holidays(exchange, year, cursor)
            holidays.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return holidays
