"""Calendar collection job.

Collects an exchange's holiday / temporary-closure records from a provider,
stores them as a versioned source, and raises alerts for conflicting sources
(same date, different reason) and temporary closures. The provider returns
sparse closure records rather than a complete daily calendar, so this job does
not infer missing dates. Manual corrections are audited and never overwrite
source data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ashare_contracts.calendar_holiday import Exchange as HolidayExchange
from ashare_contracts.calendar_holiday import Holiday
from data_worker.jobs.calendars.repository import CalendarRepository
from market_core.providers import CalendarProvider, ProviderDataError

# Retained for internal compatibility with older alert consumers. Sparse
# Holiday[] input never produces this legacy alert.
AlertKind = Literal["MISSING_DATE", "SOURCE_CONFLICT", "TEMPORARY_CLOSURE"]


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
    coverage_status: Literal["UNKNOWN"] = "UNKNOWN"


def _validate_request(exchange: str, year: int) -> tuple[str, int]:
    if type(exchange) is not str:
        raise ProviderDataError("calendar exchange is invalid")
    try:
        canonical_exchange = HolidayExchange(exchange)
    except ValueError:
        raise ProviderDataError("calendar exchange is invalid") from None

    if type(year) is not int or not 1 <= year <= 9999:
        raise ProviderDataError("calendar year is invalid")
    return canonical_exchange.value, year


def detect_alerts(
    holidays: list[Holiday],
    year: int,
    other_sources: list[Holiday] | None = None,
) -> list[CalendarAlert]:
    """Detect explicit source conflicts and temporary closures.

    ``holidays`` is a sparse list of closure records, not a daily calendar;
    neither gaps nor an empty list are evidence of missing dates.
    """
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

    del year

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
        self,
        provider: CalendarProvider,
        repository: CalendarRepository,
        source: str,
        *,
        max_pages: int = 100,
    ) -> None:
        if type(max_pages) is not int or max_pages <= 0:
            raise ProviderDataError("calendar max_pages must be a positive integer")
        self._provider = provider
        self._repository = repository
        self._source = source
        self._max_pages = max_pages

    def collect(self, exchange: str, year: int) -> CalendarCollectResult:
        canonical_exchange, valid_year = _validate_request(exchange, year)
        holidays = self._fetch_all(canonical_exchange, valid_year)
        version_id = self._repository.save_version(self._source, valid_year, holidays)
        alerts = detect_alerts(holidays, valid_year)
        return CalendarCollectResult(
            version_id=version_id, alerts=alerts, holiday_count=len(holidays)
        )

    def _fetch_all(self, exchange: str, year: int) -> list[Holiday]:
        holidays: list[Holiday] = []
        cursor: str | None = None
        consumed_cursors: set[str] = set()
        pages_fetched = 0
        while True:
            if pages_fetched >= self._max_pages:
                raise ProviderDataError("calendar pagination exceeded max_pages")
            page = self._provider.fetch_holidays(exchange, year, cursor)
            pages_fetched += 1
            if any(
                holiday.exchange.value != exchange or holiday.date.year != year
                for holiday in page.items
            ):
                raise ProviderDataError("calendar holiday does not match request")
            holidays.extend(page.items)
            next_cursor = page.next_cursor
            if next_cursor is None:
                return holidays
            if next_cursor == cursor or next_cursor in consumed_cursors:
                raise ProviderDataError("calendar pagination cursor repeated")
            if cursor is not None:
                consumed_cursors.add(cursor)
            cursor = next_cursor
