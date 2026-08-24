from __future__ import annotations

import pytest
from rotation_core.events import (
    ROTATION_EVENT_VERSION,
    RotationPointConflictError,
    SectorStrengthPoint,
    detect_rotation_events,
)


def _point(
    minute: int,
    strengths: dict[str, float],
    *,
    evidence: str | None = None,
) -> SectorStrengthPoint:
    return SectorStrengthPoint(
        f"2026-08-13T01:{minute:02d}:00Z",
        strengths,
        "snapshot-v2",
        evidence or f"point-{minute}",
    )


def _crossover_points() -> list[SectorStrengthPoint]:
    return [
        _point(0, {"A": 0.8, "B": 0.4}),
        _point(1, {"A": 0.8, "B": 0.4}),
        _point(2, {"A": 0.8, "B": 0.4}),
        _point(3, {"A": 0.4, "B": 0.9}),
        _point(4, {"A": 0.4, "B": 0.9}),
        _point(5, {"A": 0.4, "B": 0.9}),
    ]


def test_reverse_chronological_input_is_normalized() -> None:
    points = _crossover_points()
    assert detect_rotation_events(points) == detect_rotation_events(list(reversed(points)))


def test_empty_strengths_are_explicitly_skipped() -> None:
    assert detect_rotation_events([_point(0, {})]) == []


def test_duplicate_timestamp_is_idempotent_but_conflict_fails_closed() -> None:
    point = _point(0, {"A": 0.8}, evidence="same")
    assert detect_rotation_events([point, point], min_lead_minutes=1) == []
    with pytest.raises(RotationPointConflictError):
        detect_rotation_events(
            [point, _point(0, {"A": 0.9}, evidence="other")],
            min_lead_minutes=1,
        )


def test_tie_is_a_barrier_not_insertion_order() -> None:
    points = [
        _point(0, {"A": 0.5, "B": 0.5}),
        _point(1, {"B": 0.5, "A": 0.5}),
        _point(2, {"A": 0.5, "B": 0.5}),
    ]
    assert detect_rotation_events(points) == []


def test_sustained_crossover_has_stable_identity_and_versioned_window() -> None:
    event = detect_rotation_events(_crossover_points())[0]
    assert event.event_type == "CROSSOVER"
    assert event.from_sector == "A"
    assert event.to_sector == "B"
    assert event.version == ROTATION_EVENT_VERSION
    assert len(event.event_id) == 64
    assert event.evidence_start == "2026-08-13T01:00:00.000Z"
    assert event.evidence_end == "2026-08-13T01:05:00.000Z"


def test_overlapping_replay_windows_emit_same_event_identity() -> None:
    points = _crossover_points()
    first = detect_rotation_events(points)
    second = detect_rotation_events([*points, _point(6, {"A": 0.3, "B": 0.9})])
    assert [event.event_id for event in first] == [event.event_id for event in second]


def test_brief_lead_between_sustained_runs_does_not_fabricate_direct_transition() -> None:
    points = [
        _point(0, {"A": 0.9, "B": 0.4, "C": 0.2}),
        _point(1, {"A": 0.9, "B": 0.4, "C": 0.2}),
        _point(2, {"A": 0.9, "B": 0.4, "C": 0.2}),
        _point(3, {"A": 0.2, "B": 0.3, "C": 0.9}),
        _point(4, {"A": 0.2, "B": 0.9, "C": 0.3}),
        _point(5, {"A": 0.2, "B": 0.9, "C": 0.3}),
        _point(6, {"A": 0.2, "B": 0.9, "C": 0.3}),
    ]
    assert [
        event for event in detect_rotation_events(points) if event.event_type == "CROSSOVER"
    ] == []


def test_decay_timestamp_is_first_threshold_crossing_and_is_replay_stable() -> None:
    points = [
        _point(0, {"A": 0.9, "B": 0.4}),
        _point(1, {"A": 0.9, "B": 0.4}),
        _point(2, {"A": 0.9, "B": 0.4}),
        _point(3, {"A": 0.5, "B": 0.4}),
        _point(4, {"A": 0.4, "B": 0.3}),
    ]
    decays = [event for event in detect_rotation_events(points) if event.event_type == "DECAY"]
    assert len(decays) == 1
    assert decays[0].timestamp == "2026-08-13T01:03:00.000Z"
