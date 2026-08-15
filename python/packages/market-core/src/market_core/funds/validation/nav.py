"""Point-in-time fund NAV validation.

NAV (net asset value) and iNAV (indicative NAV) are reference values, never
tradeable prices. Values are stored as :class:`~decimal.Decimal`, and each
observation carries the event, publication, ingest, availability and
processing timestamps plus an immutable raw evidence/object identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

NavIssueKind = Literal[
    "NEGATIVE_NAV",
    "NEGATIVE_INAV",
    "STALE_NAV",
    "NOT_YET_AVAILABLE",
    "NAIVE_TIMESTAMP",
    "INVALID_TIMESTAMP_ORDER",
    "MISSING_EVIDENCE",
    "MISSING_PROVENANCE",
]


@dataclass(frozen=True)
class FundNav:
    """One NAV/iNAV observation for a precious-metal fund."""

    unified_code: str
    date: str
    nav: Decimal
    inav: Decimal | None
    event_time: datetime
    publish_time: datetime
    ingest_time: datetime
    available_time: datetime
    processing_time: datetime
    raw_object_id: str
    source: str

    def __post_init__(self) -> None:
        """Normalize external numeric inputs at the domain boundary."""
        object.__setattr__(self, "nav", _decimal_from_external(self.nav))
        if self.inav is not None:
            object.__setattr__(self, "inav", _decimal_from_external(self.inav))

    @property
    def available_at(self) -> str:
        """Legacy display representation; comparisons use ``available_time``."""
        return self.available_time.isoformat()

    @property
    def raw_evidence_id(self) -> str:
        """Alias used by consumers that call the immutable object evidence id."""
        return self.raw_object_id


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
    """Validate a NAV observation against a reference date and current instant."""
    issues: list[NavIssue] = []

    if nav.nav < 0:
        issues.append(_issue(nav, "NEGATIVE_NAV", "nav must be >= 0"))
    if nav.inav is not None and nav.inav < 0:
        issues.append(_issue(nav, "NEGATIVE_INAV", "inav must be >= 0"))
    if not nav.raw_object_id.strip():
        issues.append(_issue(nav, "MISSING_EVIDENCE", "raw_object_id must be non-empty"))
    if not nav.source.strip():
        issues.append(_issue(nav, "MISSING_PROVENANCE", "source must be non-empty"))

    try:
        nav_date = date.fromisoformat(nav.date)
    except ValueError:
        nav_date = None
    if nav_date is not None and (today - nav_date).days > 7:
        issues.append(_issue(nav, "STALE_NAV", "nav is older than 7 days"))

    timestamps = (
        ("event_time", nav.event_time),
        ("publish_time", nav.publish_time),
        ("ingest_time", nav.ingest_time),
        ("available_time", nav.available_time),
        ("processing_time", nav.processing_time),
    )
    naive = [
        name for name, value in timestamps if value.tzinfo is None or value.utcoffset() is None
    ]
    if naive:
        issues.append(_issue(nav, "NAIVE_TIMESTAMP", f"timezone required for {', '.join(naive)}"))

    if now.tzinfo is None or now.utcoffset() is None:
        issues.append(_issue(nav, "NAIVE_TIMESTAMP", "timezone required for now"))
    elif not naive and nav.available_time > now:
        issues.append(
            _issue(
                nav,
                "NOT_YET_AVAILABLE",
                f"available at {nav.available_time.isoformat()}",
            )
        )

    if not naive and not _is_monotonic(
        (nav.event_time, nav.publish_time, nav.ingest_time, nav.available_time, nav.processing_time)
    ):
        issues.append(
            _issue(
                nav,
                "INVALID_TIMESTAMP_ORDER",
                "event/publish/ingest/available/processing order invalid",
            )
        )

    return NavValidation(valid=not issues, issues=issues)


def premium_rate(nav: FundNav, market_price: Decimal | int | float | str) -> Decimal:
    """Return exact premium/discount rate of a market price versus NAV.

    NAV/iNAV remain reference values; this calculation does not make either
    value executable. A non-positive NAV is rejected rather than fabricated as
    a zero premium.
    """
    if nav.nav <= 0:
        raise ValueError("nav must be > 0")
    price = _decimal_from_external(market_price)
    return (price - nav.nav) / nav.nav


def fund_nav_from_dict(raw: dict[str, object]) -> FundNav:
    """Build a :class:`FundNav` from a camelCase JSON mapping."""
    raw_object_id = raw.get("rawObjectId", raw.get("rawEvidenceId"))
    if raw_object_id is None:
        raise KeyError("rawObjectId")
    return FundNav(
        unified_code=str(raw["unifiedCode"]),
        date=str(raw["date"]),
        nav=_decimal_from_external(raw["nav"]),
        inav=(None if raw.get("inav") is None else _decimal_from_external(raw["inav"])),
        event_time=_parse_datetime(raw["eventTime"]),
        publish_time=_parse_datetime(raw["publishTime"]),
        ingest_time=_parse_datetime(raw["ingestTime"]),
        available_time=_parse_datetime(raw["availableTime"]),
        processing_time=_parse_datetime(raw["processingTime"]),
        raw_object_id=str(raw_object_id),
        source=str(raw["source"]),
    )


def _issue(nav: FundNav, kind: NavIssueKind, detail: str) -> NavIssue:
    return NavIssue(kind=kind, unified_code=nav.unified_code, date=nav.date, detail=detail)


def _is_monotonic(values: tuple[datetime, ...]) -> bool:
    return all(left <= right for left, right in zip(values, values[1:], strict=False))


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be an ISO 8601 string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _decimal_from_external(value: object) -> Decimal:
    """Convert an external numeric value without ``Decimal(float)``."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a decimal value")
    if isinstance(value, float):
        raise TypeError("float is not an accepted decimal boundary value")
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
