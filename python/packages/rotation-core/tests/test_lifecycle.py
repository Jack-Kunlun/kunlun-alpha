"""Sector lifecycle tests.

Covers multi-metric classification (not a single change threshold), legal
transitions, illegal-jump rejection and explainable transitions.
"""

from __future__ import annotations

import pytest
from rotation_core.lifecycle import IllegalTransitionError, LifecycleClassifier, classify
from rotation_core.snapshot import SectorSnapshot


def _snapshot(change: float, breadth: float) -> SectorSnapshot:
    return SectorSnapshot(
        sector_id="s1",
        date="2026-08-13",
        timestamp="2026-08-13T02:00:00.000Z",
        average_change=change,
        turnover=1000.0,
        breadth=breadth,
        leader="A",
        strength=0.5,
    )


def test_classify_uses_multiple_metrics() -> None:
    # Same change, different breadth -> different states (breadth matters).
    assert classify(_snapshot(0.01, 0.3)) == "STARTUP"
    assert classify(_snapshot(0.01, 0.6)) == "FERMENT"


def test_legal_transition_chain() -> None:
    classifier = LifecycleClassifier("STARTUP")
    chain = [
        classifier.transition(_snapshot(0.02, 0.6)),
        classifier.transition(_snapshot(0.04, 0.7)),
    ]
    assert [t.to_state for t in chain] == ["FERMENT", "ACCELERATE"]


def test_illegal_jump_is_rejected() -> None:
    classifier = LifecycleClassifier("FREEZE")
    with pytest.raises(IllegalTransitionError):
        classifier.transition(_snapshot(0.04, 0.9))  # FREEZE -> CLIMAX illegal


def test_transition_is_explainable() -> None:
    classifier = LifecycleClassifier("STARTUP")
    transition = classifier.transition(_snapshot(0.02, 0.6))
    assert "change=" in transition.reason
    assert transition.confidence > 0


def test_stable_state_has_no_jump() -> None:
    classifier = LifecycleClassifier("FERMENT")
    transition = classifier.transition(_snapshot(0.02, 0.6))  # stays FERMENT
    assert transition.to_state == "FERMENT"
    assert transition.reason == "stable"
