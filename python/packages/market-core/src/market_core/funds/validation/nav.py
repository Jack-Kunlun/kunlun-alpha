"""Fund NAV validation.

NAV (net asset value) and iNAV (indicative NAV) are reference values, never
tradeable prices. Validation rejects negative values, flags stale NAV/iNAV,
and enforces the availability window — a NAV is only usable after its
``available_at`` instant. Missing fields are never silently inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, cast

NavIssueKind = Literal["NEGATIVE_NAV", "NEGATIVE_INAV", "STALE_NAV", "NOT_YET_AVAILABLE"]


@dataclass(frozen=True)
class FundNav:
    """One NAV/iNAV observation for a precious-metal fund."""

    unified_code: str
    date: str
    nav: float
    inav: float | None
    available_at: str
    source: str


@dataclass(frozen=True)
class NavIssue:
    """One NAV quality issue."""

    kind: NavIssueKind
    unified_code: str
    date: str
    detail: str


@dataclass(frozen=True)
class NavValidation:
    """Result of validating a NAV observation."""

    valid: bool
    issues: list[NavIssue]


def validate_nav(nav: FundNav, *, today: date, now: datetime) -> NavValidation:
    """Validate a NAV observation against a reference date and instant."""
    issues: list[NavIssue] = []

    if nav.nav < 0:
        issues.append(
            NavIssue(
                kind="NEGATIVE_NAV",
                unified_code=nav.unified_code,
                date=nav.date,
                detail="nav must be >= 0",
            )
        )
    if nav.inav is not None and nav.inav < 0:
        issues.append(
            NavIssue(
                kind="NEGATIVE_INAV",
                unified_code=nav.unified_code,
                date=nav.date,
                detail="inav must be >= 0",
            )
        )

    nav_date = date.fromisoformat(nav.date)
    if (today - nav_date).days > 7:
        issues.append(
            NavIssue(
                kind="STALE_NAV",
                unified_code=nav.unified_code,
                date=nav.date,
                detail="nav is older than 7 days",
            )
        )

    available_at = datetime.fromisoformat(nav.available_at.replace("Z", "+00:00"))
    if available_at > now:
        issues.append(
            NavIssue(
                kind="NOT_YET_AVAILABLE",
                unified_code=nav.unified_code,
                date=nav.date,
                detail=f"available at {available_at.isoformat()}",
            )
        )

    return NavValidation(valid=not issues, issues=issues)


def premium_rate(nav: FundNav, market_price: float) -> float:
    """Premium/discount rate of a market price vs NAV, in [-1, 1]."""
    if nav.nav <= 0:
        return 0.0
    return (market_price - nav.nav) / nav.nav


def fund_nav_from_dict(raw: dict[str, object]) -> FundNav:
    """Build a FundNav from a camelCase JSON dict (fixtures format)."""
    return FundNav(
        unified_code=str(raw["unifiedCode"]),
        date=str(raw["date"]),
        nav=cast(float, raw["nav"]),
        inav=cast("float | None", raw.get("inav")),
        available_at=str(raw["availableAt"]),
        source=str(raw["source"]),
    )
