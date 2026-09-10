"""Conservative, immutable calendar-quality assessment primitives.

The V3 SSE source contains only explicitly published closure rows and the V4
SZSE source contains a daily projection with a bounded confirmation horizon.
Neither shape is allowed to silently become a full-year trading calendar here.
This module therefore accepts already-validated source evidence, derives only
facts that are present in that evidence, and emits append-only assessment and
alert values for the persistence adapter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from re import fullmatch
from typing import Final, Literal, cast
from uuid import UUID, uuid5


class CalendarQualityError(ValueError):
    """Raised when quality evidence cannot be interpreted safely."""


class CalendarQualitySourceKind(StrEnum):
    """Evidence shapes accepted by the quality projection."""

    SPARSE = "SPARSE"
    OFFICIAL = "OFFICIAL"
    SECONDARY = "SECONDARY"


class QualityCoverageLevel(StrEnum):
    """Coverage declaration copied from an immutable source proof."""

    UNKNOWN = "UNKNOWN"
    INDETERMINATE = "INDETERMINATE"
    CONFIRMED_HORIZON = "CONFIRMED_HORIZON"
    FINAL_YEAR = "FINAL_YEAR"


class QualityAssessmentStatus(StrEnum):
    """Conservative outcome of one quality projection operation."""

    COMPLETE = "COMPLETE"
    INDETERMINATE = "INDETERMINATE"
    MISSING_COVERAGE = "MISSING_COVERAGE"
    CONFLICT = "CONFLICT"


class QualityAlertKind(StrEnum):
    """Append-only alert categories."""

    MISSING_COVERAGE = "MISSING_COVERAGE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    TEMPORARY_CLOSURE = "TEMPORARY_CLOSURE"


QualityDecision = Literal["TRADING", "NON_TRADING", "REVIEW"]
_EXCHANGES: Final = frozenset({"SH", "SZ", "BJ"})
_REASONS: Final = frozenset({"WEEKEND", "PUBLIC_HOLIDAY", "TEMPORARY_CLOSURE", "SPECIAL"})
_DIGEST_RE: Final = r"[0-9a-f]{64}"
_OPAQUE_REF_RE: Final = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}"
_QUALITY_NAMESPACE: Final = UUID("f1e0d3c2-b1a0-4938-8f7e-6d5c4b3a2910")


def _error() -> CalendarQualityError:
    return CalendarQualityError("calendar quality evidence is invalid")


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise _error()
    try:
        return value.astimezone(UTC)
    except Exception:
        raise _error() from None


def _date(value: object) -> date:
    if type(value) is not date:
        raise _error()
    return value


def _uuid(value: object) -> UUID:
    if type(value) is not UUID:
        raise _error()
    return value


def _text(value: object, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value) or "\x00" in value:
        raise _error()
    return value


def _digest(value: object) -> str:
    if type(value) is not str or fullmatch(_DIGEST_RE, value) is None:
        raise _error()
    return value


def _opaque_ref(value: object) -> str:
    if type(value) is not str or fullmatch(_OPAQUE_REF_RE, value) is None:
        raise _error()
    return value


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else value


def _enum[T: StrEnum](value: object, enum_type: type[T]) -> T:
    try:
        if type(value) is enum_type:
            return cast(T, value)
        return enum_type(cast(str, value))
    except (TypeError, ValueError):
        raise _error() from None


def _expected_dates(year: int) -> tuple[date, ...]:
    first = date(year, 1, 1)
    last = date(year + 1, 1, 1) if year < 9999 else date.max
    count = (last - first).days + 1 if year == 9999 else (last - first).days
    return tuple(date.fromordinal(first.toordinal() + index) for index in range(count))


@dataclass(frozen=True, slots=True)
class CalendarQualityDay:
    """One source-provided daily status; absence has no meaning."""

    calendar_date: date
    is_trading_day: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        _date(self.calendar_date)
        if type(self.is_trading_day) is not bool:
            raise _error()
        if self.reason is not None:
            reason = _text(self.reason)
            if reason not in _REASONS:
                raise _error()
            if self.is_trading_day:
                raise _error()


@dataclass(frozen=True, slots=True)
class CalendarQualityEvidenceLink:
    """An inseparable source reference and artifact digest pair."""

    source_id: UUID
    evidence_ref: str
    artifact_sha256: str

    def __post_init__(self) -> None:
        _uuid(self.source_id)
        _opaque_ref(self.evidence_ref)
        _digest(self.artifact_sha256)


@dataclass(frozen=True, slots=True)
class CalendarClosureEvidence:
    """Independent classification evidence for a temporary closure.

    V4's generic ``SPECIAL`` day reason is intentionally not interpreted as a
    temporary closure.  Callers must provide this separate, opaque evidence
    reference and digest when such a classification is known.
    """

    source_id: UUID
    closure_date: date
    evidence_ref: str
    artifact_sha256: str
    captured_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        source_id = _uuid(self.source_id)
        closure_date = _date(self.closure_date)
        evidence_ref = _opaque_ref(self.evidence_ref)
        artifact_sha256 = _digest(self.artifact_sha256)
        captured_at = _utc(self.captured_at)
        available_at = _utc(self.available_at)
        if captured_at > available_at:
            raise _error()
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "closure_date", closure_date)
        object.__setattr__(self, "evidence_ref", evidence_ref)
        object.__setattr__(self, "artifact_sha256", artifact_sha256)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "available_at", available_at)


@dataclass(frozen=True, slots=True)
class CalendarQualitySource:
    """A bounded, already-authenticated source projection input."""

    source_id: UUID
    source_kind: CalendarQualitySourceKind | str
    source_name: str
    exchange: str
    year: int
    captured_at: datetime
    available_at: datetime
    coverage_level: QualityCoverageLevel | str
    confirmed_through: date | None
    source_fingerprint: str
    days: Sequence[CalendarQualityDay] = ()
    evidence_links: Sequence[CalendarQualityEvidenceLink] = ()
    closures: Sequence[CalendarClosureEvidence] = ()

    def __post_init__(self) -> None:
        source_id = _uuid(self.source_id)
        source_kind = _enum(self.source_kind, CalendarQualitySourceKind)
        source_name = _text(self.source_name)
        exchange = _text(self.exchange)
        year = self.year
        if exchange not in _EXCHANGES or type(year) is not int or not 1 <= year <= 9999:
            raise _error()
        captured_at = _utc(self.captured_at)
        available_at = _utc(self.available_at)
        if captured_at > available_at:
            raise _error()
        coverage_level = _enum(self.coverage_level, QualityCoverageLevel)
        source_fingerprint = _digest(self.source_fingerprint)
        confirmed_through = (
            None if self.confirmed_through is None else _date(self.confirmed_through)
        )
        if confirmed_through is not None and confirmed_through.year != year:
            raise _error()
        if coverage_level in {QualityCoverageLevel.UNKNOWN, QualityCoverageLevel.INDETERMINATE}:
            if confirmed_through is not None:
                raise _error()
        elif confirmed_through is None or (
            coverage_level is QualityCoverageLevel.FINAL_YEAR
            and confirmed_through != date(year, 12, 31)
        ):
            raise _error()
        if source_kind is CalendarQualitySourceKind.SPARSE and coverage_level not in {
            QualityCoverageLevel.UNKNOWN,
            QualityCoverageLevel.INDETERMINATE,
        }:
            raise _error()

        try:
            copied_days = tuple(self.days)
            copied_evidence_links = tuple(self.evidence_links)
            copied_closures = tuple(self.closures)
        except Exception:
            raise _error() from None
        if not copied_evidence_links:
            raise _error()
        if any(type(link) is not CalendarQualityEvidenceLink for link in copied_evidence_links):
            raise _error()
        if any(link.source_id != source_id for link in copied_evidence_links):
            raise _error()
        evidence_keys = tuple(
            (link.evidence_ref, link.artifact_sha256) for link in copied_evidence_links
        )
        if len({item[0] for item in evidence_keys}) != len(evidence_keys):
            raise _error()
        seen_dates: set[date] = set()
        for day in copied_days:
            if type(day) is not CalendarQualityDay or day.calendar_date.year != year:
                raise _error()
            if day.calendar_date in seen_dates:
                raise _error()
            seen_dates.add(day.calendar_date)
        if coverage_level is QualityCoverageLevel.FINAL_YEAR:
            expected = _expected_dates(year)
            if tuple(day.calendar_date for day in copied_days) != expected:
                raise _error()
        for closure in copied_closures:
            if type(closure) is not CalendarClosureEvidence:
                raise _error()
            if closure.source_id != source_id or closure.closure_date.year != year:
                raise _error()
            if closure.available_at > available_at:
                raise _error()
        closure_keys = tuple((item.closure_date, item.evidence_ref) for item in copied_closures)
        if len(set(closure_keys)) != len(closure_keys):
            raise _error()
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "coverage_level", coverage_level)
        object.__setattr__(self, "confirmed_through", confirmed_through)
        object.__setattr__(self, "source_fingerprint", source_fingerprint)
        object.__setattr__(self, "days", copied_days)
        object.__setattr__(self, "evidence_links", copied_evidence_links)
        object.__setattr__(self, "closures", copied_closures)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        """Compatibility view; callers must persist ``evidence_links``."""

        return tuple(link.evidence_ref for link in self.evidence_links)

    @property
    def content_fingerprint(self) -> str:
        """Return the content identity without any caller operation id."""

        payload = {
            "source_id": str(self.source_id),
            "source_kind": _enum_value(self.source_kind),
            "source_name": self.source_name,
            "exchange": self.exchange,
            "year": self.year,
            "captured_at": self.captured_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "coverage_level": _enum_value(self.coverage_level),
            "source_fingerprint": self.source_fingerprint,
            "confirmed_through": (
                None if self.confirmed_through is None else self.confirmed_through.isoformat()
            ),
            "days": [
                {
                    "date": day.calendar_date.isoformat(),
                    "trading": day.is_trading_day,
                    "reason": day.reason,
                }
                for day in self.days
            ],
            "evidence_links": [
                {
                    "ref": link.evidence_ref,
                    "digest": link.artifact_sha256,
                }
                for link in self.evidence_links
            ],
            "closures": [
                {
                    "date": closure.closure_date.isoformat(),
                    "ref": closure.evidence_ref,
                    "digest": closure.artifact_sha256,
                    "captured_at": closure.captured_at.isoformat(),
                    "available_at": closure.available_at.isoformat(),
                }
                for closure in self.closures
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CalendarQualityAlert:
    """One deterministic append-only alert."""

    alert_id: UUID
    kind: QualityAlertKind | str
    calendar_date: date | None
    detail_code: str
    evidence_links: tuple[CalendarQualityEvidenceLink, ...]
    detected_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        alert_id = _uuid(self.alert_id)
        kind = _enum(self.kind, QualityAlertKind)
        calendar_date = None if self.calendar_date is None else _date(self.calendar_date)
        detail_code = _text(self.detail_code)
        evidence_links = tuple(self.evidence_links)
        if kind is not QualityAlertKind.MISSING_COVERAGE and not evidence_links:
            raise _error()
        if any(type(link) is not CalendarQualityEvidenceLink for link in evidence_links):
            raise _error()
        if len({(link.source_id, link.evidence_ref) for link in evidence_links}) != len(
            evidence_links
        ):
            raise _error()
        detected_at = _utc(self.detected_at)
        available_at = _utc(self.available_at)
        if detected_at > available_at:
            raise _error()
        object.__setattr__(self, "alert_id", alert_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "calendar_date", calendar_date)
        object.__setattr__(self, "detail_code", detail_code)
        object.__setattr__(self, "evidence_links", evidence_links)
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "available_at", available_at)

    @property
    def source_ids(self) -> tuple[UUID, ...]:
        return tuple(link.source_id for link in self.evidence_links)

    @property
    def evidence_refs(self) -> tuple[str, ...]:
        return tuple(link.evidence_ref for link in self.evidence_links)


@dataclass(frozen=True, slots=True)
class CalendarQualityAssessment:
    """An immutable assessment and its derived append-only alerts."""

    assessment_id: UUID
    operation_id: str
    exchange: str
    year: int
    detected_at: datetime
    available_at: datetime
    status: QualityAssessmentStatus | str
    coverage_level: QualityCoverageLevel | str
    confirmed_through: date | None
    source_ids: tuple[UUID, ...]
    missing_dates: tuple[date, ...]
    confirmed_days: tuple[CalendarQualityDay, ...]
    alerts: tuple[CalendarQualityAlert, ...]
    content_fingerprint: str
    sources: tuple[CalendarQualitySource, ...] = ()

    def __post_init__(self) -> None:
        _uuid(self.assessment_id)
        operation_id = _text(self.operation_id)
        exchange = _text(self.exchange)
        if exchange not in _EXCHANGES or type(self.year) is not int or not 1 <= self.year <= 9999:
            raise _error()
        detected_at = _utc(self.detected_at)
        available_at = _utc(self.available_at)
        if detected_at > available_at:
            raise _error()
        status = _enum(self.status, QualityAssessmentStatus)
        coverage_level = _enum(self.coverage_level, QualityCoverageLevel)
        confirmed_through = (
            None if self.confirmed_through is None else _date(self.confirmed_through)
        )
        if confirmed_through is not None and confirmed_through.year != self.year:
            raise _error()
        if coverage_level in {QualityCoverageLevel.UNKNOWN, QualityCoverageLevel.INDETERMINATE}:
            if confirmed_through is not None:
                raise _error()
        elif confirmed_through is None or (
            coverage_level is QualityCoverageLevel.FINAL_YEAR
            and confirmed_through != date(self.year, 12, 31)
        ):
            raise _error()
        source_ids = tuple(self.source_ids)
        if not source_ids and status is not QualityAssessmentStatus.MISSING_COVERAGE:
            raise _error()
        if len(set(source_ids)) != len(source_ids):
            raise _error()
        if any(type(source_id) is not UUID for source_id in source_ids):
            raise _error()
        missing_dates = tuple(self.missing_dates)
        if len(set(missing_dates)) != len(missing_dates) or any(
            type(item) is not date or item.year != self.year for item in missing_dates
        ):
            raise _error()
        confirmed_days = tuple(self.confirmed_days)
        if any(
            type(day) is not CalendarQualityDay or day.calendar_date.year != self.year
            for day in confirmed_days
        ):
            raise _error()
        alerts = tuple(self.alerts)
        if any(type(alert) is not CalendarQualityAlert for alert in alerts):
            raise _error()
        if any(alert.available_at > available_at for alert in alerts):
            raise _error()
        sources = tuple(self.sources)
        if any(type(source) is not CalendarQualitySource for source in sources):
            raise _error()
        if sources and tuple(source.source_id for source in sources) != source_ids:
            raise _error()
        if any(
            source.exchange != exchange
            or source.year != self.year
            or source.available_at > available_at
            for source in sources
        ):
            raise _error()
        content_fingerprint = _digest(self.content_fingerprint)
        object.__setattr__(self, "operation_id", operation_id)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "coverage_level", coverage_level)
        object.__setattr__(self, "confirmed_through", confirmed_through)
        object.__setattr__(
            self, "source_ids", tuple(sorted(source_ids, key=lambda value: value.bytes))
        )
        object.__setattr__(self, "missing_dates", tuple(sorted(missing_dates)))
        object.__setattr__(self, "confirmed_days", confirmed_days)
        object.__setattr__(self, "alerts", alerts)
        object.__setattr__(self, "content_fingerprint", content_fingerprint)
        object.__setattr__(self, "sources", sources)

    @property
    def operation_key_hash(self) -> bytes:
        """Hash used by the database idempotency key; plaintext is never stored."""

        return hashlib.sha256(self.operation_id.encode("utf-8")).digest()


@dataclass(frozen=True, slots=True)
class CalendarQualityOverlay:
    """An audited manual decision bound to one source-backed assessment."""

    overlay_id: UUID
    operation_id: str
    assessment_id: UUID
    source_id: UUID
    calendar_date: date
    decision: QualityDecision
    reason_code: str
    note: str
    author: str
    available_at: datetime

    def __post_init__(self) -> None:
        _uuid(self.overlay_id)
        _text(self.operation_id)
        _uuid(self.assessment_id)
        _uuid(self.source_id)
        _date(self.calendar_date)
        if self.decision not in {"TRADING", "NON_TRADING", "REVIEW"}:
            raise _error()
        _text(self.reason_code)
        _text(self.note, allow_empty=True)
        _text(self.author)
        _utc(self.available_at)

    @property
    def operation_key_hash(self) -> bytes:
        return hashlib.sha256(self.operation_id.encode("utf-8")).digest()


def _alert_id(
    assessment_id: UUID,
    kind: QualityAlertKind,
    calendar_date: date | None,
    evidence_links: Iterable[CalendarQualityEvidenceLink],
) -> UUID:
    link_part = ",".join(
        f"{link.source_id}:{link.evidence_ref}:{link.artifact_sha256}" for link in evidence_links
    )
    date_part = "" if calendar_date is None else calendar_date.isoformat()
    return uuid5(
        _QUALITY_NAMESPACE,
        f"alert:{assessment_id}:{kind.value}:{date_part}:{link_part}",
    )


def _make_alert(
    *,
    assessment_id: UUID,
    kind: QualityAlertKind,
    calendar_date: date | None,
    detail_code: str,
    sources: Sequence[CalendarQualitySource],
    detected_at: datetime,
) -> CalendarQualityAlert:
    evidence_links = tuple(link for source in sources for link in source.evidence_links)
    return CalendarQualityAlert(
        alert_id=_alert_id(assessment_id, kind, calendar_date, evidence_links),
        kind=kind,
        calendar_date=calendar_date,
        detail_code=detail_code,
        evidence_links=evidence_links,
        detected_at=detected_at,
        available_at=detected_at,
    )


def _observations_for_date(
    sources: Sequence[CalendarQualitySource],
    target: date,
) -> tuple[tuple[CalendarQualitySource, CalendarQualityDay], ...]:
    observations: list[tuple[CalendarQualitySource, CalendarQualityDay]] = []
    for source in sources:
        if source.source_kind is CalendarQualitySourceKind.SPARSE:
            days = tuple(
                day for day in source.days if day.calendar_date == target and not day.is_trading_day
            )
        else:
            if source.confirmed_through is None or target > source.confirmed_through:
                continue
            days = tuple(day for day in source.days if day.calendar_date == target)
        observations.extend((source, day) for day in days)
    return tuple(observations)


def assess_calendar_quality(
    *,
    operation_id: str,
    exchange: str,
    year: int,
    detected_at: datetime,
    sources: Iterable[CalendarQualitySource],
) -> CalendarQualityAssessment:
    """Build a conservative quality assessment from source evidence.

    A sparse source can produce explicitly listed closure alerts, but never a
    missing-date list.  A bounded official horizon produces missing coverage
    only inside the supplied horizon.  An absent source (for example BJ) is
    represented by one scope-level missing-coverage alert without synthesizing
    per-date rows or guessing a trading/non-trading status for any date.
    """

    operation_id = _text(operation_id)
    exchange = _text(exchange)
    if exchange not in _EXCHANGES or type(year) is not int or not 1 <= year <= 9999:
        raise _error()
    detected_at = _utc(detected_at)
    try:
        copied_sources = tuple(sources)
    except Exception:
        raise _error() from None
    if any(type(source) is not CalendarQualitySource for source in copied_sources):
        raise _error()
    if any(source.exchange != exchange or source.year != year for source in copied_sources):
        raise _error()
    if any(source.available_at > detected_at for source in copied_sources):
        raise _error()
    copied_sources = tuple(sorted(copied_sources, key=lambda source: source.source_id.bytes))
    if len({source.source_id for source in copied_sources}) != len(copied_sources):
        raise _error()

    assessment_id = uuid5(_QUALITY_NAMESPACE, f"assessment:{operation_id}")
    official_sources = tuple(
        source
        for source in copied_sources
        if source.source_kind is CalendarQualitySourceKind.OFFICIAL
    )
    sparse_sources = tuple(
        source
        for source in copied_sources
        if source.source_kind is CalendarQualitySourceKind.SPARSE
    )
    accepted_official = tuple(
        source
        for source in official_sources
        if source.coverage_level
        in {
            QualityCoverageLevel.CONFIRMED_HORIZON,
            QualityCoverageLevel.FINAL_YEAR,
        }
    )
    complete_official = tuple(
        source
        for source in accepted_official
        if source.coverage_level is QualityCoverageLevel.FINAL_YEAR
    )

    missing_dates: tuple[date, ...]
    confirmed_through: date | None
    coverage_level: QualityCoverageLevel
    confirmed_days: tuple[CalendarQualityDay, ...]
    official_conflict_dates: set[date] = set()
    if accepted_official:
        horizons = tuple(
            source.confirmed_through for source in accepted_official if source.confirmed_through
        )
        confirmed_through = max(horizons) if horizons else None
        coverage_level = (
            QualityCoverageLevel.FINAL_YEAR
            if complete_official
            else QualityCoverageLevel.CONFIRMED_HORIZON
            if confirmed_through
            else QualityCoverageLevel.INDETERMINATE
        )
        aggregate_missing: list[date] = []
        aggregate_days: list[CalendarQualityDay] = []
        if confirmed_through is not None:
            for target in _expected_dates(year):
                if target > confirmed_through:
                    break
                observations = _observations_for_date(accepted_official, target)
                statuses = {day.is_trading_day for _source, day in observations}
                if len(statuses) > 1:
                    official_conflict_dates.add(target)
                elif not observations:
                    aggregate_missing.append(target)
                else:
                    _selected_source, selected_day = max(
                        observations,
                        key=lambda item: (item[0].available_at, item[0].source_id.bytes),
                    )
                    aggregate_days.append(selected_day)
        missing_dates = tuple(aggregate_missing)
        confirmed_days = tuple(aggregate_days)
    elif sparse_sources:
        # Sparse holiday announcements are useful closure evidence only.
        coverage_level = QualityCoverageLevel.UNKNOWN
        confirmed_through = None
        missing_dates = ()
        confirmed_days = ()
    else:
        coverage_level = QualityCoverageLevel.INDETERMINATE
        confirmed_through = None
        missing_dates = ()
        confirmed_days = ()

    if complete_official:
        status = QualityAssessmentStatus.COMPLETE
    elif accepted_official or not sparse_sources:
        status = QualityAssessmentStatus.MISSING_COVERAGE
    else:
        status = QualityAssessmentStatus.INDETERMINATE
    available_at = detected_at

    alerts: list[CalendarQualityAlert] = []
    has_scope_gap = not accepted_official or (
        confirmed_through is not None and confirmed_through < date(year, 12, 31)
    )
    if has_scope_gap:
        alerts.append(
            _make_alert(
                assessment_id=assessment_id,
                kind=QualityAlertKind.MISSING_COVERAGE,
                calendar_date=None,
                detail_code="DATE_NOT_CONFIRMED",
                sources=accepted_official,
                detected_at=detected_at,
            )
        )
    for target in missing_dates:
        contributing = accepted_official
        alerts.append(
            _make_alert(
                assessment_id=assessment_id,
                kind=QualityAlertKind.MISSING_COVERAGE,
                calendar_date=target,
                detail_code="DATE_NOT_CONFIRMED",
                sources=contributing,
                detected_at=detected_at,
            )
        )

    for source in copied_sources:
        for closure in source.closures:
            closure_source = CalendarQualitySource(
                source_id=source.source_id,
                source_kind=source.source_kind,
                source_name=source.source_name,
                exchange=source.exchange,
                year=source.year,
                captured_at=source.captured_at,
                available_at=source.available_at,
                coverage_level=source.coverage_level,
                confirmed_through=source.confirmed_through,
                source_fingerprint=source.source_fingerprint,
                days=(),
                evidence_links=(
                    CalendarQualityEvidenceLink(
                        source_id=source.source_id,
                        evidence_ref=closure.evidence_ref,
                        artifact_sha256=closure.artifact_sha256,
                    ),
                ),
                closures=(),
            )
            alerts.append(
                _make_alert(
                    assessment_id=assessment_id,
                    kind=QualityAlertKind.TEMPORARY_CLOSURE,
                    calendar_date=closure.closure_date,
                    detail_code="EXPLICIT_CLOSURE_EVIDENCE",
                    sources=(closure_source,),
                    detected_at=detected_at,
                )
            )

    candidate_dates = {
        day.calendar_date
        for source in copied_sources
        for day in source.days
        if source.source_kind is not CalendarQualitySourceKind.SPARSE
        and source.confirmed_through is not None
        and day.calendar_date <= source.confirmed_through
    }
    candidate_dates.update(
        day.calendar_date
        for source in sparse_sources
        for day in source.days
        if not day.is_trading_day
    )
    for target in sorted(candidate_dates):
        observations = _observations_for_date(copied_sources, target)
        statuses = {day.is_trading_day for _source, day in observations}
        if len(statuses) > 1:
            involved = tuple(source for source, _day in observations)
            alerts.append(
                _make_alert(
                    assessment_id=assessment_id,
                    kind=QualityAlertKind.SOURCE_CONFLICT,
                    calendar_date=target,
                    detail_code="DAY_STATUS_DISAGREEMENT",
                    sources=involved,
                    detected_at=detected_at,
                )
            )

    if any(alert.kind is QualityAlertKind.SOURCE_CONFLICT for alert in alerts):
        status = QualityAssessmentStatus.CONFLICT

    ordered_alerts = tuple(sorted(alerts, key=lambda alert: alert.alert_id.bytes))
    fingerprint_payload = {
        "exchange": exchange,
        "year": year,
        "detected_at": detected_at.isoformat(),
        "available_at": available_at.isoformat(),
        "sources": [source.content_fingerprint for source in copied_sources],
        "status": status.value,
        "coverage_level": coverage_level.value,
        "confirmed_through": (None if confirmed_through is None else confirmed_through.isoformat()),
        "missing_dates": [item.isoformat() for item in missing_dates],
        "alerts": [str(alert.alert_id) for alert in ordered_alerts],
    }
    content = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    content_fingerprint = hashlib.sha256(content).hexdigest()
    return CalendarQualityAssessment(
        assessment_id=assessment_id,
        operation_id=operation_id,
        exchange=exchange,
        year=year,
        detected_at=detected_at,
        available_at=available_at,
        status=status,
        coverage_level=coverage_level,
        confirmed_through=confirmed_through,
        source_ids=tuple(source.source_id for source in copied_sources),
        missing_dates=missing_dates,
        confirmed_days=confirmed_days,
        alerts=ordered_alerts,
        content_fingerprint=content_fingerprint,
        sources=copied_sources,
    )


# Readable aliases for callers that use projection terminology.
project_calendar_quality = assess_calendar_quality
build_calendar_quality_assessment = assess_calendar_quality


__all__ = [
    "CalendarClosureEvidence",
    "CalendarQualityAlert",
    "CalendarQualityAssessment",
    "CalendarQualityDay",
    "CalendarQualityEvidenceLink",
    "CalendarQualityError",
    "CalendarQualityOverlay",
    "CalendarQualitySource",
    "CalendarQualitySourceKind",
    "QualityAlertKind",
    "QualityAssessmentStatus",
    "QualityCoverageLevel",
    "QualityDecision",
    "assess_calendar_quality",
    "build_calendar_quality_assessment",
    "project_calendar_quality",
]
