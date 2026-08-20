"""Emotion score V1 tests.

Covers determinism (fixed sample -> fixed score), missing-data degradation and
version stability.

P2-R01 (round 3): metrics are typed :class:`ScoredMetric` inputs and the score
requires a mandatory ``decision_time`` at which all contributing metrics are
available.
"""

from __future__ import annotations

from emotion_core.provenance import ScoredMetric
from emotion_core.scoring import SCORE_VERSION, score_emotion_v1

_DECISION = "2026-08-14T07:30:00.000Z"


def _metric(value: float, *, available_time: str = "2026-08-14T07:00:00.000Z") -> ScoredMetric:
    return ScoredMetric(
        value=value,
        available_time=available_time,
        source="emotion-engine",
        source_version="emotion_v1",
        evidence_id="ev-1",
    )


def test_fixed_sample_gives_fixed_score() -> None:
    metrics: dict[str, ScoredMetric | None] = {
        "limit_up_count": _metric(80),
        "limit_down_count": _metric(5),
        "max_board": _metric(6),
        "advancement_rate": _metric(0.4),
        "premium": _metric(0.03),
    }
    first = score_emotion_v1(metrics, decision_time=_DECISION)
    second = score_emotion_v1(metrics, decision_time=_DECISION)
    assert first == second
    assert first.total > 0
    assert first.version == SCORE_VERSION


def test_missing_data_reweights_remaining_components() -> None:
    metrics: dict[str, ScoredMetric | None] = {
        "limit_up_count": _metric(80),
        "limit_down_count": None,  # missing
        "max_board": None,  # missing
        "advancement_rate": _metric(0.4),
        "premium": _metric(0.03),
    }
    result = score_emotion_v1(metrics, decision_time=_DECISION)

    assert "limit_down" not in result.components
    assert "ladder_height" not in result.components
    assert result.explanations["limit_down"] == "missing"
    assert result.total > 0


def test_all_missing_gives_zero() -> None:
    result = score_emotion_v1({}, decision_time=_DECISION)
    assert result.total == 0.0


def test_version_is_stable() -> None:
    result = score_emotion_v1({"limit_up_count": _metric(80)}, decision_time=_DECISION)
    assert result.version == "emotion_score_v1"


def test_score_records_provenance_for_available_components() -> None:
    metrics: dict[str, ScoredMetric | None] = {
        "limit_up_count": _metric(80),
        "limit_down_count": None,
    }
    result = score_emotion_v1(metrics, decision_time=_DECISION)
    # Available component keeps a provenance/explanation trail; missing one is
    # explicitly marked, never silently dropped without a reason.
    assert "limit_up" in result.explanations
    assert result.explanations["limit_down"] == "missing"


def test_score_carries_structured_provenance() -> None:
    metrics: dict[str, ScoredMetric | None] = {
        "limit_up_count": _metric(80),
        "limit_down_count": None,  # missing
        "max_board": _metric(6),
        "advancement_rate": _metric(0.4),
        "premium": _metric(0.03),
    }
    result = score_emotion_v1(metrics, decision_time=_DECISION)

    prov = result.provenance
    assert prov.algorithm_version == "emotion_score_v1"
    assert prov.as_of == "2026-08-14T07:30:00+00:00"
    # Structured included/excluded — not just free-text explanations.
    assert "limit_up" in prov.included
    assert "premium" in prov.included
    assert prov.excluded["limit_down"] == "missing"
    assert prov.sample_size == len(prov.included)
