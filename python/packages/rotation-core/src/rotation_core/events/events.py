"""Ordered, idempotent sector-rotation event detection."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from rotation_core.temporal import canonical_instant, parse_instant

ROTATION_EVENT_VERSION = "rotation_event_v2"
_MAX_CONTIGUOUS_GAP_SECONDS = 90


class RotationPointConflictError(ValueError):
    """Duplicate timestamps disagree and cannot be ordered safely."""


@dataclass(frozen=True)
class SectorStrengthPoint:
    timestamp: str
    strengths: dict[str, float]
    source_version: str
    evidence_id: str

    def __post_init__(self) -> None:
        if not self.source_version.strip():
            raise ValueError("source_version must be non-empty")
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty")
        normalized: dict[str, float] = {}
        for sector, value in sorted(self.strengths.items()):
            if not sector:
                raise ValueError("sector id must be non-empty")
            if isinstance(value, bool):
                raise TypeError("sector strengths must be numeric")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("sector strengths must be finite")
            normalized[sector] = number
        object.__setattr__(self, "timestamp", canonical_instant(self.timestamp))
        object.__setattr__(self, "strengths", normalized)

    @property
    def payload(self) -> tuple[object, ...]:
        return (tuple(self.strengths.items()), self.source_version, self.evidence_id)


@dataclass(frozen=True)
class RotationEvent:
    event_id: str
    from_sector: str | None
    to_sector: str
    event_type: Literal["CROSSOVER", "DECAY"]
    timestamp: str
    confidence: float
    evidence_start: str
    evidence_end: str
    sample_size: int
    source_versions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    version: str = ROTATION_EVENT_VERSION


@dataclass(frozen=True)
class _LeadRun:
    lead: str | None
    points: tuple[SectorStrengthPoint, ...]

    @property
    def start(self) -> str:
        return self.points[0].timestamp


def _normalize(points: Sequence[object]) -> list[SectorStrengthPoint]:
    by_time: dict[datetime, list[SectorStrengthPoint]] = {}
    for point in points:
        if not isinstance(point, SectorStrengthPoint):
            raise TypeError("SectorStrengthPoint is required")
        if not point.strengths:
            continue
        by_time.setdefault(parse_instant(point.timestamp), []).append(point)
    normalized: list[SectorStrengthPoint] = []
    for instant in sorted(by_time):
        candidates = by_time[instant]
        winner = candidates[0]
        if any(item.payload != winner.payload for item in candidates[1:]):
            raise RotationPointConflictError(f"conflicting sector strengths at {winner.timestamp}")
        normalized.append(winner)
    return normalized


def _leading(strengths: dict[str, float]) -> str | None:
    maximum = max(strengths.values())
    leaders = sorted(sector for sector, value in strengths.items() if value == maximum)
    return leaders[0] if len(leaders) == 1 else None


def _compute_runs(points: list[SectorStrengthPoint]) -> list[_LeadRun]:
    runs: list[_LeadRun] = []
    for point in points:
        lead = _leading(point.strengths)
        contiguous = False
        if runs:
            gap = (
                parse_instant(point.timestamp) - parse_instant(runs[-1].points[-1].timestamp)
            ).total_seconds()
            contiguous = 0 < gap <= _MAX_CONTIGUOUS_GAP_SECONDS
        if runs and runs[-1].lead == lead and contiguous:
            runs[-1] = _LeadRun(lead, (*runs[-1].points, point))
        else:
            runs.append(_LeadRun(lead, (point,)))
    return runs


def _confirmation_index(run: _LeadRun, minutes: int) -> int | None:
    required_seconds = (minutes - 1) * 60
    start = parse_instant(run.start)
    for index, point in enumerate(run.points):
        if (parse_instant(point.timestamp) - start).total_seconds() >= required_seconds:
            return index
    return None


def _event_id(
    event_type: str,
    from_sector: str | None,
    to_sector: str,
    identity_time: str,
) -> str:
    payload = "|".join(
        (ROTATION_EVENT_VERSION, event_type, from_sector or "", to_sector, identity_time)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provenance(
    points: tuple[SectorStrengthPoint, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(dict.fromkeys(point.source_version for point in points)),
        tuple(dict.fromkeys(point.evidence_id for point in points)),
    )


def _crossover_confidence(point: SectorStrengthPoint, lead: str) -> float:
    values = sorted(point.strengths.values(), reverse=True)
    if len(values) < 2 or values[0] == 0:
        return 1.0
    margin = max(0.0, (point.strengths[lead] - values[1]) / abs(values[0]))
    return round(min(0.6 + margin, 1.0), 6)


def detect_rotation_events(
    points: list[SectorStrengthPoint],
    *,
    min_lead_minutes: int = 3,
    decay_threshold: float = 0.3,
) -> list[RotationEvent]:
    if isinstance(min_lead_minutes, bool) or min_lead_minutes < 1:
        raise ValueError("min_lead_minutes must be >= 1")
    if not 0 < decay_threshold <= 1:
        raise ValueError("decay_threshold must be in (0, 1]")
    normalized = _normalize(points)
    if not normalized:
        return []
    runs = _compute_runs(normalized)
    events: dict[str, RotationEvent] = {}

    for index in range(1, len(runs)):
        previous = runs[index - 1]
        current = runs[index]
        previous_confirmation = _confirmation_index(previous, min_lead_minutes)
        current_confirmation = _confirmation_index(current, min_lead_minutes)
        if (
            previous.lead is None
            or current.lead is None
            or previous.lead == current.lead
            or previous_confirmation is None
            or current_confirmation is None
        ):
            continue
        confirmation = current.points[current_confirmation]
        evidence_points = (*previous.points, *current.points[: current_confirmation + 1])
        source_versions, evidence_ids = _provenance(evidence_points)
        identity = _event_id("CROSSOVER", previous.lead, current.lead, current.start)
        events[identity] = RotationEvent(
            event_id=identity,
            from_sector=previous.lead,
            to_sector=current.lead,
            event_type="CROSSOVER",
            timestamp=current.start,
            confidence=_crossover_confidence(confirmation, current.lead),
            evidence_start=previous.start,
            evidence_end=confirmation.timestamp,
            sample_size=len(evidence_points),
            source_versions=source_versions,
            evidence_ids=evidence_ids,
        )

    for run in runs:
        confirmation = _confirmation_index(run, min_lead_minutes)
        if run.lead is None or confirmation is None:
            continue
        peak = -math.inf
        for point_index, point in enumerate(run.points):
            value = point.strengths[run.lead]
            peak = max(peak, value)
            if point_index < confirmation or peak <= 0:
                continue
            if (peak - value) / peak < decay_threshold:
                continue
            evidence_points = run.points[: point_index + 1]
            source_versions, evidence_ids = _provenance(evidence_points)
            identity = _event_id("DECAY", run.lead, run.lead, run.start)
            events[identity] = RotationEvent(
                event_id=identity,
                from_sector=run.lead,
                to_sector=run.lead,
                event_type="DECAY",
                timestamp=point.timestamp,
                confidence=round(min(0.6 + (peak - value) / peak, 1.0), 6),
                evidence_start=run.start,
                evidence_end=point.timestamp,
                sample_size=len(evidence_points),
                source_versions=source_versions,
                evidence_ids=evidence_ids,
            )
            break

    return sorted(
        events.values(),
        key=lambda event: (parse_instant(event.timestamp), event.event_type, event.event_id),
    )
