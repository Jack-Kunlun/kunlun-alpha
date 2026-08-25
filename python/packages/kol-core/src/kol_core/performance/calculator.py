"""Point-in-time KOL Claim performance with immutable revision provenance."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from kol_core.models import ClaimDirection, KolClaim, ReviewStatus

KOL_PERFORMANCE_SCHEMA_VERSION = "kol-claim-performance-v1"
KOL_PERFORMANCE_ALGORITHM_VERSION = "kol-claim-performance-v1"
KOL_PERFORMANCE_POLICY_VERSION = "kol-claim-performance-policy-v1"

_INSTRUMENT = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_MARKETS = frozenset({"SH", "SZ", "BJ"})
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _aware(value: datetime, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: str, name: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _decimal(value: Decimal, name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or (positive and value <= 0):
        raise ValueError(f"{name} must be finite{' and positive' if positive else ''}")
    return value


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


class ClaimPerformanceStatus(StrEnum):
    MATURE = "MATURE"
    PENDING = "PENDING"
    EXCLUDED = "EXCLUDED"


class ClaimPerformanceExclusionReason(StrEnum):
    NOT_APPROVED = "not_approved"
    NEUTRAL_DIRECTION = "neutral_direction"
    WAITING_FOR_ENTRY = "waiting_for_entry"
    MISSING_PRICE = "missing_price"
    INSUFFICIENT_HORIZON = "insufficient_horizon"
    SEMANTICALLY_UNCHANGED_REVISION = "semantically_unchanged_revision"


class ClaimPerformanceInputError(ValueError):
    """Fail-closed error for incomplete or ambiguous immutable input history."""


@dataclass(frozen=True, slots=True)
class TradablePriceObservation:
    instrument_id: str
    trade_date: date
    event_time: datetime
    price: Decimal
    available_time: datetime
    suspended: bool
    source: str
    source_version: str
    data_version: str
    raw_capture_id: str
    revision_id: str
    replacement_version: int = 1
    interval: str = "DAILY"
    session: str = "CONTINUOUS"
    adjustment: str = "FORWARD_ADJUSTED"

    def __post_init__(self) -> None:
        if type(self.instrument_id) is not str or _INSTRUMENT.fullmatch(self.instrument_id) is None:
            raise ValueError("instrument_id must use canonical unified code")
        if type(self.trade_date) is not date:
            raise TypeError("trade_date must be date")
        event_time = _aware(self.event_time, "event_time")
        available_time = _aware(self.available_time, "available_time")
        if available_time < event_time:
            raise ValueError("available_time must not precede event_time")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_time", available_time)
        _decimal(self.price, "price", positive=True)
        if type(self.suspended) is not bool:
            raise TypeError("suspended must be bool")
        for field_name in (
            "source",
            "source_version",
            "data_version",
            "raw_capture_id",
            "revision_id",
            "interval",
            "session",
            "adjustment",
        ):
            _text(getattr(self, field_name), field_name)
        if type(self.replacement_version) is not int or self.replacement_version < 1:
            raise ValueError("replacement_version must be a positive integer")

    @property
    def integrity_tuple(self) -> tuple[object, ...]:
        return (
            self.instrument_id,
            self.trade_date,
            self.event_time,
            self.price,
            self.available_time,
            self.suspended,
            self.source,
            self.source_version,
            self.data_version,
            self.raw_capture_id,
            self.revision_id,
            self.replacement_version,
            self.interval,
            self.session,
            self.adjustment,
        )


@dataclass(frozen=True, slots=True)
class TradingSession:
    trade_date: date
    close_time: datetime

    def __post_init__(self) -> None:
        if type(self.trade_date) is not date:
            raise TypeError("trade_date must be date")
        close_time = _aware(self.close_time, "close_time")
        if close_time.astimezone(_SHANGHAI).date() != self.trade_date:
            raise ValueError("trade_date must match close_time in Asia/Shanghai")
        object.__setattr__(self, "close_time", close_time)


@dataclass(frozen=True, slots=True)
class TradingCalendarSnapshot:
    market: str
    coverage_start_time: datetime
    coverage_end_time: datetime
    sessions: tuple[TradingSession, ...]
    available_time: datetime
    source: str
    source_version: str
    data_version: str
    snapshot_id: str
    replacement_version: int = 1

    def __post_init__(self) -> None:
        if self.market not in _MARKETS:
            raise ValueError("market must be SH, SZ, or BJ")
        coverage_start = _aware(self.coverage_start_time, "coverage_start_time")
        coverage_end = _aware(self.coverage_end_time, "coverage_end_time")
        available_time = _aware(self.available_time, "available_time")
        if coverage_end < coverage_start:
            raise ValueError("calendar coverage_end_time must not precede coverage_start_time")
        if type(self.sessions) is not tuple or any(
            type(item) is not TradingSession for item in self.sessions
        ):
            raise TypeError("sessions must be a tuple of TradingSession values")
        if tuple(sorted(self.sessions, key=lambda item: item.close_time)) != self.sessions:
            raise ValueError("calendar sessions must be sorted by close_time")
        if len({item.trade_date for item in self.sessions}) != len(self.sessions):
            raise ValueError("calendar sessions must have unique trade_date values")
        if any(
            item.close_time < coverage_start or item.close_time > coverage_end
            for item in self.sessions
        ):
            raise ValueError("calendar sessions must be inside the coverage interval")
        for field_name in ("source", "source_version", "data_version", "snapshot_id"):
            _text(getattr(self, field_name), field_name)
        if type(self.replacement_version) is not int or self.replacement_version < 1:
            raise ValueError("calendar replacement_version must be a positive integer")
        object.__setattr__(self, "coverage_start_time", coverage_start)
        object.__setattr__(self, "coverage_end_time", coverage_end)
        object.__setattr__(self, "available_time", available_time)

    @property
    def fingerprint(self) -> str:
        payload = {
            "availableTime": self.available_time.isoformat(),
            "coverageEndTime": self.coverage_end_time.isoformat(),
            "coverageStartTime": self.coverage_start_time.isoformat(),
            "dataVersion": self.data_version,
            "market": self.market,
            "replacementVersion": self.replacement_version,
            "sessions": [
                {
                    "closeTime": item.close_time.isoformat(),
                    "tradeDate": item.trade_date.isoformat(),
                }
                for item in self.sessions
            ],
            "snapshotId": self.snapshot_id,
            "source": self.source,
            "sourceVersion": self.source_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@dataclass(frozen=True, slots=True)
class ClaimPerformancePolicy:
    horizons: tuple[int, ...] = (1, 3, 5)
    interval: str = "DAILY"
    session: str = "CONTINUOUS"
    adjustment: str = "FORWARD_ADJUSTED"
    return_cap: Decimal = Decimal("0.20")
    algorithm_version: str = KOL_PERFORMANCE_ALGORITHM_VERSION
    policy_version: str = KOL_PERFORMANCE_POLICY_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.horizons) is not tuple
            or not self.horizons
            or any(type(item) is not int or item < 1 for item in self.horizons)
            or tuple(sorted(set(self.horizons))) != self.horizons
        ):
            raise ValueError("horizons must be a sorted unique tuple of positive integers")
        for field_name in (
            "interval",
            "session",
            "adjustment",
            "algorithm_version",
            "policy_version",
        ):
            _text(getattr(self, field_name), field_name)
        _decimal(self.return_cap, "return_cap", positive=True)

    @property
    def fingerprint(self) -> str:
        payload = {
            "adjustment": self.adjustment,
            "algorithmVersion": self.algorithm_version,
            "horizons": list(self.horizons),
            "interval": self.interval,
            "policyVersion": self.policy_version,
            "returnCap": _decimal_text(self.return_cap),
            "session": self.session,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


_DEFAULT_CLAIM_PERFORMANCE_POLICY = ClaimPerformancePolicy()


@dataclass(frozen=True, slots=True)
class ClaimHorizonReturn:
    horizon: int
    exit_observation: TradablePriceObservation
    raw_return: Decimal
    signed_return: Decimal


@dataclass(frozen=True, slots=True)
class ClaimPerformanceSample:
    source: str
    claim_id: str
    claim_revision_id: str
    previous_revision_id: str | None
    content_id: str
    content_version: str
    kol_id: str
    instrument_id: str
    direction: ClaimDirection
    confidence_bps: int
    review_status: ReviewStatus
    statement_fingerprint: str
    evidence_revision_ids: tuple[str, ...]
    publish_time: datetime
    claim_available_time: datetime
    active_at_decision: bool
    withdrawn_at: datetime | None
    calendar_snapshot_id: str | None
    status: ClaimPerformanceStatus
    exclusion_reason: ClaimPerformanceExclusionReason | None
    entry_observation: TradablePriceObservation | None
    observed_price_path: tuple[TradablePriceObservation, ...]
    skipped_suspensions: tuple[TradablePriceObservation, ...]
    missing_trade_dates: tuple[date, ...]
    horizon_returns: tuple[ClaimHorizonReturn, ...]
    logical_available_time: datetime


@dataclass(frozen=True, slots=True)
class ClaimPerformanceResult:
    schema_version: str
    decision_time: datetime
    samples: tuple[ClaimPerformanceSample, ...]
    data_cutoff_time: datetime | None
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str
    calendar_snapshots: tuple[TradingCalendarSnapshot, ...]


@dataclass(frozen=True, slots=True)
class _ClaimLineage:
    key: tuple[str, str]
    revisions: tuple[KolClaim, ...]


def _effective_time(claim: KolClaim) -> datetime:
    if not claim.deleted:
        return claim.available_time
    if claim.deleted_at is None:
        raise ClaimPerformanceInputError("deleted claim must have deleted_at")
    return claim.deleted_at


def _visible_claims(
    claims: Iterable[KolClaim],
    decision_time: datetime,
) -> tuple[KolClaim, ...]:
    visible: list[KolClaim] = []
    for claim in claims:
        if type(claim) is not KolClaim:
            raise TypeError("claims must contain KolClaim instances")
        if _effective_time(claim) <= decision_time:
            visible.append(claim)
    return tuple(visible)


def _visible_calendars(
    snapshots: Iterable[TradingCalendarSnapshot],
    decision_time: datetime,
) -> dict[str, TradingCalendarSnapshot]:
    grouped: dict[str, list[TradingCalendarSnapshot]] = {}
    for snapshot in snapshots:
        if type(snapshot) is not TradingCalendarSnapshot:
            raise TypeError("trading calendars must contain TradingCalendarSnapshot values")
        if snapshot.available_time > decision_time:
            continue
        grouped.setdefault(snapshot.market, []).append(snapshot)

    selected: dict[str, TradingCalendarSnapshot] = {}
    for market, versions in grouped.items():
        series_identities = {(item.source, item.source_version) for item in versions}
        if len(series_identities) != 1:
            raise ClaimPerformanceInputError(
                f"multiple calendar series at the PIT cutoff for market {market!r}"
            )
        versions.sort(
            key=lambda item: (
                item.replacement_version,
                item.available_time,
                item.snapshot_id,
            )
        )
        latest = versions[-1]
        peers = [
            item for item in versions if item.replacement_version == latest.replacement_version
        ]
        if len(peers) > 1:
            raise ClaimPerformanceInputError(
                f"calendar replacement is ambiguous for market {market!r}"
            )
        selected[market] = latest
    return selected


def _instrument_market(instrument_id: str) -> str:
    return instrument_id.rsplit(".", maxsplit=1)[1]


def _claim_lineages(claims: Iterable[KolClaim]) -> tuple[_ClaimLineage, ...]:
    groups: dict[tuple[str, str], list[KolClaim]] = {}
    for claim in claims:
        if type(claim) is not KolClaim:
            raise TypeError("claims must contain KolClaim instances")
        groups.setdefault((claim.source, claim.claim_id), []).append(claim)

    lineages: list[_ClaimLineage] = []
    for key, entries in groups.items():
        by_revision: dict[str, KolClaim] = {}
        children: dict[str, list[KolClaim]] = {}
        for entry in entries:
            if entry.revision_id in by_revision:
                raise ClaimPerformanceInputError(f"duplicate claim revision {entry.revision_id!r}")
            by_revision[entry.revision_id] = entry
        roots = [entry for entry in entries if entry.previous_revision_id is None]
        if len(roots) != 1:
            raise ClaimPerformanceInputError(f"claim lineage {key!r} must have exactly one root")
        for entry in entries:
            previous = entry.previous_revision_id
            if previous is None:
                continue
            predecessor = by_revision.get(previous)
            if predecessor is None:
                raise ClaimPerformanceInputError(
                    f"claim revision {entry.revision_id!r} has a missing predecessor"
                )
            if predecessor.deleted:
                raise ClaimPerformanceInputError("a deleted claim tombstone must be terminal")
            if (
                predecessor.kol_id != entry.kol_id
                or predecessor.instrument_id != entry.instrument_id
                or predecessor.content_id != entry.content_id
            ):
                raise ClaimPerformanceInputError("claim lineage identity changed across revisions")
            children.setdefault(previous, []).append(entry)
        if any(len(items) != 1 for items in children.values()):
            raise ClaimPerformanceInputError(f"claim lineage {key!r} contains a revision fork")

        ordered: list[KolClaim] = []
        current = roots[0]
        visited: set[str] = set()
        while True:
            if current.revision_id in visited:
                raise ClaimPerformanceInputError(f"claim lineage {key!r} contains a cycle")
            visited.add(current.revision_id)
            ordered.append(current)
            successors = children.get(current.revision_id, [])
            if not successors:
                break
            successor = successors[0]
            if _effective_time(successor) < _effective_time(current):
                raise ClaimPerformanceInputError("claim revision effective times must be monotonic")
            current = successor
        if len(visited) != len(entries):
            raise ClaimPerformanceInputError(f"claim lineage {key!r} is disconnected")
        lineages.append(_ClaimLineage(key=key, revisions=tuple(ordered)))
    return tuple(sorted(lineages, key=lambda item: item.key))


def _active_revision(lineage: _ClaimLineage, decision_time: datetime) -> KolClaim | None:
    head: KolClaim | None = None
    for revision in lineage.revisions:
        if _effective_time(revision) <= decision_time:
            head = revision
        else:
            break
    return None if head is None or head.deleted else head


def select_active_claims(
    claims: Iterable[KolClaim],
    decision_time: datetime,
) -> tuple[KolClaim, ...]:
    """Select one active head per complete revision lineage at a PIT cutoff."""
    decision = _aware(decision_time, "decision_time")
    selected = [
        head
        for lineage in _claim_lineages(_visible_claims(claims, decision))
        if (head := _active_revision(lineage, decision)) is not None
    ]
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                item.kol_id,
                item.instrument_id,
                item.source,
                item.claim_id,
                item.revision_id,
            ),
        )
    )


def _semantic_fingerprint(claim: KolClaim) -> str:
    payload = {
        "attribution": claim.attribution.value,
        "confidenceBps": claim.confidence_bps,
        "direction": claim.direction.value,
        "instrumentId": claim.instrument_id,
        "statement": claim.statement,
        "statementKind": claim.statement_kind.value,
        "uncertainty": claim.uncertainty.value,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _visible_prices(
    observations: Iterable[TradablePriceObservation],
    decision_time: datetime,
    policy: ClaimPerformancePolicy,
) -> dict[str, tuple[TradablePriceObservation, ...]]:
    grouped: dict[tuple[str, date], list[TradablePriceObservation]] = {}
    series_by_instrument: dict[str, set[tuple[str, ...]]] = {}
    seen_revisions: set[tuple[str, str]] = set()
    for observation in observations:
        if type(observation) is not TradablePriceObservation:
            raise TypeError("price observations must be TradablePriceObservation instances")
        if observation.available_time > decision_time:
            continue
        revision_key = (observation.source, observation.revision_id)
        if revision_key in seen_revisions:
            raise ClaimPerformanceInputError(f"duplicate price revision {revision_key!r}")
        seen_revisions.add(revision_key)
        if (
            observation.interval != policy.interval
            or observation.session != policy.session
            or observation.adjustment != policy.adjustment
        ):
            continue
        series_identity = (
            observation.source,
            observation.source_version,
            observation.data_version,
            observation.interval,
            observation.session,
            observation.adjustment,
        )
        series_by_instrument.setdefault(observation.instrument_id, set()).add(series_identity)
        grouped.setdefault((observation.instrument_id, observation.trade_date), []).append(
            observation
        )

    ambiguous_instruments = sorted(
        instrument_id
        for instrument_id, identities in series_by_instrument.items()
        if len(identities) > 1
    )
    if ambiguous_instruments:
        raise ClaimPerformanceInputError(
            f"multiple price series at the PIT cutoff for {ambiguous_instruments!r}"
        )

    selected: dict[str, list[TradablePriceObservation]] = {}
    for (instrument_id, _), versions in grouped.items():
        versions.sort(
            key=lambda item: (
                item.replacement_version,
                item.available_time,
                item.revision_id,
            )
        )
        latest = versions[-1]
        peers = [
            item for item in versions if item.replacement_version == latest.replacement_version
        ]
        if len(peers) > 1:
            raise ClaimPerformanceInputError("price replacement is ambiguous at the PIT cutoff")
        selected.setdefault(instrument_id, []).append(latest)
    return {
        instrument_id: tuple(sorted(items, key=lambda item: item.event_time))
        for instrument_id, items in selected.items()
    }


def _withdrawn_at(
    lineage: _ClaimLineage,
    revision_index: int,
    decision_time: datetime,
) -> datetime | None:
    for descendant in lineage.revisions[revision_index + 1 :]:
        if descendant.deleted and descendant.deleted_at is not None:
            return descendant.deleted_at if descendant.deleted_at <= decision_time else None
    return None


def _claim_sample(
    claim: KolClaim,
    *,
    active_at_decision: bool,
    withdrawn_at: datetime | None,
    statement_fingerprint: str,
    status: ClaimPerformanceStatus,
    reason: ClaimPerformanceExclusionReason | None,
    calendar: TradingCalendarSnapshot | None = None,
    entry: TradablePriceObservation | None = None,
    skipped_suspensions: tuple[TradablePriceObservation, ...] = (),
    missing_trade_dates: tuple[date, ...] = (),
    horizon_returns: tuple[ClaimHorizonReturn, ...] = (),
    observed_prices: tuple[TradablePriceObservation, ...] = (),
) -> ClaimPerformanceSample:
    availability_times = [claim.available_time]
    if calendar is not None:
        availability_times.append(calendar.available_time)
    availability_times.extend(item.available_time for item in observed_prices)
    if withdrawn_at is not None:
        availability_times.append(withdrawn_at)
    return ClaimPerformanceSample(
        source=claim.source,
        claim_id=claim.claim_id,
        claim_revision_id=claim.revision_id,
        previous_revision_id=claim.previous_revision_id,
        content_id=claim.content_id,
        content_version=claim.content_version,
        kol_id=claim.kol_id,
        instrument_id=claim.instrument_id,
        direction=claim.direction,
        confidence_bps=claim.confidence_bps,
        review_status=claim.review_status,
        statement_fingerprint=statement_fingerprint,
        evidence_revision_ids=tuple(sorted(item.evidence_revision_id for item in claim.evidence)),
        publish_time=claim.publish_time,
        claim_available_time=claim.available_time,
        active_at_decision=active_at_decision,
        withdrawn_at=withdrawn_at,
        calendar_snapshot_id=calendar.snapshot_id if calendar is not None else None,
        status=status,
        exclusion_reason=reason,
        entry_observation=entry,
        observed_price_path=observed_prices,
        skipped_suspensions=skipped_suspensions,
        missing_trade_dates=missing_trade_dates,
        horizon_returns=horizon_returns,
        logical_available_time=max(availability_times),
    )


def _excluded_sample(
    claim: KolClaim,
    *,
    active_at_decision: bool,
    withdrawn_at: datetime | None,
    statement_fingerprint: str,
    reason: ClaimPerformanceExclusionReason,
) -> ClaimPerformanceSample:
    return _claim_sample(
        claim,
        active_at_decision=active_at_decision,
        withdrawn_at=withdrawn_at,
        statement_fingerprint=statement_fingerprint,
        status=ClaimPerformanceStatus.EXCLUDED,
        reason=reason,
    )


def compute_claim_performance(
    claims: Iterable[KolClaim],
    prices: Iterable[TradablePriceObservation],
    trading_calendars: Iterable[TradingCalendarSnapshot],
    decision_time: datetime,
    policy: ClaimPerformancePolicy = _DEFAULT_CLAIM_PERFORMANCE_POLICY,
) -> ClaimPerformanceResult:
    """Compute immutable per-revision returns from each revision's own availability."""
    decision = _aware(decision_time, "decision_time")
    if type(policy) is not ClaimPerformancePolicy:
        raise TypeError("policy must be ClaimPerformancePolicy")
    lineages = _claim_lineages(_visible_claims(claims, decision))
    visible_prices = _visible_prices(prices, decision, policy)
    calendars = _visible_calendars(trading_calendars, decision)
    used_calendars: dict[str, TradingCalendarSnapshot] = {}
    samples: list[ClaimPerformanceSample] = []

    for lineage in lineages:
        active = _active_revision(lineage, decision)
        previous_evaluation_state: tuple[str, ReviewStatus] | None = None
        for index, claim in enumerate(lineage.revisions):
            if claim.deleted:
                continue
            statement_fingerprint = _semantic_fingerprint(claim)
            evaluation_state = (statement_fingerprint, claim.review_status)
            withdrawn_at = _withdrawn_at(lineage, index, decision)
            active_at_decision = active is not None and active.revision_id == claim.revision_id
            if previous_evaluation_state == evaluation_state:
                samples.append(
                    _excluded_sample(
                        claim,
                        active_at_decision=active_at_decision,
                        withdrawn_at=withdrawn_at,
                        statement_fingerprint=statement_fingerprint,
                        reason=ClaimPerformanceExclusionReason.SEMANTICALLY_UNCHANGED_REVISION,
                    )
                )
                continue
            previous_evaluation_state = evaluation_state
            if claim.review_status is not ReviewStatus.APPROVED:
                samples.append(
                    _excluded_sample(
                        claim,
                        active_at_decision=active_at_decision,
                        withdrawn_at=withdrawn_at,
                        statement_fingerprint=statement_fingerprint,
                        reason=ClaimPerformanceExclusionReason.NOT_APPROVED,
                    )
                )
                continue
            if claim.direction is ClaimDirection.NEUTRAL:
                samples.append(
                    _excluded_sample(
                        claim,
                        active_at_decision=active_at_decision,
                        withdrawn_at=withdrawn_at,
                        statement_fingerprint=statement_fingerprint,
                        reason=ClaimPerformanceExclusionReason.NEUTRAL_DIRECTION,
                    )
                )
                continue

            market = _instrument_market(claim.instrument_id)
            calendar = calendars.get(market)
            if calendar is None:
                raise ClaimPerformanceInputError(
                    f"missing visible trading calendar for market {market!r}"
                )
            if calendar.coverage_start_time > claim.available_time:
                raise ClaimPerformanceInputError(
                    f"calendar {calendar.snapshot_id!r} does not cover Claim availability"
                )
            if calendar.coverage_end_time < decision:
                raise ClaimPerformanceInputError(
                    f"calendar {calendar.snapshot_id!r} does not cover decision_time"
                )
            used_calendars[market] = calendar
            expected_sessions = tuple(
                item
                for item in calendar.sessions
                if claim.available_time <= item.close_time <= decision
            )
            sessions_by_date = {item.trade_date: item for item in expected_sessions}
            instrument_prices = tuple(
                item
                for item in visible_prices.get(claim.instrument_id, ())
                if item.event_time >= claim.available_time
            )
            for observation in instrument_prices:
                session = sessions_by_date.get(observation.trade_date)
                if session is None or session.close_time != observation.event_time:
                    raise ClaimPerformanceInputError(
                        "price observation does not match the selected trading calendar"
                    )
            prices_by_date = {item.trade_date: item for item in instrument_prices}
            observed_prices: list[TradablePriceObservation] = []
            skipped_suspensions: list[TradablePriceObservation] = []
            missing_trade_dates: tuple[date, ...] = ()
            entry: TradablePriceObservation | None = None
            entry_index = -1
            for session_index, session in enumerate(expected_sessions):
                observation = prices_by_date.get(session.trade_date)
                if observation is None:
                    missing_trade_dates = (session.trade_date,)
                    break
                observed_prices.append(observation)
                if observation.suspended:
                    skipped_suspensions.append(observation)
                    continue
                entry = observation
                entry_index = session_index
                break
            if entry is None:
                samples.append(
                    _claim_sample(
                        claim,
                        active_at_decision=active_at_decision,
                        withdrawn_at=withdrawn_at,
                        statement_fingerprint=statement_fingerprint,
                        status=ClaimPerformanceStatus.PENDING,
                        reason=(
                            ClaimPerformanceExclusionReason.MISSING_PRICE
                            if missing_trade_dates
                            else ClaimPerformanceExclusionReason.WAITING_FOR_ENTRY
                        ),
                        calendar=calendar,
                        skipped_suspensions=tuple(skipped_suspensions),
                        missing_trade_dates=missing_trade_dates,
                        observed_prices=tuple(observed_prices),
                    )
                )
                continue

            sign = Decimal("1") if claim.direction is ClaimDirection.BULLISH else Decimal("-1")
            horizon_returns: list[ClaimHorizonReturn] = []
            horizon_set = set(policy.horizons)
            tradable_step = 0
            for session in expected_sessions[entry_index + 1 :]:
                observation = prices_by_date.get(session.trade_date)
                if observation is None:
                    missing_trade_dates = (session.trade_date,)
                    break
                observed_prices.append(observation)
                if observation.suspended:
                    skipped_suspensions.append(observation)
                    continue
                tradable_step += 1
                if tradable_step in horizon_set:
                    raw_return = (observation.price - entry.price) / entry.price
                    horizon_returns.append(
                        ClaimHorizonReturn(
                            horizon=tradable_step,
                            exit_observation=observation,
                            raw_return=raw_return,
                            signed_return=raw_return * sign,
                        )
                    )
                if tradable_step >= policy.horizons[-1]:
                    break
            mature = len(horizon_returns) == len(policy.horizons)
            samples.append(
                _claim_sample(
                    claim,
                    active_at_decision=active_at_decision,
                    withdrawn_at=withdrawn_at,
                    statement_fingerprint=statement_fingerprint,
                    status=(
                        ClaimPerformanceStatus.MATURE if mature else ClaimPerformanceStatus.PENDING
                    ),
                    reason=(
                        None
                        if mature
                        else ClaimPerformanceExclusionReason.MISSING_PRICE
                        if missing_trade_dates
                        else ClaimPerformanceExclusionReason.INSUFFICIENT_HORIZON
                    ),
                    calendar=calendar,
                    entry=entry,
                    skipped_suspensions=tuple(skipped_suspensions),
                    missing_trade_dates=missing_trade_dates,
                    horizon_returns=tuple(horizon_returns),
                    observed_prices=tuple(observed_prices),
                )
            )

    ordered_samples = tuple(
        sorted(
            samples,
            key=lambda item: (
                item.claim_available_time,
                item.source,
                item.claim_id,
                item.claim_revision_id,
            ),
        )
    )
    cutoff = max((item.logical_available_time for item in ordered_samples), default=None)
    return ClaimPerformanceResult(
        schema_version=KOL_PERFORMANCE_SCHEMA_VERSION,
        decision_time=decision,
        samples=ordered_samples,
        data_cutoff_time=cutoff,
        algorithm_version=policy.algorithm_version,
        policy_version=policy.policy_version,
        policy_fingerprint=policy.fingerprint,
        calendar_snapshots=tuple(used_calendars[key] for key in sorted(used_calendars)),
    )


__all__ = [
    "KOL_PERFORMANCE_ALGORITHM_VERSION",
    "KOL_PERFORMANCE_POLICY_VERSION",
    "KOL_PERFORMANCE_SCHEMA_VERSION",
    "ClaimHorizonReturn",
    "ClaimPerformanceExclusionReason",
    "ClaimPerformanceInputError",
    "ClaimPerformancePolicy",
    "ClaimPerformanceResult",
    "ClaimPerformanceSample",
    "ClaimPerformanceStatus",
    "TradingCalendarSnapshot",
    "TradingSession",
    "TradablePriceObservation",
    "compute_claim_performance",
    "select_active_claims",
]
