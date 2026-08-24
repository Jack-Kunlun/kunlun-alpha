"""Deterministic point-in-time sector snapshot computation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from market_core.models.validators import Bar, validate_bar

from rotation_core.taxonomy import SectorMembership
from rotation_core.temporal import canonical_instant, parse_date, parse_instant

SNAPSHOT_VERSION = "sector_snapshot_v2"


class SnapshotRevisionConflictError(ValueError):
    """One observation identity/revision has conflicting payloads."""


class MembershipResolver(Protocol):
    def memberships_of(
        self, sector_id: str, query_date: str, *, decision_time: str
    ) -> tuple[SectorMembership, ...]: ...


def _require_instance(value: object, expected: type[object], message: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(message)


@dataclass(frozen=True)
class SectorBarObservation:
    bar: Bar
    previous_close: Decimal
    available_time: str
    source: str
    source_version: str
    evidence_id: str
    revision: int = 0

    def __post_init__(self) -> None:
        _require_instance(self.bar, Bar, "bar must be a Bar")
        _require_instance(
            self.previous_close,
            Decimal,
            "previous_close must be Decimal",
        )
        if not self.previous_close.is_finite() or self.previous_close <= 0:
            raise ValueError("previous_close must be finite and > 0")
        if isinstance(self.revision, bool):
            raise TypeError("revision must be a non-negative int")
        _require_instance(self.revision, int, "revision must be a non-negative int")
        if self.revision < 0:
            raise ValueError("revision must be a non-negative int")
        for field_name in ("source", "source_version", "evidence_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        event = parse_instant(self.bar.timestamp)
        available = parse_instant(self.available_time)
        if event > available:
            raise ValueError("bar event_time must be <= available_time")
        parse_date(self.bar.date)
        object.__setattr__(self, "available_time", canonical_instant(self.available_time))

    @property
    def event_time(self) -> str:
        return canonical_instant(self.bar.timestamp)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.bar.unified_code, self.event_time)

    @property
    def payload(self) -> tuple[object, ...]:
        return (
            self.bar,
            self.previous_close,
            self.available_time,
            self.source,
            self.source_version,
            self.evidence_id,
        )


@dataclass(frozen=True)
class SnapshotEvidence:
    unified_code: str
    membership_source_version: str
    membership_evidence_id: str
    bar_event_time: str
    bar_available_time: str
    bar_revision: int
    bar_source_version: str
    bar_evidence_id: str


def _empty_exclusions() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class SectorSnapshot:
    sector_id: str
    date: str
    timestamp: str
    average_change: float
    speed: float
    turnover: Decimal
    breadth: float
    leader: str | None
    strength: float
    sample_size: int
    member_count: int
    freshness_seconds: int | None
    confidence: float
    source_versions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence: tuple[SnapshotEvidence, ...]
    excluded: Mapping[str, str] = field(default_factory=_empty_exclusions)
    version: str = SNAPSHOT_VERSION


def canonicalize_observations(
    observations: Sequence[object],
    *,
    decision_time: str | None = None,
) -> list[SectorBarObservation]:
    cutoff = parse_instant(decision_time) if decision_time is not None else None
    groups: dict[tuple[str, str], list[SectorBarObservation]] = {}
    for value in observations:
        if not isinstance(value, SectorBarObservation):
            raise TypeError("SectorBarObservation is required")
        if cutoff is not None:
            if parse_instant(value.event_time) > cutoff:
                continue
            if parse_instant(value.available_time) > cutoff:
                continue
        groups.setdefault(value.identity, []).append(value)

    winners: list[SectorBarObservation] = []
    for identity, group in groups.items():
        revision = max(item.revision for item in group)
        candidates = [item for item in group if item.revision == revision]
        winner = candidates[0]
        if any(item.payload != winner.payload for item in candidates[1:]):
            raise SnapshotRevisionConflictError(
                f"conflicting sector bars for {identity!r} at revision {revision}"
            )
        winners.append(winner)
    return sorted(winners, key=lambda item: (parse_instant(item.event_time), item.bar.unified_code))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def compute_snapshot(
    sector_id: str,
    query_date: str,
    decision_time: str,
    resolver: MembershipResolver,
    observations: Sequence[SectorBarObservation],
) -> SectorSnapshot:
    parse_date(query_date)
    decision = parse_instant(decision_time)
    timestamp = canonical_instant(decision_time)
    memberships = resolver.memberships_of(sector_id, query_date, decision_time=timestamp)
    membership_by_code = {item.unified_code: item for item in memberships}
    canonical = canonicalize_observations(observations, decision_time=timestamp)

    by_code: dict[str, list[SectorBarObservation]] = {}
    for item in canonical:
        if item.bar.date != query_date or item.bar.unified_code not in membership_by_code:
            continue
        by_code.setdefault(item.bar.unified_code, []).append(item)

    changes: list[Decimal] = []
    speeds: list[Decimal] = []
    turnover = Decimal("0")
    advancing = 0
    leader: str | None = None
    leader_change: Decimal | None = None
    ages: list[int] = []
    evidence: list[SnapshotEvidence] = []
    excluded: dict[str, str] = {}
    source_versions: set[str] = set()
    evidence_ids: set[str] = set()

    for code in sorted(membership_by_code):
        membership = membership_by_code[code]
        history = by_code.get(code, [])
        if not history:
            excluded[code] = "missing_or_unavailable_bar"
            continue
        current = history[-1]
        validation = validate_bar(current.bar)
        if not validation.valid:
            excluded[code] = f"invalid_bar:{validation.errors[0]}"
            continue
        if current.bar.suspended:
            excluded[code] = "suspended"
            continue
        if current.bar.price_type != "RAW":
            excluded[code] = "non_raw_price"
            continue

        change = (current.bar.close - current.previous_close) / current.previous_close
        changes.append(change)
        turnover += current.bar.amount
        if change > 0:
            advancing += 1
        if (
            leader_change is None
            or change > leader_change
            or (change == leader_change and leader is not None and code < leader)
        ):
            leader_change = change
            leader = code

        event = parse_instant(current.event_time)
        ages.append(max(0, int((decision - event).total_seconds())))
        if len(history) >= 2:
            previous = history[-2]
            previous_change = (
                previous.bar.close - previous.previous_close
            ) / previous.previous_close
            elapsed_minutes = Decimal(
                str((event - parse_instant(previous.event_time)).total_seconds() / 60)
            )
            if elapsed_minutes > 0:
                speeds.append((change - previous_change) / elapsed_minutes)

        source_versions.update((membership.source_version, current.source_version))
        evidence_ids.update((membership.evidence_id, current.evidence_id))
        evidence.append(
            SnapshotEvidence(
                unified_code=code,
                membership_source_version=membership.source_version,
                membership_evidence_id=membership.evidence_id,
                bar_event_time=current.event_time,
                bar_available_time=current.available_time,
                bar_revision=current.revision,
                bar_source_version=current.source_version,
                bar_evidence_id=current.evidence_id,
            )
        )

    sample_size = len(changes)
    member_count = len(memberships)
    average_change = (
        sum(changes, Decimal("0")) / Decimal(sample_size) if sample_size else Decimal("0")
    )
    speed = sum(speeds, Decimal("0")) / Decimal(len(speeds)) if speeds else Decimal("0")
    breadth = Decimal(advancing) / Decimal(sample_size) if sample_size else Decimal("0")
    strength = Decimal("0.6") * Decimal(str(_sigmoid(float(average_change * 20)))) + (
        Decimal("0.4") * breadth
    )
    confidence = Decimal(sample_size) / Decimal(member_count) if member_count else Decimal("0")

    return SectorSnapshot(
        sector_id=sector_id,
        date=query_date,
        timestamp=timestamp,
        average_change=round(float(average_change), 6),
        speed=round(float(speed), 6),
        turnover=turnover,
        breadth=round(float(breadth), 6),
        leader=leader,
        strength=round(float(strength), 6),
        sample_size=sample_size,
        member_count=member_count,
        freshness_seconds=max(ages) if ages else None,
        confidence=round(float(confidence), 6),
        source_versions=tuple(sorted(source_versions)),
        evidence_ids=tuple(sorted(evidence_ids)),
        evidence=tuple(evidence),
        excluded=excluded,
    )


class SnapshotAggregator:
    def __init__(self, sector_id: str, query_date: str, resolver: MembershipResolver) -> None:
        self._sector_id = sector_id
        self._date = query_date
        self._resolver = resolver
        self._observations: list[SectorBarObservation] = []
        self._revision = 0

    def feed(self, observation: SectorBarObservation) -> int:
        candidate = [*self._observations, observation]
        canonicalize_observations(candidate)
        self._observations = candidate
        self._revision += 1
        return self._revision

    def snapshot(self, decision_time: str) -> SectorSnapshot:
        return compute_snapshot(
            self._sector_id,
            self._date,
            decision_time,
            self._resolver,
            self._observations,
        )
