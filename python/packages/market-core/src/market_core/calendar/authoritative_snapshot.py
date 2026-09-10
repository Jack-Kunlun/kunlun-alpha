"""Pure, point-in-time rules for authoritative daily calendar snapshots.

This module intentionally contains no provider, persistence, or network code.  A
future trusted adapter may construct the typed inputs here after independently
checking the provider's identity and captured evidence.
"""

from __future__ import annotations

import calendar as _calendar
import hashlib
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from re import fullmatch
from typing import Final, Literal, NoReturn
from uuid import UUID
from zoneinfo import ZoneInfo

from ashare_contracts.calendar_trading_day import Exchange as ContractExchange
from ashare_contracts.calendar_trading_day import Reason as ContractReason
from ashare_contracts.calendar_trading_day import TradingDay as ContractTradingDay

from market_core.calendar.scan_run import (
    CalendarScanRunCoverage,
    CalendarScanRunManifestReceipt,
    CalendarScanRunPassReceipt,
    CalendarScanRunReceipt,
    ScanRunCoverage,
    ScanRunCoverageLevel,
    calendar_scan_run_catalog_digest,
    calendar_scan_run_manifest_member_digest,
    calendar_scan_run_pass_member_digest,
    calendar_scan_run_resource_id,
)

ExchangeCode = Literal["SH", "SZ", "BJ"]

_INVALID_SCOPE = "invalid calendar scope"
_INVALID_DAY = "invalid calendar day"
_INVALID_SNAPSHOT = "invalid calendar snapshot"
_INVALID_LINEAGE = "invalid calendar snapshot lineage"
_INVALID_SECONDARY = "invalid secondary calendar observation"
_INVALID_RESOLUTION = "invalid calendar resolution"
_SHA256_PATTERN = r"[0-9a-f]{64}"
_P1N07_2026_RULE_CHANGE = date(2026, 7, 6)
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


class AuthoritativeCalendarError(ValueError):
    """Raised when a typed calendar input violates the domain contract."""


class OfficialAuthority(StrEnum):
    """Closed set of official authority labels and their fixed exchanges."""

    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"

    @property
    def exchange(self) -> ExchangeCode:
        return _AUTHORITY_EXCHANGE[self]


class SnapshotTerminal(StrEnum):
    """Whether a snapshot is complete enough for a positive decision."""

    COMPLETE = "COMPLETE"
    INDETERMINATE = "INDETERMINATE"


class CalendarDayReason(StrEnum):
    """Closed reasons retained from the typed day contract."""

    WEEKEND = "WEEKEND"
    PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY"
    TEMPORARY_CLOSURE = "TEMPORARY_CLOSURE"
    SPECIAL = "SPECIAL"


class CalendarEvidenceKind(StrEnum):
    """Closed evidence classes accepted by an authoritative snapshot."""

    ANNUAL_NOTICE = "ANNUAL_NOTICE"
    RULE = "RULE"
    TEMPORARY_SCAN = "TEMPORARY_SCAN"
    TEMPORARY_CLOSURE_NOTICE = "TEMPORARY_CLOSURE_NOTICE"


class CalendarResolutionStatus(StrEnum):
    """Three-state result for one exchange/date/as-of query."""

    TRADING = "TRADING"
    NON_TRADING = "NON_TRADING"
    INDETERMINATE = "INDETERMINATE"


class CalendarResolutionReason(StrEnum):
    """Fixed, non-free-text reasons for a resolution result."""

    OFFICIAL_TRADING = "OFFICIAL_TRADING"
    OFFICIAL_NON_TRADING = "OFFICIAL_NON_TRADING"
    OFFICIAL_INCOMPLETE = "OFFICIAL_INCOMPLETE"
    NO_VISIBLE_OFFICIAL = "NO_VISIBLE_OFFICIAL"
    OFFICIAL_CONFLICT = "OFFICIAL_CONFLICT"
    OFFICIAL_LINEAGE_UNAVAILABLE = "OFFICIAL_LINEAGE_UNAVAILABLE"
    OFFICIAL_HORIZON_UNCONFIRMED = "OFFICIAL_HORIZON_UNCONFIRMED"


class CalendarCoverageLevel(StrEnum):
    """The verified horizon exposed by an official calendar composition."""

    FINAL_YEAR = "FINAL_YEAR"
    CONFIRMED_HORIZON = "CONFIRMED_HORIZON"
    INDETERMINATE = "INDETERMINATE"


CalendarCoverageStatus = CalendarCoverageLevel


_AUTHORITY_EXCHANGE: Final[dict[OfficialAuthority, ExchangeCode]] = {
    OfficialAuthority.SSE: "SH",
    OfficialAuthority.SZSE: "SZ",
    OfficialAuthority.BSE: "BJ",
}
_CONTRACT_EXCHANGE: Final[dict[ContractExchange, ExchangeCode]] = {
    ContractExchange.sh: "SH",
    ContractExchange.sz: "SZ",
    ContractExchange.bj: "BJ",
}
_CONTRACT_REASON: Final[dict[ContractReason, CalendarDayReason]] = {
    ContractReason.weekend: CalendarDayReason.WEEKEND,
    ContractReason.public_holiday: CalendarDayReason.PUBLIC_HOLIDAY,
    ContractReason.temporary_closure: CalendarDayReason.TEMPORARY_CLOSURE,
    ContractReason.special: CalendarDayReason.SPECIAL,
}


def _fail(message: str) -> NoReturn:
    """Raise only fixed domain messages; never echo untrusted input."""

    raise AuthoritativeCalendarError(message)


def _utc(value: object, message: str) -> datetime:
    if type(value) is not datetime:
        _fail(message)
    normalized: datetime | None = None
    failed = False
    try:
        if value.tzinfo is not None and value.utcoffset() is not None:
            normalized = value.astimezone(UTC)
    except Exception:
        failed = True
    if failed or normalized is None:
        _fail(message)
    return normalized


def _strict_date(value: object, message: str) -> date:
    if type(value) is not date:
        _fail(message)
    return value


def _strict_uuid(value: object, message: str) -> UUID:
    if type(value) is not UUID:
        _fail(message)
    return value


def _strict_sha256(value: object, message: str) -> str:
    if type(value) is not str or fullmatch(_SHA256_PATTERN, value) is None:
        _fail(message)
    return value


def _strict_cursor(value: object, message: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value or "\x00" in value:
        _fail(message)
    return value


def _strict_scope(value: object, message: str) -> CalendarScope:
    if type(value) is not CalendarScope:
        _fail(message)
    if type(value.exchange) is not str or value.exchange not in {"SH", "SZ", "BJ"}:
        _fail(message)
    if type(value.year) is not int or not 1 <= value.year <= 9999:
        _fail(message)
    return value


def _expected_dates(year: int) -> tuple[date, ...]:
    """Return every date in ``year`` without constructing year + 1."""

    count = 366 if _calendar.isleap(year) else 365
    first = date(year, 1, 1)
    return tuple(date.fromordinal(first.toordinal() + offset) for offset in range(count))


def expected_calendar_dates(year: int) -> tuple[date, ...]:
    """Return every natural date in a validated calendar year."""

    _validate_year(year)
    return _expected_dates(year)


def _validate_year(year: object) -> int:
    if type(year) is not int or not 1 <= year <= 9999:
        _fail(_INVALID_SCOPE)
    return year


@dataclass(frozen=True, slots=True)
class CalendarScope:
    """The only scope dimensions accepted by this contract."""

    exchange: ExchangeCode
    year: int

    def __post_init__(self) -> None:
        if type(self.exchange) is not str or self.exchange not in {"SH", "SZ", "BJ"}:
            _fail(_INVALID_SCOPE)
        if type(self.year) is not int or not 1 <= self.year <= 9999:
            _fail(_INVALID_SCOPE)


@dataclass(frozen=True, slots=True)
class CalendarCoverage:
    """Immutable, point-in-time coverage and source-policy declaration."""

    scope: CalendarScope
    level: CalendarCoverageLevel
    confirmed_through: date
    publication_cutoff: datetime
    source_policy_id: str
    source_catalog_sha256: str
    two_pass_verified: bool
    source_policy_verified: bool = True

    def __post_init__(self) -> None:
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if type(self.level) is not CalendarCoverageLevel:
            _fail(_INVALID_SNAPSHOT)
        confirmed_through = _strict_date(self.confirmed_through, _INVALID_SNAPSHOT)
        if confirmed_through.year != scope.year:
            _fail(_INVALID_SCOPE)
        publication_cutoff = _utc(self.publication_cutoff, _INVALID_SNAPSHOT)
        if type(self.source_policy_id) is not str or not self.source_policy_id:
            _fail(_INVALID_SNAPSHOT)
        if "\x00" in self.source_policy_id:
            _fail(_INVALID_SNAPSHOT)
        _strict_sha256(self.source_catalog_sha256, _INVALID_SNAPSHOT)
        if type(self.two_pass_verified) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if type(self.source_policy_verified) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if self.level is CalendarCoverageLevel.FINAL_YEAR and confirmed_through != date(
            scope.year, 12, 31
        ):
            _fail(_INVALID_SNAPSHOT)
        if (
            self.level is CalendarCoverageLevel.CONFIRMED_HORIZON
            and confirmed_through > publication_cutoff.astimezone(_SHANGHAI_TZ).date()
        ):
            _fail(_INVALID_SNAPSHOT)
        object.__setattr__(self, "publication_cutoff", publication_cutoff)

    @property
    def final_year_watermark(self) -> datetime:
        """The earliest legal publication boundary for a final-year result."""

        return datetime(self.scope.year, 12, 31, 23, 59, 59, tzinfo=UTC)

    @property
    def is_verified(self) -> bool:
        """Whether source policy and two-pass evidence are both trusted."""

        return self.source_policy_verified and self.two_pass_verified

    @property
    def final_year_eligible(self) -> bool:
        """Whether this declaration is strong enough to produce COMPLETE."""

        return (
            self.level is CalendarCoverageLevel.FINAL_YEAR
            and self.confirmed_through == date(self.scope.year, 12, 31)
            and self.publication_cutoff >= self.final_year_watermark
            and self.is_verified
        )

    @property
    def source_catalog_digest(self) -> str:
        """Compatibility spelling for the catalog digest field."""

        return self.source_catalog_sha256

    @property
    def coverage_level(self) -> CalendarCoverageLevel:
        """Return the declared coverage level."""

        return self.level


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """Immutable internal copy of one typed daily calendar row.

    Provider notes and other free text are deliberately not represented.
    """

    date: date
    exchange: ExchangeCode
    is_trading_day: bool
    reason: CalendarDayReason | None = None

    def __post_init__(self) -> None:
        _strict_date(self.date, _INVALID_DAY)
        if type(self.exchange) is not str or self.exchange not in {"SH", "SZ", "BJ"}:
            _fail(_INVALID_DAY)
        if type(self.is_trading_day) is not bool:
            _fail(_INVALID_DAY)
        if self.reason is not None and type(self.reason) is not CalendarDayReason:
            _fail(_INVALID_DAY)
        if self.is_trading_day and self.reason is not None:
            _fail(_INVALID_DAY)


@dataclass(frozen=True, slots=True)
class CalendarEvidence:
    """Redacted, immutable reference to one verified official artifact."""

    evidence_id: UUID
    artifact_sha256: str
    kind: CalendarEvidenceKind
    authority: OfficialAuthority
    scope: CalendarScope
    captured_at: datetime
    available_at: datetime
    source_url: str = ""
    document_id: str = ""
    title: str = ""
    issuer: str = ""
    identity_verified: bool = False
    covers_full_exchange: bool = False
    covers_full_day: bool = False
    artifact_id: UUID | None = None
    capture_id: UUID | None = None

    def __post_init__(self) -> None:
        _strict_uuid(self.evidence_id, _INVALID_SNAPSHOT)
        _strict_sha256(self.artifact_sha256, _INVALID_SNAPSHOT)
        if type(self.kind) is not CalendarEvidenceKind:
            _fail(_INVALID_SNAPSHOT)
        if type(self.authority) is not OfficialAuthority:
            _fail(_INVALID_SNAPSHOT)
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if self.authority.exchange != scope.exchange:
            _fail(_INVALID_SCOPE)
        captured_at = _utc(self.captured_at, _INVALID_SNAPSHOT)
        available_at = _utc(self.available_at, _INVALID_SNAPSHOT)
        if captured_at > available_at:
            _fail(_INVALID_SNAPSHOT)
        for identity in (self.source_url, self.document_id, self.title, self.issuer):
            if type(identity) is not str or ("\x00" in identity):
                _fail(_INVALID_SNAPSHOT)
        if type(self.identity_verified) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if type(self.covers_full_exchange) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if type(self.covers_full_day) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if self.artifact_id is not None:
            _strict_uuid(self.artifact_id, _INVALID_SNAPSHOT)
        if self.capture_id is not None:
            _strict_uuid(self.capture_id, _INVALID_SNAPSHOT)
        if self.identity_verified and (
            not self.source_url.startswith("https://")
            or not self.document_id
            or not self.title
            or not self.issuer
            or self.artifact_id is None
            or self.capture_id is None
        ):
            _fail(_INVALID_SNAPSHOT)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "available_at", available_at)


@dataclass(frozen=True, slots=True)
class CalendarScanPage:
    """One ordered page and its immutable official evidence receipt."""

    ordinal: int
    evidence: CalendarEvidence
    cursor_in: str | None
    cursor_out: str | None

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal <= 0:
            _fail(_INVALID_SNAPSHOT)
        if type(self.evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.evidence.kind is not CalendarEvidenceKind.TEMPORARY_SCAN:
            _fail(_INVALID_SNAPSHOT)
        _strict_cursor(self.cursor_in, _INVALID_SNAPSHOT)
        _strict_cursor(self.cursor_out, _INVALID_SNAPSHOT)


@dataclass(frozen=True, slots=True)
class CalendarScanBundle:
    """Auditable ordered pages with derived pagination completeness."""

    bundle_id: UUID
    authority: OfficialAuthority
    scope: CalendarScope
    pages: tuple[CalendarScanPage, ...]
    evidence_ids: tuple[UUID, ...]
    artifact_sha256s: tuple[str, ...]
    window_start: date
    window_end: date
    page_count: int
    replayable: bool
    continuity_verified: bool
    complete: bool
    captured_at: datetime
    available_at: datetime
    covers_full_exchange: bool = False

    def __post_init__(self) -> None:
        _strict_uuid(self.bundle_id, _INVALID_SNAPSHOT)
        if type(self.authority) is not OfficialAuthority:
            _fail(_INVALID_SNAPSHOT)
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if self.authority.exchange != scope.exchange:
            _fail(_INVALID_SCOPE)
        if type(self.pages) is not tuple or not self.pages:
            _fail(_INVALID_SNAPSHOT)
        if any(type(page) is not CalendarScanPage for page in self.pages):
            _fail(_INVALID_SNAPSHOT)
        for page in self.pages:
            if page.evidence.scope != scope or page.evidence.authority is not self.authority:
                _fail(_INVALID_SCOPE)
        if type(self.evidence_ids) is not tuple or not self.evidence_ids:
            _fail(_INVALID_SNAPSHOT)
        if type(self.artifact_sha256s) is not tuple:
            _fail(_INVALID_SNAPSHOT)
        if type(self.page_count) is not int or self.page_count <= 0:
            _fail(_INVALID_SNAPSHOT)
        if self.page_count != len(self.pages):
            _fail(_INVALID_SNAPSHOT)
        if len(self.evidence_ids) != len(self.artifact_sha256s):
            _fail(_INVALID_SNAPSHOT)
        if len(self.evidence_ids) != self.page_count:
            _fail(_INVALID_SNAPSHOT)
        for evidence_id in self.evidence_ids:
            _strict_uuid(evidence_id, _INVALID_SNAPSHOT)
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            _fail(_INVALID_SNAPSHOT)
        for digest in self.artifact_sha256s:
            _strict_sha256(digest, _INVALID_SNAPSHOT)
        page_ids = tuple(page.evidence.evidence_id for page in self.pages)
        page_digests = tuple(page.evidence.artifact_sha256 for page in self.pages)
        if self.evidence_ids != page_ids or self.artifact_sha256s != page_digests:
            _fail(_INVALID_SNAPSHOT)
        if tuple(page.ordinal for page in self.pages) != tuple(range(1, self.page_count + 1)):
            _fail(_INVALID_SNAPSHOT)
        _strict_date(self.window_start, _INVALID_SNAPSHOT)
        _strict_date(self.window_end, _INVALID_SNAPSHOT)
        if self.window_start > self.window_end:
            _fail(_INVALID_SNAPSHOT)
        if self.window_start.year != scope.year or self.window_end.year != scope.year:
            _fail(_INVALID_SCOPE)
        if type(self.replayable) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if type(self.continuity_verified) is not bool or type(self.complete) is not bool:
            _fail(_INVALID_SNAPSHOT)
        if type(self.covers_full_exchange) is not bool:
            _fail(_INVALID_SNAPSHOT)
        captured_at = _utc(self.captured_at, _INVALID_SNAPSHOT)
        available_at = _utc(self.available_at, _INVALID_SNAPSHOT)
        if captured_at > available_at:
            _fail(_INVALID_SNAPSHOT)
        derived_captured_at = max(page.evidence.captured_at for page in self.pages)
        derived_available_at = max(page.evidence.available_at for page in self.pages)
        if captured_at != derived_captured_at or available_at != derived_available_at:
            _fail(_INVALID_SNAPSHOT)
        continuity_verified = _pages_are_continuous(self.pages)
        if self.continuity_verified and not continuity_verified:
            _fail(_INVALID_SNAPSHOT)
        derived_complete = (
            self.window_start == date(scope.year, 1, 1)
            and self.window_end == date(scope.year, 12, 31)
            and self.replayable
            and continuity_verified
            and self.covers_full_exchange
            and all(page.evidence.identity_verified for page in self.pages)
        )
        if self.complete != derived_complete:
            _fail(_INVALID_SNAPSHOT)
        if self.complete and not all(page.evidence.identity_verified for page in self.pages):
            _fail(_INVALID_SNAPSHOT)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "available_at", available_at)


def _pages_are_continuous(pages: tuple[CalendarScanPage, ...]) -> bool:
    if not pages or pages[0].cursor_in is not None or pages[-1].cursor_out is not None:
        return False
    if len(pages) > 1 and any(page.cursor_out is None for page in pages[:-1]):
        return False
    if len(pages) > 1 and any(page.cursor_in is None for page in pages[1:]):
        return False
    outgoing = tuple(page.cursor_out for page in pages[:-1])
    incoming = tuple(page.cursor_in for page in pages[1:])
    if outgoing != incoming or len(outgoing) != len(set(outgoing)):
        return False
    return all(
        current.cursor_out == following.cursor_in
        for current, following in zip(pages, pages[1:], strict=False)
    )


def _scan_pages_cover_deltas(
    scan: CalendarScanObservation,
    deltas: tuple[CalendarTemporaryClosureDelta, ...],
) -> bool:
    """Require every scan page to be visible no earlier than every delta."""

    return all(
        all(page.evidence.available_at >= delta.evidence.available_at for page in scan.bundle.pages)
        for delta in deltas
    )


@dataclass(frozen=True, slots=True)
class CalendarTemporaryClosureDelta:
    """One ordered, verified full-market/full-day closure delta."""

    evidence: CalendarEvidence
    closure_date: date

    def __post_init__(self) -> None:
        if type(self.evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.evidence.kind is not CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE:
            _fail(_INVALID_SNAPSHOT)
        if not self.evidence.identity_verified:
            _fail(_INVALID_SNAPSHOT)
        if not self.evidence.covers_full_exchange or not self.evidence.covers_full_day:
            _fail(_INVALID_SNAPSHOT)
        _strict_date(self.closure_date, _INVALID_SNAPSHOT)
        if self.closure_date.year != self.evidence.scope.year:
            _fail(_INVALID_SCOPE)


@dataclass(frozen=True, slots=True)
class CalendarAnnualNotice:
    """Verified annual closure dates, retained without raw provider text."""

    evidence: CalendarEvidence
    closed_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if type(self.evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.evidence.kind is not CalendarEvidenceKind.ANNUAL_NOTICE:
            _fail(_INVALID_SNAPSHOT)
        if type(self.closed_dates) is not tuple:
            _fail(_INVALID_SNAPSHOT)
        for closed_date in self.closed_dates:
            _strict_date(closed_date, _INVALID_SNAPSHOT)
            if closed_date.year != self.evidence.scope.year:
                _fail(_INVALID_SCOPE)
        if len(set(self.closed_dates)) != len(self.closed_dates):
            _fail(_INVALID_SNAPSHOT)


@dataclass(frozen=True, slots=True)
class CalendarRuleCoverage:
    """One effective-date segment of the official exchange rule set."""

    evidence: CalendarEvidence
    valid_from: date
    valid_to: date
    weekdays: tuple[int, ...]
    closes_legal_holidays: bool

    def __post_init__(self) -> None:
        if type(self.evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.evidence.kind is not CalendarEvidenceKind.RULE:
            _fail(_INVALID_SNAPSHOT)
        _strict_date(self.valid_from, _INVALID_SNAPSHOT)
        _strict_date(self.valid_to, _INVALID_SNAPSHOT)
        if self.valid_from > self.valid_to:
            _fail(_INVALID_SNAPSHOT)
        if self.valid_from.year != self.evidence.scope.year or self.valid_to.year != (
            self.evidence.scope.year
        ):
            _fail(_INVALID_SCOPE)
        if type(self.weekdays) is not tuple or not self.weekdays:
            _fail(_INVALID_SNAPSHOT)
        if any(type(day) is not int or day < 0 or day > 6 for day in self.weekdays):
            _fail(_INVALID_SNAPSHOT)
        if len(set(self.weekdays)) != len(self.weekdays):
            _fail(_INVALID_SNAPSHOT)
        if type(self.closes_legal_holidays) is not bool:
            _fail(_INVALID_SNAPSHOT)


@dataclass(frozen=True, slots=True)
class CalendarScanObservation:
    """Daily rows and their bundle-level pagination proof."""

    bundle: CalendarScanBundle
    evidence: CalendarEvidence
    days: Sequence[CalendarDay | ContractTradingDay]
    delta_evidence: CalendarEvidence | None = None
    deltas: tuple[CalendarTemporaryClosureDelta, ...] = ()

    def __post_init__(self) -> None:
        if type(self.bundle) is not CalendarScanBundle:
            _fail(_INVALID_SNAPSHOT)
        if type(self.evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.evidence.kind is not CalendarEvidenceKind.TEMPORARY_SCAN:
            _fail(_INVALID_SNAPSHOT)
        if (
            self.evidence.scope != self.bundle.scope
            or self.evidence.authority is not self.bundle.authority
            or self.evidence.evidence_id not in self.bundle.evidence_ids
        ):
            _fail(_INVALID_SCOPE)
        if self.evidence.artifact_sha256 not in self.bundle.artifact_sha256s:
            _fail(_INVALID_SNAPSHOT)
        if not any(page.evidence == self.evidence for page in self.bundle.pages):
            _fail(_INVALID_SNAPSHOT)
        if self.delta_evidence is not None:
            if type(self.delta_evidence) is not CalendarEvidence:
                _fail(_INVALID_SNAPSHOT)
            if self.delta_evidence.kind is not CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE:
                _fail(_INVALID_SNAPSHOT)
            if (
                self.delta_evidence.scope != self.bundle.scope
                or self.delta_evidence.authority is not self.bundle.authority
            ):
                _fail(_INVALID_SNAPSHOT)
        if type(self.deltas) is not tuple:
            _fail(_INVALID_SNAPSHOT)
        previous_date: date | None = None
        for delta in self.deltas:
            if type(delta) is not CalendarTemporaryClosureDelta:
                _fail(_INVALID_SNAPSHOT)
            if (
                delta.evidence.scope != self.bundle.scope
                or delta.evidence.authority is not self.bundle.authority
            ):
                _fail(_INVALID_SCOPE)
            if previous_date is not None and delta.closure_date <= previous_date:
                _fail(_INVALID_SNAPSHOT)
            previous_date = delta.closure_date
        if (
            self.delta_evidence is not None
            and self.deltas
            and not any(
                _evidence_receipt_matches(self.delta_evidence, delta.evidence)
                for delta in self.deltas
            )
        ):
            _fail(_INVALID_SNAPSHOT)
        copied_days: tuple[CalendarDay, ...] | None = None
        with suppress(Exception):
            copied_days = tuple(_copy_day(day) for day in self.days)
        if copied_days is None:
            _fail(_INVALID_DAY)
        for day in copied_days:
            if (
                day.exchange != self.bundle.scope.exchange
                or day.date.year != self.bundle.scope.year
            ):
                _fail(_INVALID_SCOPE)
        if self.bundle.complete:
            expected_dates = _expected_dates(self.bundle.scope.year)
            if (
                len(copied_days) != len(expected_dates)
                or tuple(day.date for day in copied_days) != expected_dates
            ):
                _fail(_INVALID_SNAPSHOT)
        object.__setattr__(self, "days", copied_days)

    @property
    def page_evidence(self) -> tuple[CalendarEvidence, ...]:
        """Return every ordered page receipt carried by the scan."""

        return tuple(page.evidence for page in self.bundle.pages)

    @property
    def available_at(self) -> datetime:
        """Return the latest visibility boundary of scan and optional delta."""

        candidates = [self.bundle.available_at]
        if self.delta_evidence is not None:
            candidates.append(self.delta_evidence.available_at)
        candidates.extend(delta.evidence.available_at for delta in self.deltas)
        return max(candidates)


def _copy_day(value: object) -> CalendarDay:
    if type(value) is CalendarDay:
        return CalendarDay(
            date=value.date,
            exchange=value.exchange,
            is_trading_day=value.is_trading_day,
            reason=value.reason,
        )
    if type(value) is not ContractTradingDay:
        _fail(_INVALID_DAY)

    fields: tuple[object, object, object, object, object] | None = None
    with suppress(Exception):
        fields = (value.date, value.exchange, value.is_trading_day, value.reason, value.note)
    if fields is None:
        _fail(_INVALID_DAY)
    raw_date, raw_exchange, raw_trading, raw_reason, raw_note = fields

    _strict_date(raw_date, _INVALID_DAY)
    if type(raw_exchange) is not ContractExchange:
        _fail(_INVALID_DAY)
    if type(raw_trading) is not bool:
        _fail(_INVALID_DAY)
    if raw_reason is not None and type(raw_reason) is not ContractReason:
        _fail(_INVALID_DAY)
    if raw_note is not None and type(raw_note) is not str:
        _fail(_INVALID_DAY)
    if raw_trading and raw_reason is not None:
        _fail(_INVALID_DAY)
    reason = None if raw_reason is None else _CONTRACT_REASON[raw_reason]
    return CalendarDay(
        date=raw_date,
        exchange=_CONTRACT_EXCHANGE[raw_exchange],
        is_trading_day=raw_trading,
        reason=reason,
    )


@dataclass(frozen=True, slots=True)
class CalendarSnapshot:
    """Immutable official snapshot with an explicit point-in-time boundary."""

    snapshot_id: UUID
    artifact_id: UUID
    capture_id: UUID
    artifact_sha256: str
    authority: OfficialAuthority
    scope: CalendarScope
    captured_at: datetime
    available_at: datetime
    terminal: SnapshotTerminal
    days: Sequence[CalendarDay | ContractTradingDay]
    supersedes: UUID | None = None
    evidence: Sequence[CalendarEvidence] = ()
    scan_bundle: CalendarScanBundle | None = None
    composition_receipt: CalendarCompositionReceipt | None = None
    proof: CalendarCompositionReceipt | None = None
    resolution_proof: CalendarScanRunReceipt | None = None

    def __post_init__(self) -> None:
        _strict_uuid(self.snapshot_id, _INVALID_SNAPSHOT)
        _strict_uuid(self.artifact_id, _INVALID_SNAPSHOT)
        _strict_uuid(self.capture_id, _INVALID_SNAPSHOT)
        _strict_sha256(self.artifact_sha256, _INVALID_SNAPSHOT)
        if type(self.authority) is not OfficialAuthority:
            _fail(_INVALID_SNAPSHOT)
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if self.authority.exchange != scope.exchange:
            _fail(_INVALID_SCOPE)
        if type(self.terminal) is not SnapshotTerminal:
            _fail(_INVALID_SNAPSHOT)
        captured_at = _utc(self.captured_at, _INVALID_SNAPSHOT)
        available_at = _utc(self.available_at, _INVALID_SNAPSHOT)
        if captured_at > available_at:
            _fail(_INVALID_SNAPSHOT)
        if self.supersedes is not None:
            _strict_uuid(self.supersedes, _INVALID_LINEAGE)

        copied_days: tuple[CalendarDay, ...] | None = None
        with suppress(Exception):
            copied_days = tuple(_copy_day(day) for day in self.days)
        if copied_days is None:
            _fail(_INVALID_DAY)

        seen: set[date] = set()
        for day in copied_days:
            if day.exchange != scope.exchange:
                _fail(_INVALID_SCOPE)
            if day.date.year != scope.year:
                _fail(_INVALID_SNAPSHOT)
            if day.date in seen:
                _fail(_INVALID_SNAPSHOT)
            seen.add(day.date)

        copied_evidence: tuple[CalendarEvidence, ...] | None = None
        with suppress(Exception):
            copied_evidence = tuple(self.evidence)
        if copied_evidence is None:
            _fail(_INVALID_SNAPSHOT)
        seen_evidence: set[UUID] = set()
        evidence_by_id: dict[UUID, CalendarEvidence] = {}
        for evidence in copied_evidence:
            if type(evidence) is not CalendarEvidence:
                _fail(_INVALID_SNAPSHOT)
            if evidence.scope != scope or evidence.authority is not self.authority:
                _fail(_INVALID_SCOPE)
            if evidence.evidence_id in seen_evidence:
                _fail(_INVALID_SNAPSHOT)
            seen_evidence.add(evidence.evidence_id)
            evidence_by_id[evidence.evidence_id] = evidence

        scan_bundle = self.scan_bundle
        if scan_bundle is not None:
            if type(scan_bundle) is not CalendarScanBundle:
                _fail(_INVALID_SNAPSHOT)
            if scan_bundle.scope != scope or scan_bundle.authority is not self.authority:
                _fail(_INVALID_SCOPE)
            if not set(scan_bundle.evidence_ids).issubset(seen_evidence):
                _fail(_INVALID_SNAPSHOT)
            for evidence_id, digest in zip(
                scan_bundle.evidence_ids,
                scan_bundle.artifact_sha256s,
                strict=True,
            ):
                if evidence_by_id[evidence_id].artifact_sha256 != digest:
                    _fail(_INVALID_SNAPSHOT)
            if scan_bundle.available_at > available_at:
                _fail(_INVALID_SNAPSHOT)

        composition_receipt = self.composition_receipt
        proof = self.proof
        resolution_proof = self.resolution_proof
        if resolution_proof is not None:
            if type(resolution_proof) is not CalendarScanRunReceipt:
                _fail(_INVALID_SNAPSHOT)
            if (
                resolution_proof.authority != OfficialAuthority.SZSE.value
                or resolution_proof.exchange != scope.exchange
                or resolution_proof.year != scope.year
                or self.authority is not OfficialAuthority.SZSE
            ):
                _fail(_INVALID_SCOPE)
            if (
                resolution_proof.opened_at != captured_at
                or resolution_proof.cutoff_at != available_at
            ):
                _fail(_INVALID_SNAPSHOT)
            expected_terminal = (
                SnapshotTerminal.COMPLETE
                if resolution_proof.final_year_eligible
                else SnapshotTerminal.INDETERMINATE
            )
            if self.terminal is not expected_terminal:
                _fail(_INVALID_SNAPSHOT)
            if composition_receipt is not None or proof is not None or self.scan_bundle is not None:
                _fail(_INVALID_SNAPSHOT)
            primary_artifact, primary_capture, primary_digest = resolution_proof.primary_provenance
            if (
                self.artifact_id != primary_artifact
                or self.capture_id != primary_capture
                or self.artifact_sha256 != primary_digest
            ):
                _fail(_INVALID_SNAPSHOT)
            expected_resolution_days = tuple(
                CalendarDay(
                    date=day.date,
                    exchange=scope.exchange,
                    is_trading_day=day.is_trading_day,
                    reason=None if day.is_trading_day else CalendarDayReason.SPECIAL,
                )
                for day in resolution_proof.daily_days
            )
            if tuple(copied_days) != expected_resolution_days:
                _fail(_INVALID_SNAPSHOT)
        if (
            composition_receipt is not None
            and type(composition_receipt) is not CalendarCompositionReceipt
        ):
            _fail(_INVALID_SNAPSHOT)
        if proof is not None and type(proof) is not CalendarCompositionReceipt:
            _fail(_INVALID_SNAPSHOT)
        if composition_receipt is not None and proof is not None and composition_receipt != proof:
            _fail(_INVALID_SNAPSHOT)
        receipt = composition_receipt or proof
        if receipt is not None:
            if receipt.scope != scope or receipt.authority is not self.authority:
                _fail(_INVALID_SCOPE)
            if scan_bundle is None or scan_bundle != receipt.scan.bundle:
                _fail(_INVALID_SNAPSHOT)
            if receipt.scan_watermark > available_at:
                _fail(_INVALID_SNAPSHOT)
            if not (
                receipt.primary_evidence.artifact_id == self.artifact_id
                and receipt.primary_evidence.capture_id == self.capture_id
                and receipt.primary_evidence.artifact_sha256 == self.artifact_sha256
            ):
                _fail(_INVALID_SNAPSHOT)
            proof_evidence = receipt.all_evidence
            for item in proof_evidence:
                candidate = evidence_by_id.get(item.evidence_id)
                if candidate is None or not _evidence_receipt_matches(candidate, item):
                    _fail(_INVALID_SNAPSHOT)
            if (
                tuple(copied_days) != receipt.recomputed_days
                or tuple(receipt.scan.days) != receipt.recomputed_days
            ):
                _fail(_INVALID_SNAPSHOT)

        if copied_evidence and not any(
            evidence.identity_verified
            and evidence.artifact_id == self.artifact_id
            and evidence.capture_id == self.capture_id
            and evidence.artifact_sha256 == self.artifact_sha256
            for evidence in copied_evidence
        ):
            _fail(_INVALID_SNAPSHOT)
        if any(evidence.available_at > available_at for evidence in copied_evidence):
            _fail(_INVALID_SNAPSHOT)

        if self.terminal is SnapshotTerminal.COMPLETE and (
            resolution_proof is None or not resolution_proof.final_year_eligible
        ):
            _fail(_INVALID_SNAPSHOT)
        if self.terminal is SnapshotTerminal.COMPLETE and any(
            not evidence.identity_verified for evidence in copied_evidence
        ):
            _fail(_INVALID_SNAPSHOT)

        if self.terminal is SnapshotTerminal.COMPLETE:
            expected = _expected_dates(scope.year)
            if len(copied_days) != len(expected) or seen != set(expected):
                _fail(_INVALID_SNAPSHOT)

        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "days", copied_days)
        object.__setattr__(self, "evidence", copied_evidence)
        object.__setattr__(self, "composition_receipt", receipt)
        object.__setattr__(self, "proof", receipt)
        object.__setattr__(self, "resolution_proof", resolution_proof)

    @property
    def composition_proof(self) -> CalendarCompositionReceipt | None:
        """Return the immutable proof, when this snapshot has one."""

        return self.composition_receipt

    @property
    def coverage(self) -> CalendarCoverage | ScanRunCoverage | None:
        """Return the proof coverage, when this snapshot has one."""

        if self.resolution_proof is not None:
            return self.resolution_proof.coverage
        return None if self.composition_receipt is None else self.composition_receipt.coverage


def build_authoritative_snapshot(
    *,
    snapshot_id: UUID,
    artifact_id: UUID,
    capture_id: UUID,
    artifact_sha256: str,
    authority: OfficialAuthority,
    scope: CalendarScope,
    captured_at: datetime,
    available_at: datetime,
    days: Iterable[CalendarDay | ContractTradingDay],
    evidence: Iterable[CalendarEvidence],
    scan_bundle: CalendarScanBundle | None,
    supersedes: UUID | None = None,
    force_indeterminate: bool = False,
    composition_receipt: CalendarCompositionReceipt | None = None,
    proof: CalendarCompositionReceipt | None = None,
    resolution_proof: CalendarScanRunReceipt | None = None,
) -> CalendarSnapshot:
    """Build a conservative daily snapshot candidate.

    This lower-level public helper never promotes a caller-supplied projection
    to ``COMPLETE``.  A ``CalendarScanRunReceipt`` is the only positive proof
    accepted by the direct-daily composition path.
    """

    copied_days: tuple[CalendarDay | ContractTradingDay, ...] | None = None
    copied_evidence: tuple[CalendarEvidence, ...] | None = None
    with suppress(Exception):
        copied_days = tuple(days)
        copied_evidence = tuple(evidence)
    if copied_days is None or copied_evidence is None:
        _fail(_INVALID_SNAPSHOT)
    normalized_available_at = _utc(available_at, _INVALID_SNAPSHOT)
    scope = _strict_scope(scope, _INVALID_SCOPE)
    if type(authority) is not OfficialAuthority or authority.exchange != scope.exchange:
        _fail(_INVALID_SCOPE)
    terminal = (
        SnapshotTerminal.COMPLETE
        if resolution_proof is not None and resolution_proof.final_year_eligible
        else SnapshotTerminal.INDETERMINATE
    )
    return CalendarSnapshot(
        snapshot_id=snapshot_id,
        artifact_id=artifact_id,
        capture_id=capture_id,
        artifact_sha256=artifact_sha256,
        authority=authority,
        scope=scope,
        captured_at=captured_at,
        available_at=normalized_available_at,
        terminal=terminal,
        days=copied_days,
        supersedes=supersedes,
        evidence=copied_evidence,
        scan_bundle=scan_bundle,
        composition_receipt=composition_receipt,
        proof=proof,
        resolution_proof=resolution_proof,
    )


@dataclass(frozen=True, slots=True)
class CalendarRuleProfile:
    """Optional, exchange/year-specific effective-date boundary requirements."""

    scope: CalendarScope
    required_rule_starts: tuple[date, ...] = ()

    def __post_init__(self) -> None:
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if type(self.required_rule_starts) is not tuple:
            _fail(_INVALID_SNAPSHOT)
        for required_start in self.required_rule_starts:
            _strict_date(required_start, _INVALID_SNAPSHOT)
            if required_start.year != scope.year:
                _fail(_INVALID_SCOPE)
        if len(set(self.required_rule_starts)) != len(self.required_rule_starts):
            _fail(_INVALID_SNAPSHOT)


def _rules_cover_year(scope: CalendarScope, rules: tuple[CalendarRuleCoverage, ...]) -> bool:
    if not rules:
        return False
    ordered = tuple(sorted(rules, key=lambda rule: rule.valid_from))
    expected_start = date(scope.year, 1, 1)
    expected_end = date(scope.year, 12, 31)
    cursor = expected_start
    finished = False
    for rule in ordered:
        if finished or rule.evidence.scope != scope or rule.valid_from != cursor:
            return False
        if rule.valid_to == expected_end:
            finished = True
        else:
            cursor = date.fromordinal(rule.valid_to.toordinal() + 1)
    return finished and all(rule.closes_legal_holidays for rule in ordered)


def _rules_match_profile(
    scope: CalendarScope,
    rules: tuple[CalendarRuleCoverage, ...],
    profile: CalendarRuleProfile | None,
) -> bool:
    if profile is None:
        return scope.year != 2026
    if type(profile) is not CalendarRuleProfile or profile.scope != scope:
        return False
    if scope.year == 2026 and _P1N07_2026_RULE_CHANGE not in profile.required_rule_starts:
        return False
    starts = {rule.valid_from for rule in rules}
    return all(required_start in starts for required_start in profile.required_rule_starts)


def _baseline_days(
    scope: CalendarScope,
    annual_notice: CalendarAnnualNotice,
    rules: tuple[CalendarRuleCoverage, ...],
) -> tuple[CalendarDay, ...]:
    holiday_dates = set(annual_notice.closed_dates)
    result: list[CalendarDay] = []
    for current in _expected_dates(scope.year):
        if current.weekday() >= 5:
            result.append(
                CalendarDay(
                    date=current,
                    exchange=scope.exchange,
                    is_trading_day=False,
                    reason=CalendarDayReason.WEEKEND,
                )
            )
            continue
        if current in holiday_dates:
            result.append(
                CalendarDay(
                    date=current,
                    exchange=scope.exchange,
                    is_trading_day=False,
                    reason=CalendarDayReason.PUBLIC_HOLIDAY,
                )
            )
            continue
        matching = next(
            (rule for rule in rules if rule.valid_from <= current <= rule.valid_to),
            None,
        )
        if matching is not None and current.weekday() in matching.weekdays:
            result.append(CalendarDay(date=current, exchange=scope.exchange, is_trading_day=True))
        else:
            result.append(
                CalendarDay(
                    date=current,
                    exchange=scope.exchange,
                    is_trading_day=False,
                    reason=CalendarDayReason.SPECIAL,
                )
            )
    return tuple(result)


def _apply_calendar_deltas(
    baseline: tuple[CalendarDay, ...],
    deltas: tuple[CalendarTemporaryClosureDelta, ...],
) -> tuple[CalendarDay, ...]:
    """Apply ordered, all-day closures without mutating the baseline."""

    by_date = {day.date: day for day in baseline}
    for delta in deltas:
        current = by_date.get(delta.closure_date)
        if current is None or not current.is_trading_day:
            _fail(_INVALID_SNAPSHOT)
        by_date[delta.closure_date] = CalendarDay(
            date=current.date,
            exchange=current.exchange,
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
    return tuple(by_date[current.date] for current in baseline)


def _evidence_receipt_matches(left: CalendarEvidence, right: CalendarEvidence) -> bool:
    return type(left) is CalendarEvidence and type(right) is CalendarEvidence and left == right


def _coverage_binding_sha256(coverage: CalendarCoverage) -> str:
    payload = "|".join(
        (
            coverage.scope.exchange,
            str(coverage.scope.year),
            coverage.level.value,
            coverage.confirmed_through.isoformat(),
            coverage.publication_cutoff.isoformat(),
            coverage.source_policy_id,
            coverage.source_catalog_sha256,
            str(coverage.two_pass_verified),
            str(coverage.source_policy_verified),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _composition_binding_sha256(
    *,
    annual_notice: CalendarAnnualNotice,
    rules: tuple[CalendarRuleCoverage, ...],
    rule_profile: CalendarRuleProfile | None,
    scan: CalendarScanObservation,
    deltas: tuple[CalendarTemporaryClosureDelta, ...],
    primary_evidence: CalendarEvidence,
    coverage: CalendarCoverage,
) -> str:
    payload = repr(
        (
            annual_notice,
            rules,
            rule_profile,
            scan,
            deltas,
            primary_evidence,
            coverage,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CalendarCompositionReceipt:
    """Single immutable proof for a recomputable official composition."""

    authority: OfficialAuthority
    scope: CalendarScope
    annual_notice: CalendarAnnualNotice
    rules: tuple[CalendarRuleCoverage, ...]
    rule_profile: CalendarRuleProfile | None
    scan: CalendarScanObservation
    deltas: tuple[CalendarTemporaryClosureDelta, ...]
    primary_evidence: CalendarEvidence
    coverage: CalendarCoverage
    scan_watermark: datetime
    coverage_binding_sha256: str = ""
    composition_binding_sha256: str = ""

    def __post_init__(self) -> None:
        if type(self.authority) is not OfficialAuthority:
            _fail(_INVALID_SNAPSHOT)
        scope = _strict_scope(self.scope, _INVALID_SCOPE)
        if self.authority.exchange != scope.exchange:
            _fail(_INVALID_SCOPE)
        if type(self.annual_notice) is not CalendarAnnualNotice:
            _fail(_INVALID_SNAPSHOT)
        if (
            self.annual_notice.evidence.scope != scope
            or self.annual_notice.evidence.authority is not self.authority
        ):
            _fail(_INVALID_SCOPE)
        if type(self.rules) is not tuple or not self.rules:
            _fail(_INVALID_SNAPSHOT)
        if any(type(rule) is not CalendarRuleCoverage for rule in self.rules):
            _fail(_INVALID_SNAPSHOT)
        if any(
            rule.evidence.scope != scope or rule.evidence.authority is not self.authority
            for rule in self.rules
        ):
            _fail(_INVALID_SCOPE)
        if tuple(rule.valid_from for rule in self.rules) != tuple(
            sorted(rule.valid_from for rule in self.rules)
        ):
            _fail(_INVALID_SNAPSHOT)
        if self.rule_profile is not None and type(self.rule_profile) is not CalendarRuleProfile:
            _fail(_INVALID_SNAPSHOT)
        if type(self.scan) is not CalendarScanObservation:
            _fail(_INVALID_SNAPSHOT)
        if self.scan.bundle.scope != scope or self.scan.bundle.authority is not self.authority:
            _fail(_INVALID_SCOPE)
        if type(self.deltas) is not tuple:
            _fail(_INVALID_SNAPSHOT)
        previous_date: date | None = None
        for delta in self.deltas:
            if type(delta) is not CalendarTemporaryClosureDelta:
                _fail(_INVALID_SNAPSHOT)
            if delta.evidence.scope != scope or delta.evidence.authority is not self.authority:
                _fail(_INVALID_SCOPE)
            if previous_date is not None and delta.closure_date <= previous_date:
                _fail(_INVALID_SNAPSHOT)
            previous_date = delta.closure_date
        if type(self.primary_evidence) is not CalendarEvidence:
            _fail(_INVALID_SNAPSHOT)
        if self.primary_evidence.kind not in {
            CalendarEvidenceKind.TEMPORARY_SCAN,
            CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE,
        }:
            _fail(_INVALID_SNAPSHOT)
        if type(self.coverage) is not CalendarCoverage:
            _fail(_INVALID_SNAPSHOT)
        if self.coverage.scope != scope:
            _fail(_INVALID_SCOPE)
        watermark = _utc(self.scan_watermark, _INVALID_SNAPSHOT)
        observed_delta_evidence = tuple(delta.evidence for delta in self.scan.deltas)
        if self.scan.delta_evidence is not None:
            observed_delta_evidence = (*observed_delta_evidence, self.scan.delta_evidence)
        if self.scan.deltas:
            if tuple(self.scan.deltas) != self.deltas:
                _fail(_INVALID_SNAPSHOT)
        elif self.scan.delta_evidence is not None:
            if len(self.deltas) != 1 or not _evidence_receipt_matches(
                self.deltas[0].evidence, self.scan.delta_evidence
            ):
                _fail(_INVALID_SNAPSHOT)
        elif self.deltas:
            _fail(_INVALID_SNAPSHOT)
        if not _scan_pages_cover_deltas(self.scan, self.deltas):
            _fail(_INVALID_SNAPSHOT)

        evidence = self.all_evidence
        evidence_ids = tuple(item.evidence_id for item in evidence)
        if len(set(evidence_ids)) != len(evidence_ids):
            _fail(_INVALID_SNAPSHOT)
        if not all(item.identity_verified for item in evidence):
            _fail(_INVALID_SNAPSHOT)
        if not any(_evidence_receipt_matches(item, self.primary_evidence) for item in evidence):
            _fail(_INVALID_SNAPSHOT)
        if self.scan.available_at > watermark:
            _fail(_INVALID_SNAPSHOT)
        expected_watermark = max(
            self.coverage.publication_cutoff,
            *(item.available_at for item in evidence),
        )
        if watermark != expected_watermark:
            _fail(_INVALID_SNAPSHOT)
        if self.rule_profile is not None and self.rule_profile.scope != scope:
            _fail(_INVALID_SCOPE)
        coverage_binding = _coverage_binding_sha256(self.coverage)
        if self.coverage_binding_sha256 not in {"", coverage_binding}:
            _fail(_INVALID_SNAPSHOT)
        composition_binding = _composition_binding_sha256(
            annual_notice=self.annual_notice,
            rules=self.rules,
            rule_profile=self.rule_profile,
            scan=self.scan,
            deltas=self.deltas,
            primary_evidence=self.primary_evidence,
            coverage=self.coverage,
        )
        if self.composition_binding_sha256 not in {"", composition_binding}:
            _fail(_INVALID_SNAPSHOT)
        object.__setattr__(self, "scan_watermark", watermark)
        object.__setattr__(self, "coverage_binding_sha256", coverage_binding)
        object.__setattr__(self, "composition_binding_sha256", composition_binding)

    @property
    def all_evidence(self) -> tuple[CalendarEvidence, ...]:
        """Return the exact ordered evidence receipts used by this proof."""

        return (
            self.annual_notice.evidence,
            *(rule.evidence for rule in self.rules),
            *self.scan.page_evidence,
            *(delta.evidence for delta in self.deltas),
        )

    @property
    def recomputed_days(self) -> tuple[CalendarDay, ...]:
        """Recompute the immutable daily rows from annual evidence and deltas."""

        baseline = _baseline_days(self.scope, self.annual_notice, self.rules)
        return _apply_calendar_deltas(baseline, self.deltas)

    @property
    def rules_complete(self) -> bool:
        return _rules_cover_year(self.scope, self.rules) and _rules_match_profile(
            self.scope, self.rules, self.rule_profile
        )

    @property
    def scan_complete(self) -> bool:
        return (
            self.scan.bundle.complete
            and self.scan.bundle.replayable
            and self.scan.bundle.continuity_verified
            and self.scan.bundle.covers_full_exchange
            and self.scan.bundle.window_start == date(self.scope.year, 1, 1)
            and self.scan.bundle.window_end == date(self.scope.year, 12, 31)
            and _scan_pages_cover_deltas(self.scan, self.deltas)
            and tuple(self.scan.days) == self.recomputed_days
        )

    @property
    def watermark_complete(self) -> bool:
        """Return whether the scan pages reach the declared visibility horizon."""

        return (
            self.coverage.is_verified and self.scan.available_at >= self.coverage.publication_cutoff
        )

    @property
    def complete_eligible(self) -> bool:
        """Return whether this proof can support a final-year COMPLETE snapshot."""

        return (
            self.coverage.final_year_eligible
            and self.watermark_complete
            and self.rules_complete
            and self.scan_complete
        )

    @property
    def primary_receipt(self) -> CalendarEvidence:
        """Return the evidence receipt anchoring snapshot provenance."""

        return self.primary_evidence

    @property
    def watermark(self) -> datetime:
        """Return the point-in-time watermark bound to this composition."""

        return self.scan_watermark

    @property
    def composition_binding(self) -> str:
        """Return the immutable digest of all proof inputs."""

        return self.composition_binding_sha256


# A proof is an interchangeable public spelling used by callers that prefer
# the term ``proof``; both names refer to the same immutable type.
CalendarCompositionProof = CalendarCompositionReceipt


def _receipt_provenance(evidence: CalendarEvidence) -> tuple[UUID, UUID, str]:
    if type(evidence) is not CalendarEvidence:
        _fail(_INVALID_SNAPSHOT)
    if evidence.artifact_id is None or evidence.capture_id is None:
        _fail(_INVALID_SNAPSHOT)
    return evidence.artifact_id, evidence.capture_id, evidence.artifact_sha256


def compose_direct_daily_snapshot(
    *,
    snapshot_id: UUID,
    run_receipt: CalendarScanRunReceipt,
    supersedes: UUID | None = None,
) -> CalendarSnapshot:
    """Build a SZSE snapshot solely from a validated direct-daily run proof.

    The run receipt owns the ordered daily rows, provenance and point-in-time
    boundaries.  There are intentionally no caller-supplied ``days`` or
    watermark parameters to override those values.
    """

    if type(run_receipt) is not CalendarScanRunReceipt:
        _fail(_INVALID_SNAPSHOT)
    artifact_id, capture_id, artifact_sha256 = run_receipt.primary_provenance
    scope = CalendarScope(exchange="SZ", year=run_receipt.year)
    days = tuple(
        CalendarDay(
            date=day.date,
            exchange="SZ",
            is_trading_day=day.is_trading_day,
            reason=None if day.is_trading_day else CalendarDayReason.SPECIAL,
        )
        for day in run_receipt.daily_days
    )
    terminal = (
        SnapshotTerminal.COMPLETE
        if run_receipt.final_year_eligible
        else SnapshotTerminal.INDETERMINATE
    )
    return CalendarSnapshot(
        snapshot_id=snapshot_id,
        artifact_id=artifact_id,
        capture_id=capture_id,
        artifact_sha256=artifact_sha256,
        authority=OfficialAuthority.SZSE,
        scope=scope,
        captured_at=run_receipt.opened_at,
        available_at=run_receipt.cutoff_at,
        terminal=terminal,
        days=days,
        supersedes=supersedes,
        resolution_proof=run_receipt,
    )


def compose_official_calendar(
    *,
    snapshot_id: UUID,
    authority: OfficialAuthority,
    scope: CalendarScope,
    annual_notice: CalendarAnnualNotice,
    rules: Iterable[CalendarRuleCoverage],
    scan: CalendarScanObservation | None,
    captured_at: datetime,
    available_at: datetime,
    rule_profile: CalendarRuleProfile | None = None,
    supersedes: UUID | None = None,
    coverage: CalendarCoverage | None = None,
    deltas: Iterable[CalendarTemporaryClosureDelta] = (),
) -> CalendarSnapshot:
    """Compose a safe daily calendar from verified rule and scan inputs."""

    if type(annual_notice) is not CalendarAnnualNotice:
        _fail(_INVALID_SNAPSHOT)
    if annual_notice.evidence.scope != scope or annual_notice.evidence.authority is not authority:
        _fail(_INVALID_SCOPE)
    copied_rules: tuple[CalendarRuleCoverage, ...] | None = None
    with suppress(Exception):
        copied_rules = tuple(rules)
    if copied_rules is None or any(type(rule) is not CalendarRuleCoverage for rule in copied_rules):
        _fail(_INVALID_SNAPSHOT)
    for rule in copied_rules:
        if rule.evidence.scope != scope or rule.evidence.authority is not authority:
            _fail(_INVALID_SCOPE)
    if coverage is not None and type(coverage) is not CalendarCoverage:
        _fail(_INVALID_SNAPSHOT)
    if coverage is not None and coverage.scope != scope:
        _fail(_INVALID_SCOPE)
    copied_deltas: tuple[CalendarTemporaryClosureDelta, ...] | None = None
    with suppress(Exception):
        copied_deltas = tuple(deltas)
    if copied_deltas is None or any(
        type(delta) is not CalendarTemporaryClosureDelta for delta in copied_deltas
    ):
        _fail(_INVALID_SNAPSHOT)
    previous_date: date | None = None
    for delta in copied_deltas:
        if delta.evidence.scope != scope or delta.evidence.authority is not authority:
            _fail(_INVALID_SCOPE)
        if previous_date is not None and delta.closure_date <= previous_date:
            _fail(_INVALID_SNAPSHOT)
        previous_date = delta.closure_date
    if scan is not None:
        if type(scan) is not CalendarScanObservation:
            _fail(_INVALID_SNAPSHOT)
        if scan.deltas:
            if copied_deltas and tuple(scan.deltas) != copied_deltas:
                _fail(_INVALID_SNAPSHOT)
            copied_deltas = tuple(scan.deltas)
        elif scan.delta_evidence is not None:
            if not copied_deltas or not any(
                _evidence_receipt_matches(scan.delta_evidence, delta.evidence)
                for delta in copied_deltas
            ):
                _fail(_INVALID_SNAPSHOT)
        for delta in copied_deltas:
            if delta.evidence.scope != scope or delta.evidence.authority is not authority:
                _fail(_INVALID_SCOPE)
    baseline = _baseline_days(scope, annual_notice, copied_rules)
    composed_rows = _apply_calendar_deltas(baseline, copied_deltas)
    normalized_available_at = _utc(available_at, _INVALID_SNAPSHOT)
    scan_rows = composed_rows
    scan_is_valid = False
    scan_evidence: tuple[CalendarEvidence, ...] = ()
    scan_bundle: CalendarScanBundle | None = None
    if scan is not None:
        scan_rows = tuple(scan.days)
        scan_evidence = scan.page_evidence
        scan_bundle = scan.bundle
        scan_is_valid = (
            scan.bundle.complete
            and scan.bundle.replayable
            and scan.bundle.continuity_verified
            and scan.bundle.covers_full_exchange
            and scan.bundle.window_start == date(scope.year, 1, 1)
            and scan.bundle.window_end == date(scope.year, 12, 31)
            and _scan_pages_cover_deltas(scan, copied_deltas)
            and len(scan_rows) == len(composed_rows)
            and tuple(day.date for day in scan_rows) == tuple(day.date for day in composed_rows)
            and all(left == right for left, right in zip(scan_rows, composed_rows, strict=True))
            and scan.available_at <= normalized_available_at
        )
        if scan.available_at > normalized_available_at:
            _fail(_INVALID_SNAPSHOT)
    evidence_items = (
        annual_notice.evidence,
        *(rule.evidence for rule in copied_rules),
        *scan_evidence,
        *(delta.evidence for delta in copied_deltas),
    )
    evidence: list[CalendarEvidence] = []
    seen_evidence: set[UUID] = set()
    for item in evidence_items:
        if item.evidence_id not in seen_evidence:
            seen_evidence.add(item.evidence_id)
            evidence.append(item)
    provenance_source = scan_evidence[0] if scan_evidence else annual_notice.evidence
    artifact_id, capture_id, artifact_sha256 = _receipt_provenance(provenance_source)
    receipt: CalendarCompositionReceipt | None = None
    if scan is not None and coverage is not None and scan_is_valid:
        if scan.available_at > normalized_available_at:
            _fail(_INVALID_SNAPSHOT)
        receipt_watermark = max(
            coverage.publication_cutoff,
            *(
                item.available_at
                for item in (
                    annual_notice.evidence,
                    *(rule.evidence for rule in copied_rules),
                    *scan_evidence,
                    *(delta.evidence for delta in copied_deltas),
                )
            ),
        )
        if receipt_watermark <= normalized_available_at:
            receipt = CalendarCompositionReceipt(
                authority=authority,
                scope=scope,
                annual_notice=annual_notice,
                rules=copied_rules,
                rule_profile=rule_profile,
                scan=scan,
                deltas=copied_deltas,
                primary_evidence=provenance_source,
                coverage=coverage,
                scan_watermark=receipt_watermark,
            )
        if receipt is not None and receipt.scan_complete:
            composed_rows = receipt.recomputed_days
            scan_rows = tuple(scan.days)
    # The annual/rule composition is retained as a candidate and audit record.
    # Positive resolution now requires a CalendarScanRunReceipt produced by the
    # direct-daily proof path; this legacy composer must never emit COMPLETE.
    terminal = SnapshotTerminal.INDETERMINATE
    return CalendarSnapshot(
        snapshot_id=snapshot_id,
        artifact_id=artifact_id,
        capture_id=capture_id,
        artifact_sha256=artifact_sha256,
        authority=authority,
        scope=scope,
        captured_at=captured_at,
        available_at=available_at,
        terminal=terminal,
        days=scan_rows,
        evidence=tuple(evidence),
        scan_bundle=scan_bundle,
        supersedes=supersedes,
        composition_receipt=receipt,
    )


def apply_temporary_closure(
    parent: CalendarSnapshot,
    *,
    snapshot_id: UUID,
    evidence: CalendarEvidence,
    closure_date: date,
    captured_at: datetime,
    available_at: datetime,
    successor_scan: CalendarScanObservation | None = None,
) -> CalendarSnapshot:
    """Materialize a verified full-day closure and its successor scan.

    The delta receipt supplies the child provenance.  Without a successor scan
    that contains the delta and proves the complete replacement, the child is
    retained as ``INDETERMINATE`` so it cannot become a positive resolution.
    """

    if type(parent) is not CalendarSnapshot:
        _fail(_INVALID_LINEAGE)
    parent_receipt = parent.composition_receipt
    if parent_receipt is None:
        _fail(_INVALID_LINEAGE)
    if type(evidence) is not CalendarEvidence:
        _fail(_INVALID_SNAPSHOT)
    if evidence.kind is not CalendarEvidenceKind.TEMPORARY_CLOSURE_NOTICE:
        _fail(_INVALID_SNAPSHOT)
    if not evidence.identity_verified:
        _fail(_INVALID_SNAPSHOT)
    if not evidence.covers_full_exchange or not evidence.covers_full_day:
        _fail(_INVALID_SNAPSHOT)
    if evidence.scope != parent.scope or evidence.authority is not parent.authority:
        _fail(_INVALID_SCOPE)
    _strict_date(closure_date, _INVALID_SNAPSHOT)
    if closure_date.year != parent.scope.year:
        _fail(_INVALID_SCOPE)
    existing = next((day for day in parent.days if day.date == closure_date), None)
    if existing is None or not existing.is_trading_day:
        _fail(_INVALID_SNAPSHOT)
    child_available_at = _utc(available_at, _INVALID_SNAPSHOT)
    if child_available_at < parent.available_at or child_available_at < evidence.available_at:
        _fail(_INVALID_SNAPSHOT)
    delta = CalendarTemporaryClosureDelta(evidence=evidence, closure_date=closure_date)
    replaced_days = tuple(
        CalendarDay(
            date=day.date,
            exchange=parent.scope.exchange,
            is_trading_day=False,
            reason=CalendarDayReason.TEMPORARY_CLOSURE,
        )
        if day.date == closure_date
        else _copy_day(day)
        for day in parent.days
    )
    successor_is_valid = False
    valid_successor: CalendarScanObservation | None = None
    if successor_scan is not None:
        if type(successor_scan) is not CalendarScanObservation:
            _fail(_INVALID_SNAPSHOT)
        valid_successor = successor_scan
        successor_bundle = successor_scan.bundle
        expected_deltas = tuple(
            sorted(
                (*parent_receipt.deltas, delta),
                key=lambda item: item.closure_date,
            )
        )
        successor_deltas = successor_scan.deltas
        if not successor_deltas and successor_scan.delta_evidence is not None:
            if not _evidence_receipt_matches(successor_scan.delta_evidence, evidence):
                _fail(_INVALID_SNAPSHOT)
            successor_deltas = (delta,)
        if tuple(successor_deltas) != expected_deltas:
            _fail(_INVALID_SNAPSHOT)
        if successor_bundle.available_at < evidence.available_at or any(
            page.evidence.available_at < evidence.available_at for page in successor_bundle.pages
        ):
            _fail(_INVALID_SNAPSHOT)
        successor_is_valid = (
            successor_bundle.scope == parent.scope
            and successor_bundle.authority is parent.authority
            and successor_bundle.complete
            and successor_bundle.replayable
            and successor_bundle.continuity_verified
            and successor_bundle.covers_full_exchange
            and successor_bundle.window_start == date(parent.scope.year, 1, 1)
            and successor_bundle.window_end == date(parent.scope.year, 12, 31)
            and successor_scan.available_at >= evidence.available_at
            and successor_scan.available_at <= child_available_at
            and tuple(successor_deltas) == expected_deltas
        )
        if successor_is_valid:
            expected_days = _apply_calendar_deltas(
                _baseline_days(
                    parent_receipt.scope, parent_receipt.annual_notice, parent_receipt.rules
                ),
                expected_deltas,
            )
            successor_is_valid = tuple(successor_scan.days) == expected_days
    if successor_is_valid and valid_successor is not None:
        child_days = tuple(_copy_day(day) for day in valid_successor.days)
        child_scan_bundle = valid_successor.bundle
        child_deltas = tuple(
            sorted((*parent_receipt.deltas, delta), key=lambda item: item.closure_date)
        )
        child_evidence_sources: tuple[CalendarEvidence, ...] = (
            parent_receipt.annual_notice.evidence,
            *(rule.evidence for rule in parent_receipt.rules),
            *valid_successor.page_evidence,
            *(item.evidence for item in child_deltas),
        )
    else:
        child_days = replaced_days
        child_scan_bundle = None
        child_evidence_sources = (*parent.evidence, evidence)
        child_deltas = ()
    child_evidence: list[CalendarEvidence] = []
    seen_evidence: set[UUID] = set()
    for item in child_evidence_sources:
        if item.evidence_id not in seen_evidence:
            seen_evidence.add(item.evidence_id)
            child_evidence.append(item)
    if evidence.artifact_id is None or evidence.capture_id is None:
        _fail(_INVALID_SNAPSHOT)
    child_receipt: CalendarCompositionReceipt | None = None
    child_terminal = SnapshotTerminal.INDETERMINATE
    if successor_is_valid and valid_successor is not None:
        child_receipt = CalendarCompositionReceipt(
            authority=parent.authority,
            scope=parent.scope,
            annual_notice=parent_receipt.annual_notice,
            rules=parent_receipt.rules,
            rule_profile=parent_receipt.rule_profile,
            scan=valid_successor,
            deltas=child_deltas,
            primary_evidence=evidence,
            coverage=parent_receipt.coverage,
            scan_watermark=max(
                parent_receipt.coverage.publication_cutoff,
                *(
                    item.available_at
                    for item in (
                        parent_receipt.annual_notice.evidence,
                        *(rule.evidence for rule in parent_receipt.rules),
                        *valid_successor.page_evidence,
                        *(item.evidence for item in child_deltas),
                    )
                ),
            ),
        )
        # A temporary notice is not itself a direct-daily run proof.  Even a
        # structurally valid legacy successor remains candidate-only here; a
        # later post-notice CalendarScanRunReceipt must establish positive
        # resolution.
    return CalendarSnapshot(
        snapshot_id=snapshot_id,
        artifact_id=evidence.artifact_id,
        capture_id=evidence.capture_id,
        artifact_sha256=evidence.artifact_sha256,
        authority=parent.authority,
        scope=parent.scope,
        captured_at=captured_at,
        available_at=child_available_at,
        terminal=child_terminal,
        days=child_days,
        supersedes=parent.snapshot_id,
        evidence=tuple(child_evidence),
        scan_bundle=child_scan_bundle,
        composition_receipt=child_receipt,
    )


@dataclass(frozen=True, slots=True)
class SecondaryCalendarObservation:
    """Typed secondary observation; no source metadata or free text is kept."""

    evidence_id: UUID
    artifact_sha256: str
    scope: CalendarScope
    date: date
    is_trading_day: bool
    available_at: datetime

    def __post_init__(self) -> None:
        _strict_uuid(self.evidence_id, _INVALID_SECONDARY)
        _strict_sha256(self.artifact_sha256, _INVALID_SECONDARY)
        scope = _strict_scope(self.scope, _INVALID_SECONDARY)
        _strict_date(self.date, _INVALID_SECONDARY)
        if type(self.is_trading_day) is not bool:
            _fail(_INVALID_SECONDARY)
        available_at = _utc(self.available_at, _INVALID_SECONDARY)
        if self.date.year != scope.year:
            _fail(_INVALID_SCOPE)
        object.__setattr__(self, "available_at", available_at)

    @property
    def status(self) -> CalendarResolutionStatus:
        return (
            CalendarResolutionStatus.TRADING
            if self.is_trading_day
            else CalendarResolutionStatus.NON_TRADING
        )


@dataclass(frozen=True, slots=True)
class SecondaryConflictEvidence:
    """Redacted immutable evidence for a same-date secondary disagreement."""

    evidence_ids: tuple[UUID, ...]
    artifact_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.evidence_ids) is not tuple or type(self.artifact_digests) is not tuple:
            _fail(_INVALID_RESOLUTION)
        if len(self.evidence_ids) != len(self.artifact_digests) or not self.evidence_ids:
            _fail(_INVALID_RESOLUTION)
        for evidence_id in self.evidence_ids:
            _strict_uuid(evidence_id, _INVALID_RESOLUTION)
        for digest in self.artifact_digests:
            _strict_sha256(digest, _INVALID_RESOLUTION)


@dataclass(frozen=True, slots=True)
class CalendarResolution:
    """Fixed-shape answer with no provider metadata or raw input."""

    exchange: ExchangeCode
    date: date
    as_of: datetime
    status: CalendarResolutionStatus
    reason: CalendarResolutionReason
    selected_version: UUID | None = None
    selected_available_at: datetime | None = None
    secondary_conflict: SecondaryConflictEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.exchange) is not str or self.exchange not in {"SH", "SZ", "BJ"}:
            _fail(_INVALID_RESOLUTION)
        _strict_date(self.date, _INVALID_RESOLUTION)
        as_of = _utc(self.as_of, _INVALID_RESOLUTION)
        if type(self.status) is not CalendarResolutionStatus:
            _fail(_INVALID_RESOLUTION)
        if type(self.reason) is not CalendarResolutionReason:
            _fail(_INVALID_RESOLUTION)
        if self.selected_version is not None:
            _strict_uuid(self.selected_version, _INVALID_RESOLUTION)
        if self.selected_available_at is not None:
            selected_available_at = _utc(self.selected_available_at, _INVALID_RESOLUTION)
        else:
            selected_available_at = None
        if (self.selected_version is None) != (selected_available_at is None):
            _fail(_INVALID_RESOLUTION)
        if (
            self.secondary_conflict is not None
            and type(self.secondary_conflict) is not SecondaryConflictEvidence
        ):
            _fail(_INVALID_RESOLUTION)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "selected_available_at", selected_available_at)


def _typed_snapshot_inputs(
    snapshots: Iterable[CalendarSnapshot],
) -> tuple[CalendarSnapshot, ...]:
    values: tuple[CalendarSnapshot, ...] | None = None
    with suppress(Exception):
        values = tuple(snapshots)
    if values is None:
        _fail(_INVALID_SNAPSHOT)

    for snapshot in values:
        if type(snapshot) is not CalendarSnapshot:
            _fail(_INVALID_SNAPSHOT)
        _strict_scope(snapshot.scope, _INVALID_SCOPE)
    return values


def _secondary_conflict(
    *,
    exchange: ExchangeCode,
    target_date: date,
    as_of: datetime,
    official: CalendarResolutionStatus | None,
    secondary: Iterable[SecondaryCalendarObservation] | None,
) -> SecondaryConflictEvidence | None:
    if secondary is None:
        return None
    observations: tuple[SecondaryCalendarObservation, ...] | None = None
    with suppress(Exception):
        observations = tuple(secondary)
    if observations is None:
        _fail(_INVALID_SECONDARY)
    matching: list[SecondaryCalendarObservation] = []
    target_scope = CalendarScope(exchange=exchange, year=target_date.year)
    for observation in observations:
        if type(observation) is not SecondaryCalendarObservation:
            _fail(_INVALID_SECONDARY)
        if (
            observation.scope == target_scope
            and observation.date == target_date
            and observation.available_at <= as_of
        ):
            matching.append(observation)

    secondary_statuses = {observation.status for observation in matching}
    has_secondary_conflict = len(secondary_statuses) > 1
    has_official_conflict = official is not None and any(
        observation.status is not official for observation in matching
    )
    if not has_secondary_conflict and not has_official_conflict:
        return None

    ordered = sorted(
        matching,
        key=lambda observation: (observation.evidence_id.bytes, observation.artifact_sha256),
    )
    return SecondaryConflictEvidence(
        evidence_ids=tuple(observation.evidence_id for observation in ordered),
        artifact_digests=tuple(observation.artifact_sha256 for observation in ordered),
    )


def resolve(
    exchange: ExchangeCode,
    date: date,
    as_of: datetime,
    snapshots: Iterable[CalendarSnapshot] | None,
    *,
    secondary: Iterable[SecondaryCalendarObservation] | None = None,
) -> CalendarResolution:
    """Resolve one date using only visible, valid official snapshot lineage."""

    if type(exchange) is not str or exchange not in {"SH", "SZ", "BJ"}:
        _fail(_INVALID_SCOPE)
    target_date = _strict_date(date, _INVALID_SCOPE)
    cutoff = _utc(as_of, _INVALID_RESOLUTION)
    official_inputs = _typed_snapshot_inputs(() if snapshots is None else snapshots)

    visible = tuple(snapshot for snapshot in official_inputs if snapshot.available_at <= cutoff)
    target_scope = CalendarScope(exchange=exchange, year=target_date.year)
    target_visible = tuple(snapshot for snapshot in visible if snapshot.scope == target_scope)
    selected: CalendarSnapshot | None = None
    result_status = CalendarResolutionStatus.INDETERMINATE
    result_reason = CalendarResolutionReason.NO_VISIBLE_OFFICIAL

    if target_visible:
        visible_by_id: dict[UUID, CalendarSnapshot] = {}
        duplicate_ids: set[UUID] = set()
        for snapshot in visible:
            if snapshot.snapshot_id in visible_by_id:
                duplicate_ids.add(snapshot.snapshot_id)
            else:
                visible_by_id[snapshot.snapshot_id] = snapshot

        target_by_id = {snapshot.snapshot_id: snapshot for snapshot in target_visible}
        invalid_lineage = len(target_by_id) != len(target_visible)
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        for root in target_visible:
            stack: list[tuple[CalendarSnapshot, bool]] = [(root, False)]
            while stack:
                snapshot, exiting = stack.pop()
                snapshot_id = snapshot.snapshot_id
                if exiting:
                    visiting.discard(snapshot_id)
                    visited.add(snapshot_id)
                    continue
                if snapshot_id in duplicate_ids or snapshot_id in visiting:
                    invalid_lineage = True
                    continue
                if snapshot_id in visited:
                    continue
                visiting.add(snapshot_id)
                stack.append((snapshot, True))
                parent_id = snapshot.supersedes
                if parent_id is None:
                    continue
                parent = visible_by_id.get(parent_id)
                if (
                    parent is None
                    or parent.scope != target_scope
                    or parent.authority is not snapshot.authority
                    or parent.available_at > snapshot.available_at
                ):
                    invalid_lineage = True
                    continue
                stack.append((parent, False))

        if invalid_lineage:
            result_reason = CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE
        else:
            superseded = {
                snapshot.supersedes
                for snapshot in target_visible
                if snapshot.supersedes is not None
            }
            heads = tuple(
                snapshot for snapshot in target_visible if snapshot.snapshot_id not in superseded
            )
            if len(heads) == 1:
                selected = heads[0]
                resolution_proof = selected.resolution_proof
                if resolution_proof is not None:
                    coverage = resolution_proof.coverage
                    if coverage.level is ScanRunCoverageLevel.INDETERMINATE:
                        result_reason = CalendarResolutionReason.OFFICIAL_INCOMPLETE
                    elif (
                        coverage.confirmed_through is None
                        or target_date > coverage.confirmed_through
                    ):
                        result_reason = CalendarResolutionReason.OFFICIAL_HORIZON_UNCONFIRMED
                    else:
                        day = next(
                            (day for day in selected.days if day.date == target_date),
                            None,
                        )
                        if day is None:
                            result_reason = CalendarResolutionReason.OFFICIAL_INCOMPLETE
                        else:
                            result_status = (
                                CalendarResolutionStatus.TRADING
                                if day.is_trading_day
                                else CalendarResolutionStatus.NON_TRADING
                            )
                            result_reason = (
                                CalendarResolutionReason.OFFICIAL_TRADING
                                if result_status is CalendarResolutionStatus.TRADING
                                else CalendarResolutionReason.OFFICIAL_NON_TRADING
                            )
                else:
                    # CalendarCompositionReceipt is intentionally legacy
                    # candidate/audit evidence.  It cannot establish a
                    # positive result after the direct-daily proof cutover.
                    result_reason = CalendarResolutionReason.OFFICIAL_INCOMPLETE
            elif len(heads) > 1:
                result_reason = CalendarResolutionReason.OFFICIAL_CONFLICT
            else:
                result_reason = CalendarResolutionReason.OFFICIAL_LINEAGE_UNAVAILABLE

    conflict = _secondary_conflict(
        exchange=exchange,
        target_date=target_date,
        as_of=cutoff,
        official=result_status
        if selected is not None and result_status is not CalendarResolutionStatus.INDETERMINATE
        else None,
        secondary=secondary,
    )
    return CalendarResolution(
        exchange=exchange,
        date=target_date,
        as_of=cutoff,
        status=result_status,
        reason=result_reason,
        selected_version=None if selected is None else selected.snapshot_id,
        selected_available_at=None if selected is None else selected.available_at,
        secondary_conflict=conflict,
    )


__all__ = [
    "AuthoritativeCalendarError",
    "CalendarAnnualNotice",
    "CalendarCompositionProof",
    "CalendarCompositionReceipt",
    "CalendarCoverage",
    "CalendarCoverageLevel",
    "CalendarCoverageStatus",
    "CalendarDay",
    "CalendarDayReason",
    "CalendarEvidence",
    "CalendarEvidenceKind",
    "CalendarRuleProfile",
    "CalendarResolution",
    "CalendarResolutionReason",
    "CalendarResolutionStatus",
    "CalendarScope",
    "CalendarRuleCoverage",
    "CalendarScanPage",
    "CalendarScanBundle",
    "CalendarScanObservation",
    "CalendarScanRunReceipt",
    "CalendarScanRunManifestReceipt",
    "CalendarScanRunPassReceipt",
    "CalendarScanRunCoverage",
    "ScanRunCoverage",
    "ScanRunCoverageLevel",
    "calendar_scan_run_catalog_digest",
    "calendar_scan_run_manifest_member_digest",
    "calendar_scan_run_pass_member_digest",
    "calendar_scan_run_resource_id",
    "CalendarSnapshot",
    "CalendarTemporaryClosureDelta",
    "ExchangeCode",
    "OfficialAuthority",
    "SecondaryCalendarObservation",
    "SecondaryConflictEvidence",
    "SnapshotTerminal",
    "apply_temporary_closure",
    "build_authoritative_snapshot",
    "compose_direct_daily_snapshot",
    "compose_official_calendar",
    "expected_calendar_dates",
    "resolve",
]
