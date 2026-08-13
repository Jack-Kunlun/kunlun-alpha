"""Rotation event detection.

Detects sector-strength crossovers (a new leader taking over) and rapid decay
(a leader collapsing). Short-lived lead changes (jitter) are suppressed via a
minimum lead duration, so a brief overtake does not emit an event. A crossover
is emitted only once per sustained lead change, so it is not repeated every
minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SectorStrengthPoint:
    """One instant's sector strengths."""

    timestamp: str
    strengths: dict[str, float]


@dataclass(frozen=True)
class RotationEvent:
    """A detected rotation event with from/to, time, confidence and window."""

    from_sector: str | None
    to_sector: str
    event_type: Literal["CROSSOVER", "DECAY"]
    timestamp: str
    confidence: float
    evidence_window: int


@dataclass(frozen=True)
class _LeadRun:
    lead: str
    start: str
    end: str
    duration: int


def _leading(strengths: dict[str, float]) -> str:
    # Deterministic: max() keeps the first key on ties, so equal strengths do
    # not flicker the leader.
    return max(strengths, key=lambda k: strengths[k])


def _compute_runs(points: list[SectorStrengthPoint]) -> list[_LeadRun]:
    runs: list[_LeadRun] = []
    for point in points:
        lead = _leading(point.strengths)
        if runs and runs[-1].lead == lead:
            runs[-1] = _LeadRun(
                lead=lead, start=runs[-1].start, end=point.timestamp, duration=runs[-1].duration + 1
            )
        else:
            runs.append(_LeadRun(lead=lead, start=point.timestamp, end=point.timestamp, duration=1))
    return runs


def detect_rotation_events(
    points: list[SectorStrengthPoint],
    *,
    min_lead_minutes: int = 3,
    decay_threshold: float = 0.3,
) -> list[RotationEvent]:
    """Detect crossovers and decays from a sequence of strength points.

    ``min_lead_minutes`` suppresses jitter: a lead change lasting fewer than
    this many points is ignored. ``decay_threshold`` triggers a DECAY event
    when a leader's strength drops by that fraction from its peak.
    """
    if not points:
        return []

    runs = _compute_runs(points)
    valid_runs = [r for r in runs if r.duration >= min_lead_minutes]

    events: list[RotationEvent] = []
    for i in range(1, len(valid_runs)):
        prev = valid_runs[i - 1]
        curr = valid_runs[i]
        if prev.lead != curr.lead:
            events.append(
                RotationEvent(
                    from_sector=prev.lead,
                    to_sector=curr.lead,
                    event_type="CROSSOVER",
                    timestamp=curr.start,
                    confidence=0.7,
                    evidence_window=curr.duration,
                )
            )

    # Decay: the leading sector's strength collapses within the final run.
    last_run = valid_runs[-1] if valid_runs else None
    if last_run is not None:
        strengths = [
            p.strengths.get(last_run.lead, 0.0) for p in points if p.timestamp >= last_run.start
        ]
        if strengths:
            peak = max(strengths)
            trough = min(strengths)
            if peak > 0 and (peak - trough) / peak >= decay_threshold:
                events.append(
                    RotationEvent(
                        from_sector=last_run.lead,
                        to_sector=last_run.lead,
                        event_type="DECAY",
                        timestamp=last_run.end,
                        confidence=0.8,
                        evidence_window=last_run.duration,
                    )
                )

    return events
