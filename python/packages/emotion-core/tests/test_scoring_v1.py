"""Emotion score V1 tests.

Covers determinism (fixed sample -> fixed score), missing-data degradation and
version stability.
"""

from __future__ import annotations

from emotion_core.scoring import SCORE_VERSION, score_emotion_v1


def test_fixed_sample_gives_fixed_score() -> None:
    metrics = {
        "limit_up_count": 80,
        "limit_down_count": 5,
        "max_board": 6,
        "advancement_rate": 0.4,
        "premium": 0.03,
    }
    first = score_emotion_v1(metrics)
    second = score_emotion_v1(metrics)
    assert first == second
    assert first.total > 0
    assert first.version == SCORE_VERSION


def test_missing_data_reweights_remaining_components() -> None:
    metrics = {
        "limit_up_count": 80,
        "limit_down_count": None,  # missing
        "max_board": None,  # missing
        "advancement_rate": 0.4,
        "premium": 0.03,
    }
    result = score_emotion_v1(metrics)

    assert "limit_down" not in result.components
    assert "ladder_height" not in result.components
    assert result.explanations["limit_down"] == "missing"
    assert result.total > 0


def test_all_missing_gives_zero() -> None:
    result = score_emotion_v1({})
    assert result.total == 0.0


def test_version_is_stable() -> None:
    result = score_emotion_v1({"limit_up_count": 80})
    assert result.version == "emotion_score_v1"


def test_score_records_provenance_for_available_components() -> None:
    metrics: dict[str, float | None] = {"limit_up_count": 80, "limit_down_count": None}
    result = score_emotion_v1(metrics)
    # Available component keeps a provenance/explanation trail; missing one is
    # explicitly marked, never silently dropped without a reason.
    assert "limit_up" in result.explanations
    assert result.explanations["limit_down"] == "missing"
