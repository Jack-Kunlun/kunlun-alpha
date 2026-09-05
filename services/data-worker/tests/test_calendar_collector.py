"""Calendar collection job tests.

Covers sparse-provider semantics, bounded pagination, versioning, source
provenance and the audit-only nature of manual corrections.
"""

from __future__ import annotations

from typing import cast

import pytest
from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.calendars.collector import CalendarCollector, detect_alerts
from data_worker.jobs.calendars.repository import InMemoryCalendarRepository
from market_core.providers import ProviderDataError
from market_core.providers.interfaces import CalendarProvider


def _holiday(date: str, reason: str = "PUBLIC_HOLIDAY", note: str | None = None) -> Holiday:
    return Holiday.model_validate({"date": date, "exchange": "SH", "reason": reason, "note": note})


def _page(items: list[Holiday], next_cursor: Cursor | None = None) -> Page[Holiday]:
    return Page[Holiday](items=items, next_cursor=next_cursor)


class FakeCalendarProvider(CalendarProvider):
    def __init__(self, holidays: list[Holiday]) -> None:
        self._holidays = holidays

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_CALENDAR})

    def fetch_holidays(
        self, exchange: str, year: int, cursor: Cursor | None = None
    ) -> Page[Holiday]:
        return _page(list(self._holidays))


class PagedCalendarProvider(CalendarProvider):
    def __init__(
        self,
        pages: dict[Cursor | None, Page[Holiday]],
        errors: dict[Cursor, ProviderDataError] | None = None,
    ) -> None:
        self._pages = pages
        self._errors = errors or {}
        self.calls: list[Cursor | None] = []

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_CALENDAR})

    def fetch_holidays(
        self, exchange: str, year: int, cursor: Cursor | None = None
    ) -> Page[Holiday]:
        del exchange, year
        self.calls.append(cursor)
        if cursor is not None and cursor in self._errors:
            raise self._errors[cursor]
        return self._pages[cursor]


def test_temporary_closure_raises_alert() -> None:
    holidays = [_holiday("2026-08-07", "TEMPORARY_CLOSURE", "台风临时休市")]
    alerts = detect_alerts(holidays, 2026)

    assert any(a.kind == "TEMPORARY_CLOSURE" and a.date == "2026-08-07" for a in alerts)


def test_sparse_holiday_records_do_not_infer_missing_dates() -> None:
    # Holiday[] contains closures, not one record for every calendar date.
    holidays = [_holiday("2026-01-01"), _holiday("2026-02-17")]
    alerts = detect_alerts(holidays, 2026)

    assert not any(a.kind == "MISSING_DATE" for a in alerts)


def test_empty_holiday_records_do_not_infer_missing_dates() -> None:
    assert not any(a.kind == "MISSING_DATE" for a in detect_alerts([], 2026))


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
    assert result.coverage_status == "UNKNOWN"
    assert len(repo.source_holidays("exchange-a")) == 1
    assert repo.source_holidays("other-source") == []


def test_multi_page_collection_saves_all_pages_once() -> None:
    first = _holiday("2026-01-01")
    second = _holiday("2026-02-17")
    provider = PagedCalendarProvider(
        {
            None: _page([first], "page-2"),
            "page-2": _page([second]),
        }
    )
    repo = InMemoryCalendarRepository()

    result = CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    assert provider.calls == [None, "page-2"]
    assert [item.date.isoformat() for item in repo.source_holidays("exchange-a")] == [
        "2026-01-01",
        "2026-02-17",
    ]
    assert result.holiday_count == 2
    assert sum(line.startswith("SAVE ") for line in repo.audit_log()) == 1


def test_exact_page_limit_allows_final_page_without_an_extra_request() -> None:
    provider = PagedCalendarProvider(
        {
            None: _page([_holiday("2026-01-01")], "page-2"),
            "page-2": _page([_holiday("2026-02-17")]),
        }
    )

    CalendarCollector(provider, InMemoryCalendarRepository(), "exchange-a", max_pages=2).collect(
        "SH", 2026
    )

    assert provider.calls == [None, "page-2"]


def test_invalid_max_pages_is_rejected_before_fetch() -> None:
    for invalid in (0, -1, 1.5, True):
        provider = PagedCalendarProvider({None: _page([])})
        with pytest.raises(
            ProviderDataError, match="calendar max_pages must be a positive integer"
        ):
            CalendarCollector(
                provider,
                InMemoryCalendarRepository(),
                "exchange-a",
                max_pages=cast(int, invalid),
            )
        assert provider.calls == []


def test_page_limit_failure_does_not_request_page_max_plus_one_or_save() -> None:
    provider = PagedCalendarProvider(
        {
            None: _page([_holiday("2026-01-01")], "page-2"),
            "page-2": _page([_holiday("2026-02-17")], "page-3"),
            "page-3": _page([_holiday("2026-05-01")]),
        }
    )
    repo = InMemoryCalendarRepository()
    CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-01")]), repo, source="exchange-a"
    ).collect("SH", 2026)
    before_holidays = repo.source_holidays("exchange-a")
    before_audit = repo.audit_log()

    with pytest.raises(ProviderDataError, match="calendar pagination exceeded max_pages"):
        CalendarCollector(provider, repo, "exchange-a", max_pages=2).collect("SH", 2026)

    assert provider.calls == [None, "page-2"]
    assert repo.source_holidays("exchange-a") == before_holidays
    assert repo.audit_log() == before_audit


@pytest.mark.parametrize(
    ("pages", "calls"),
    [
        (
            {
                None: _page([], "secret-self-loop"),
                "secret-self-loop": _page([], "secret-self-loop"),
            },
            [None, "secret-self-loop"],
        ),
        (
            {
                None: _page([], "cursor-a"),
                "cursor-a": _page([], "cursor-b"),
                "cursor-b": _page([], "cursor-a"),
            },
            [None, "cursor-a", "cursor-b"],
        ),
    ],
)
def test_repeated_or_cyclic_cursors_fail_without_echoing_cursor(
    pages: dict[Cursor | None, Page[Holiday]], calls: list[Cursor | None]
) -> None:
    provider = PagedCalendarProvider(pages)

    with pytest.raises(ProviderDataError, match="calendar pagination cursor repeated") as error:
        CalendarCollector(provider, InMemoryCalendarRepository(), "exchange-a").collect("SH", 2026)

    assert provider.calls == calls
    assert str(error.value) == "calendar pagination cursor repeated"


def test_infinite_unique_cursors_are_bounded() -> None:
    pages = {
        None: _page([], "cursor-1"),
        "cursor-1": _page([], "cursor-2"),
        "cursor-2": _page([], "cursor-3"),
    }
    provider = PagedCalendarProvider(pages)

    with pytest.raises(ProviderDataError, match="calendar pagination exceeded max_pages"):
        CalendarCollector(
            provider, InMemoryCalendarRepository(), "exchange-a", max_pages=3
        ).collect("SH", 2026)

    assert provider.calls == [None, "cursor-1", "cursor-2"]


def test_provider_error_after_page_one_preserves_previous_version() -> None:
    repo = InMemoryCalendarRepository()
    CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-01")]), repo, source="exchange-a"
    ).collect("SH", 2026)
    before_holidays = repo.source_holidays("exchange-a")
    before_audit = repo.audit_log()
    provider = PagedCalendarProvider(
        {None: _page([_holiday("2026-02-17")], "page-2")},
        errors={"page-2": ProviderDataError("provider data invalid")},
    )

    with pytest.raises(ProviderDataError, match="provider data invalid"):
        CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    assert provider.calls == [None, "page-2"]
    assert repo.source_holidays("exchange-a") == before_holidays
    assert repo.audit_log() == before_audit


def test_manual_correction_is_audited_without_overwriting_source() -> None:
    provider = FakeCalendarProvider([_holiday("2026-01-01")])
    repo = InMemoryCalendarRepository()
    CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    repo.apply_correction("2026-01-02", "TEMPORARY_CLOSURE", "手工修正", "ops")

    # Source data unchanged; correction recorded in the audit log.
    assert len(repo.source_holidays("exchange-a")) == 1
    assert any("CORRECTION 2026-01-02" in line for line in repo.audit_log())


def test_multiple_calendar_versions_are_independently_retrievable() -> None:
    repo = InMemoryCalendarRepository()
    first = CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-01")]), repo, source="exchange-a"
    ).collect("SH", 2026)
    second = CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-02")]), repo, source="exchange-a"
    ).collect("SH", 2026)

    assert first.version_id != second.version_id
    assert [item.date.isoformat() for item in repo.get_version(first.version_id)] == ["2026-01-01"]
    assert [item.date.isoformat() for item in repo.get_version(second.version_id)] == ["2026-01-02"]


def test_calendar_correction_is_an_audited_overlay() -> None:
    repo = InMemoryCalendarRepository()
    result = CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-01")]), repo, source="exchange-a"
    ).collect("SH", 2026)

    repo.apply_correction(
        "2026-01-02",
        "TEMPORARY_CLOSURE",
        "manual review",
        "ops",
        version_id=result.version_id,
    )

    assert [item.date.isoformat() for item in repo.get_version(result.version_id)] == ["2026-01-01"]
    assert [item.date for item in repo.correction_overlay(result.version_id)] == ["2026-01-02"]
