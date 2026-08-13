"""Fund NAV collection job tests.

Covers negative NAV/iNAV rejection, stale NAV alerts, source conflicts,
deduplication and the availability time boundary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from ashare_contracts.providers import Capability, Cursor, Page
from data_worker.jobs.precious_metals_funds.collector import NavCollector, NavProvider
from market_core.funds.validation import FundNav


def _nav(
    unified_code: str = "SH.518880",
    nav_date: str = "2026-08-10",
    nav: float = 1.5,
    inav: float | None = 1.5,
    available_at: str = "2026-08-10T09:00:00Z",
    source: str = "provider-x",
) -> FundNav:
    return FundNav(
        unified_code=unified_code,
        date=nav_date,
        nav=nav,
        inav=inav,
        available_at=available_at,
        source=source,
    )


class FakeNavProvider(NavProvider):
    def __init__(self, navs: list[FundNav]) -> None:
        self._navs = navs

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def fetch_navs(self, exchange: str, cursor: Cursor | None = None) -> Page[FundNav]:
        return Page(items=list(self._navs), next_cursor=None)


def _collector(navs: list[FundNav]) -> NavCollector:
    today = date(2026, 8, 13)
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    return NavCollector(FakeNavProvider(navs), today=today, now=now)


def test_negative_nav_is_rejected() -> None:
    result = _collector([_nav(nav=-1.0)]).collect("SH")
    assert result.accepted == []
    assert len(result.rejected) == 1
    assert any(a.kind == "NEGATIVE_VALUE" for a in result.alerts)


def test_stale_nav_raises_alert() -> None:
    result = _collector([_nav(nav_date="2026-07-01")]).collect("SH")
    assert any(a.kind == "STALE_NAV" for a in result.alerts)


def test_not_yet_available_nav_is_rejected() -> None:
    result = _collector([_nav(available_at="2026-08-14T09:00:00Z")]).collect("SH")
    assert result.accepted == []
    assert any(a.kind == "NOT_YET_AVAILABLE" for a in result.alerts)


def test_source_conflict_raises_alert() -> None:
    a = _nav(nav=1.5, source="provider-x")
    b = _nav(nav=1.6, source="provider-y")
    result = _collector([a, b]).collect("SH")
    assert any(a.kind == "SOURCE_CONFLICT" for a in result.alerts)


def test_duplicate_records_are_deduplicated() -> None:
    duplicate = _nav(nav=1.5)
    result = _collector([duplicate, duplicate]).collect("SH")
    assert len(result.accepted) == 1


def test_missing_capability_fails_fast() -> None:
    class NoNavProvider(NavProvider):
        def capabilities(self) -> frozenset[Capability]:
            return frozenset()

        def fetch_navs(self, exchange: str, cursor: Cursor | None = None) -> Page[FundNav]:
            return Page(items=[], next_cursor=None)

    collector = NavCollector(NoNavProvider())
    with pytest.raises(NotImplementedError):
        collector.collect("SH")
