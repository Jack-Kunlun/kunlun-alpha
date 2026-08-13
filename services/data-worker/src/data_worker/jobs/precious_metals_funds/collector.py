"""Precious-metal fund NAV collection job.

Collects NAV/iNAV observations from a provider (capability-gated), normalizes
and deduplicates them, validates each observation, and raises alerts for
source conflicts and stale NAV. NAV/iNAV are reference values — never marked
tradeable — and missing fields are never silently inferred.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from ashare_contracts.providers import Capability, Cursor, Page
from market_core.funds.validation import FundNav, NavIssue, validate_nav
from market_core.providers import Provider

AlertKind = Literal["SOURCE_CONFLICT", "STALE_NAV", "NOT_YET_AVAILABLE", "NEGATIVE_VALUE"]


class NavProvider(Provider):
    """Fetches fund NAV/iNAV observations."""

    @abstractmethod
    def fetch_navs(self, exchange: str, cursor: Cursor | None = None) -> Page[FundNav]: ...


@dataclass(frozen=True)
class NavAlert:
    """One NAV collection alert."""

    kind: AlertKind
    unified_code: str
    date: str
    detail: str


@dataclass(frozen=True)
class NavCollectResult:
    """Result of a NAV collection run."""

    accepted: list[FundNav]
    rejected: list[tuple[FundNav, list[NavIssue]]]
    alerts: list[NavAlert]


class NavCollector:
    """Collects, deduplicates and validates fund NAV observations."""

    def __init__(
        self, provider: NavProvider, today: date | None = None, now: datetime | None = None
    ) -> None:
        self._provider = provider
        self._today = today or date.today()
        self._now = now or datetime.now().astimezone()

    def collect(self, exchange: str) -> NavCollectResult:
        self._provider.require(Capability.FETCH_FUND_NAV)
        navs = self._fetch_all(exchange)

        # Deduplicate by (unified_code, date), keeping the latest source.
        deduped: dict[tuple[str, str], FundNav] = {}
        for nav in navs:
            deduped[(nav.unified_code, nav.date)] = nav

        accepted: list[FundNav] = []
        rejected: list[tuple[FundNav, list[NavIssue]]] = []
        alerts: list[NavAlert] = []

        for nav in deduped.values():
            validation = validate_nav(nav, today=self._today, now=self._now)
            if validation.valid:
                accepted.append(nav)
            else:
                rejected.append((nav, validation.issues))
                for issue in validation.issues:
                    alerts.append(
                        NavAlert(
                            kind=_alert_kind(issue.kind),
                            unified_code=nav.unified_code,
                            date=nav.date,
                            detail=issue.detail,
                        )
                    )

        alerts.extend(self._detect_source_conflicts(navs))
        return NavCollectResult(accepted=accepted, rejected=rejected, alerts=alerts)

    def _fetch_all(self, exchange: str) -> list[FundNav]:
        navs: list[FundNav] = []
        cursor: str | None = None
        while True:
            page = self._provider.fetch_navs(exchange, cursor)
            navs.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return navs

    def _detect_source_conflicts(self, navs: list[FundNav]) -> list[NavAlert]:
        by_key: dict[tuple[str, str], list[FundNav]] = {}
        for nav in navs:
            by_key.setdefault((nav.unified_code, nav.date), []).append(nav)

        alerts: list[NavAlert] = []
        for (unified_code, nav_date), entries in by_key.items():
            values = {e.nav for e in entries}
            if len(values) > 1:
                alerts.append(
                    NavAlert(
                        kind="SOURCE_CONFLICT",
                        unified_code=unified_code,
                        date=nav_date,
                        detail=f"{len(values)} conflicting NAV values",
                    )
                )
        return alerts


def _alert_kind(issue_kind: str) -> AlertKind:
    mapping: dict[str, AlertKind] = {
        "NEGATIVE_NAV": "NEGATIVE_VALUE",
        "NEGATIVE_INAV": "NEGATIVE_VALUE",
        "STALE_NAV": "STALE_NAV",
        "NOT_YET_AVAILABLE": "NOT_YET_AVAILABLE",
    }
    return mapping.get(issue_kind, "NEGATIVE_VALUE")
