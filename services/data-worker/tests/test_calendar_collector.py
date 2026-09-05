"""Calendar collection job tests.

Covers sparse-provider semantics, bounded pagination, versioning, source
provenance and the audit-only nature of manual corrections.
"""

from __future__ import annotations

from typing import cast

import pytest
from ashare_contracts.calendar_holiday import Exchange as HolidayExchange
from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.calendars.collector import CalendarCollector, detect_alerts
from data_worker.jobs.calendars.repository import InMemoryCalendarRepository
from market_core.providers import ProviderDataError
from market_core.providers.interfaces import CalendarProvider


def _holiday(
    date: str,
    reason: str = "PUBLIC_HOLIDAY",
    note: str | None = None,
    exchange: str = "SH",
) -> Holiday:
    return Holiday.model_validate(
        {"date": date, "exchange": exchange, "reason": reason, "note": note}
    )


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
        self.request_calls: list[tuple[str, int, Cursor | None]] = []

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_CALENDAR})

    def fetch_holidays(
        self, exchange: str, year: int, cursor: Cursor | None = None
    ) -> Page[Holiday]:
        self.request_calls.append((exchange, year, cursor))
        self.calls.append(cursor)
        if cursor is not None and cursor in self._errors:
            raise self._errors[cursor]
        return self._pages[cursor]


@pytest.mark.parametrize(
    ("exchange", "year", "holiday_date"),
    [("SH", 2026, "2026-01-01"), ("SZ", 2026, "2026-12-31"), ("BJ", 2024, "2024-02-29")],
)
def test_supported_exchange_requests_are_canonical_and_accept_boundary_dates(
    exchange: str, year: int, holiday_date: str
) -> None:
    provider = PagedCalendarProvider({None: _page([_holiday(holiday_date, exchange=exchange)])})
    repo = InMemoryCalendarRepository()

    result = CalendarCollector(provider, repo, source="exchange-a").collect(exchange, year)

    assert provider.request_calls == [(HolidayExchange(exchange).value, year, None)]
    assert result.holiday_count == 1
    assert [item.date.isoformat() for item in repo.source_holidays("exchange-a")] == [holiday_date]


def test_valid_multi_page_response_is_saved_once_with_canonical_request() -> None:
    provider = PagedCalendarProvider(
        {
            None: _page([_holiday("2026-01-01")], "page-2"),
            "page-2": _page([_holiday("2026-12-31")]),
        }
    )
    repo = InMemoryCalendarRepository()

    CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    assert provider.request_calls == [("SH", 2026, None), ("SH", 2026, "page-2")]
    assert sum(line.startswith("SAVE ") for line in repo.audit_log()) == 1


@pytest.mark.parametrize(
    ("exchange", "year", "bad_holiday"),
    [
        ("SH", 2026, _holiday("2026-01-01", exchange="SZ", note="secret-note")),
        ("SH", 2026, _holiday("2025-12-31", note="secret-note")),
    ],
)
def test_first_page_identity_mismatch_fails_before_next_fetch_or_saving(
    exchange: str, year: int, bad_holiday: Holiday
) -> None:
    provider = PagedCalendarProvider(
        {None: _page([bad_holiday], "secret-cursor"), "secret-cursor": _page([])}
    )
    repo = InMemoryCalendarRepository()

    with pytest.raises(ProviderDataError, match="calendar holiday does not match request") as error:
        CalendarCollector(provider, repo, source="exchange-a").collect(exchange, year)

    assert str(error.value) == "calendar holiday does not match request"
    assert provider.calls == [None]
    assert repo.source_holidays("exchange-a") == []
    assert repo.audit_log() == []
    assert "secret-cursor" not in str(error.value)
    assert "secret-note" not in str(error.value)


@pytest.mark.parametrize(
    "bad_holiday",
    [
        _holiday("2025-03-02", note="secret-note"),
        _holiday("2026-03-02", exchange="SZ", note="secret-note"),
    ],
)
def test_subsequent_mixed_page_identity_mismatch_preserves_snapshot_audit_and_correction(
    bad_holiday: Holiday,
) -> None:
    repo = InMemoryCalendarRepository()
    initial = CalendarCollector(
        FakeCalendarProvider([_holiday("2026-01-01")]), repo, source="exchange-a"
    ).collect("SH", 2026)
    repo.apply_correction(
        "2026-01-02",
        "TEMPORARY_CLOSURE",
        "existing correction",
        "ops",
        version_id=initial.version_id,
    )
    before_holidays = repo.source_holidays("exchange-a")
    before_audit = repo.audit_log()
    before_corrections = repo.correction_overlay(initial.version_id)
    provider = PagedCalendarProvider(
        {
            None: _page([_holiday("2026-02-17")], "cursor-a"),
            "cursor-a": _page(
                [
                    _holiday("2026-03-01"),
                    bad_holiday,
                ],
                "secret-cursor",
            ),
            "secret-cursor": _page([_holiday("2026-04-01")]),
        }
    )

    with pytest.raises(ProviderDataError, match="calendar holiday does not match request") as error:
        CalendarCollector(provider, repo, source="exchange-a").collect("SH", 2026)

    assert str(error.value) == "calendar holiday does not match request"
    assert provider.calls == [None, "cursor-a"]
    assert repo.source_holidays("exchange-a") == before_holidays
    assert repo.get_version(initial.version_id) == before_holidays
    assert repo.audit_log() == before_audit
    assert repo.correction_overlay(initial.version_id) == before_corrections
    assert "secret-cursor" not in str(error.value)
    assert "secret-note" not in str(error.value)


@pytest.mark.parametrize("invalid_exchange", ["sh", "SSE", "", None, 123])
def test_invalid_exchange_is_rejected_before_fetch_or_save(invalid_exchange: object) -> None:
    provider = PagedCalendarProvider({None: _page([])})
    repo = InMemoryCalendarRepository()

    with pytest.raises(ProviderDataError, match="calendar exchange is invalid") as error:
        CalendarCollector(provider, repo, source="exchange-a").collect(
            cast(str, invalid_exchange), 2026
        )

    assert str(error.value) == "calendar exchange is invalid"
    assert provider.calls == []
    assert repo.audit_log() == []
    assert repr(invalid_exchange) not in str(error.value)


@pytest.mark.parametrize("invalid_year", [True, False, 0, 10000, 1.5, "2026", None])
def test_invalid_year_is_rejected_before_fetch_or_save(invalid_year: object) -> None:
    provider = PagedCalendarProvider({None: _page([])})
    repo = InMemoryCalendarRepository()

    with pytest.raises(ProviderDataError, match="calendar year is invalid") as error:
        CalendarCollector(provider, repo, source="exchange-a").collect(
            "SH", cast(int, invalid_year)
        )

    assert str(error.value) == "calendar year is invalid"
    assert provider.calls == []
    assert repo.audit_log() == []
    assert repr(invalid_year) not in str(error.value)


@pytest.mark.parametrize("year", [1, 9999])
def test_legal_empty_response_remains_unknown_coverage(year: int) -> None:
    provider = PagedCalendarProvider({None: _page([])})
    repo = InMemoryCalendarRepository()

    result = CalendarCollector(provider, repo, source="exchange-a").collect("BJ", year)

    assert result.coverage_status == "UNKNOWN"
    assert provider.request_calls == [("BJ", year, None)]
    assert sum(line.startswith("SAVE ") for line in repo.audit_log()) == 1


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
