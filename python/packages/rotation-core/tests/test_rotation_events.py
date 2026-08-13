"""Rotation event detection tests.

Covers jitter suppression, ties (equal strength), brief overtakes, rapid
decay, and non-repetition of the same crossover.
"""

from __future__ import annotations

from rotation_core.events import SectorStrengthPoint, detect_rotation_events


def _point(timestamp: str, strengths: dict[str, float]) -> SectorStrengthPoint:
    return SectorStrengthPoint(timestamp=timestamp, strengths=strengths)


def test_jitter_is_suppressed() -> None:
    # A leads, B briefly overtakes for 2 minutes (< min_lead_minutes), then A
    # leads again — no crossover emitted.
    points = [
        _point("t1", {"A": 0.8, "B": 0.5}),
        _point("t2", {"A": 0.6, "B": 0.7}),
        _point("t3", {"A": 0.6, "B": 0.7}),
        _point("t4", {"A": 0.8, "B": 0.5}),
        _point("t5", {"A": 0.8, "B": 0.5}),
    ]
    events = detect_rotation_events(points, min_lead_minutes=3)
    assert events == []


def test_tie_does_not_flicker_leader() -> None:
    points = [
        _point("t1", {"A": 0.5, "B": 0.5}),
        _point("t2", {"A": 0.5, "B": 0.5}),
        _point("t3", {"A": 0.5, "B": 0.5}),
    ]
    events = detect_rotation_events(points, min_lead_minutes=2)
    assert events == []


def test_sustained_crossover_emits_event() -> None:
    points = [
        _point("t1", {"A": 0.8, "B": 0.4}),
        _point("t2", {"A": 0.8, "B": 0.4}),
        _point("t3", {"A": 0.8, "B": 0.4}),
        _point("t4", {"A": 0.4, "B": 0.9}),
        _point("t5", {"A": 0.4, "B": 0.9}),
        _point("t6", {"A": 0.4, "B": 0.9}),
    ]
    events = detect_rotation_events(points, min_lead_minutes=3)
    crossovers = [e for e in events if e.event_type == "CROSSOVER"]
    assert len(crossovers) == 1
    assert crossovers[0].from_sector == "A"
    assert crossovers[0].to_sector == "B"


def test_rapid_decay_emits_event() -> None:
    points = [
        _point("t1", {"A": 0.9, "B": 0.4}),
        _point("t2", {"A": 0.9, "B": 0.4}),
        _point("t3", {"A": 0.9, "B": 0.4}),
        _point("t4", {"A": 0.5, "B": 0.4}),  # A decays but stays leader
        _point("t5", {"A": 0.5, "B": 0.4}),
        _point("t6", {"A": 0.5, "B": 0.4}),
    ]
    events = detect_rotation_events(points, min_lead_minutes=3, decay_threshold=0.3)
    assert any(e.event_type == "DECAY" for e in events)


def test_same_crossover_not_repeated() -> None:
    points = [
        _point("t1", {"A": 0.8, "B": 0.4}),
        _point("t2", {"A": 0.8, "B": 0.4}),
        _point("t3", {"A": 0.8, "B": 0.4}),
        _point("t4", {"A": 0.4, "B": 0.9}),
        _point("t5", {"A": 0.4, "B": 0.9}),
        _point("t6", {"A": 0.4, "B": 0.9}),
        _point("t7", {"A": 0.4, "B": 0.9}),
        _point("t8", {"A": 0.4, "B": 0.9}),
    ]
    events = detect_rotation_events(points, min_lead_minutes=3)
    crossovers = [e for e in events if e.event_type == "CROSSOVER"]
    assert len(crossovers) == 1
