"""Calendar collection job tests.

Covers missing-date, source-conflict and temporary-closure alerts, versioning,
source provenance and the audit-only nature of manual corrections.
"""

from __future__ import annotations

from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.calendars.collector import CalendarCollector, detect_alerts
from data_worker.jobs.calendars.repository import InMemoryCalendarRepository
from market_core.providers.interfaces import CalendarProvider


def _holiday(date: str, reason: str = "PUBLIC_HOLIDAY", note: str | None = None) -> Holiday:
    return Holiday.model_validate({"date": date, "exchange": "SH", "reason": reason, "note": note})


class FakeCalendarProvider(CalendarProvider):
    def __init__(self, holidays: list[Holiday]) -> None:
        self._holidays = holidays

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_CALENDAR})

    def fetch_holidays(
        self, exchange: str, year: int, cursor: Cursor | None = None
    ) -> Page[Holiday]:
        return Page(items=list(self._holidays), next_cursor=None)


def test_temporary_closure_raises_alert() -> None:
    holidays = [_holiday("2026-08-07", "TEMPORARY_CLOSURE", "台风临时休市")]
    alerts = detect_alerts(holidays, 2026)

    assert any(a.kind == "TEMPORARY_CLOSURE" and a.date == "2026-08-07" for a in alerts)


def test_missing_dates_raise_alert() -> None:
    # Only Q1 data present — a large gap from April to the year end.
    holidays = [_holiday("2026-01-01"), _holiday("2026-02-17")]
    alerts = detect_alerts(holidays, 2026)

    assert any(a.kind == "MISSING_DATE" for a in alerts)


def test_source_conflict_raises_alert() -> None:
    primary = [_holiday("2026-01-01", "PUBLIC_HOLIDAY")]
    other = [_holiday("2026-01-01", "TEMPORARY_CLOSURE")]
    alerts = detect_alerts(primary, 2026, other_sources=other)

    assert any(a.kind == "SOURCE_CONFLICT" and a.date == "2026-01-01" for a in alerts)


def test_collect_saves_version_with_provenance() -> None:
    provider = FakeCalendarProvider([_holiday("2026-01-01")])
    repo = InMemoryCalendarRepository()
    collector = CalendarCollector(provider, repo, source="exchange-a")

    result = collector.collect("SH", 2026)

    assert result.version_id.startswith("exchange-a:2026:")
    assert len(repo.source_holidays("exchange-a")) == 1
    assert repo.source_holidays("other-source") == []


def test_manual_correction_is_audited_without_overwriting_source() -> None:
    provider = FakeCalendarProvider([_holiday("2026-01-01")])
    repo = InMemoryCalendarRepository()
    CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    repo.apply_correction("2026-01-02", "TEMPORARY_CLOSURE", "手工修正", "ops")

    # Source data unchanged; correction recorded in the audit log.
    assert len(repo.source_holidays("exchange-a")) == 1
    assert any("CORRECTION 2026-01-02" in line for line in repo.audit_log())
