from __future__ import annotations

from decimal import Decimal

import pytest
from rotation_core.lifecycle import (
    DEFAULT_CONFIG,
    IllegalTransitionError,
    LifecycleClassifier,
    classify,
)
from rotation_core.snapshot import SectorSnapshot


def _snapshot(change: float, breadth: float, *, speed: float = 0.0) -> SectorSnapshot:
    return SectorSnapshot(
        sector_id="s1",
        date="2026-08-13",
        timestamp="2026-08-13T02:00:00.000Z",
        average_change=change,
        speed=speed,
        turnover=Decimal("1000"),
        breadth=breadth,
        leader="600000.SH",
        strength=0.5,
        sample_size=8,
        member_count=10,
        freshness_seconds=30,
        confidence=0.8,
        source_versions=("bars-v1", "membership-v1"),
        evidence_ids=("e1", "e2"),
        evidence=(),
    )


def test_classify_uses_explicit_versioned_multi_metric_config() -> None:
    assert DEFAULT_CONFIG.version == "lifecycle_v1"
    assert classify(_snapshot(0.01, 0.3)) == "STARTUP"
    assert classify(_snapshot(0.01, 0.6)) == "FERMENT"


def test_legal_transition_carries_complete_evidence() -> None:
    transition = LifecycleClassifier("STARTUP").transition(_snapshot(0.02, 0.6, speed=0.01))
    assert transition.to_state == "FERMENT"
    assert transition.lifecycle_version == "lifecycle_v1"
    assert transition.snapshot_version == "sector_snapshot_v2"
    assert transition.sample_size == 8
    assert transition.freshness_seconds == 30
    assert transition.evidence_ids == ("e1", "e2")
    assert len(transition.transition_id) == 64
    assert "config=lifecycle_v1" in transition.reason


def test_illegal_jump_is_rejected() -> None:
    with pytest.raises(IllegalTransitionError):
        LifecycleClassifier("FREEZE").transition(_snapshot(0.04, 0.9))


def test_stable_transition_is_deterministic() -> None:
    first = LifecycleClassifier("FERMENT").transition(_snapshot(0.02, 0.6))
    second = LifecycleClassifier("FERMENT").transition(_snapshot(0.02, 0.6))
    assert first == second
    assert first.reason == "stable"
