"""Emotion score V1.

A deterministic, versioned sentiment score. Each component is normalized to
[0, 1] and combined with fixed weights; the total and per-component scores are
reported with explanations. A missing component is handled by re-normalizing
the remaining weights (an explicit degradation rule) rather than guessing.
Version upgrades never overwrite old scores — v1 lives in this module, and a
future v2 would live in ``scoring/v2``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

SCORE_VERSION = "emotion_score_v1"


@dataclass(frozen=True)
class ScoringWeights:
    """Component weights for emotion_score_v1."""

    limit_up: float = 0.3
    limit_down: float = 0.2
    ladder_height: float = 0.2
    advancement: float = 0.15
    premium: float = 0.15


@dataclass(frozen=True)
class EmotionScoreV1:
    """The emotion_score_v1 result."""

    total: float
    components: dict[str, float] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    version: str = SCORE_VERSION


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _normalize_limit_up(count: float) -> float:
    return _sigmoid((count - 50) / 30)


def _normalize_limit_down(count: float) -> float:
    return 1.0 - _sigmoid((count - 10) / 20)


def _normalize_height(max_board: float) -> float:
    return min(max_board / 10.0, 1.0)


def _normalize_advancement(rate: float) -> float:
    return max(0.0, min(rate, 1.0))


def _normalize_premium(premium: float) -> float:
    return _sigmoid(premium * 20)


_COMPONENTS = {
    "limit_up": ("limit_up_count", _normalize_limit_up),
    "limit_down": ("limit_down_count", _normalize_limit_down),
    "ladder_height": ("max_board", _normalize_height),
    "advancement": ("advancement_rate", _normalize_advancement),
    "premium": ("premium", _normalize_premium),
}


def score_emotion_v1(
    metrics: dict[str, float | None],
    weights: ScoringWeights | None = None,
) -> EmotionScoreV1:
    """Score sentiment deterministically from raw metrics.

    ``metrics`` maps raw metric names to values; a value of ``None`` (or a
    missing key) marks the component as unavailable and it is dropped from the
    weighted average, with the remaining weights re-normalized.
    """
    weights = weights or ScoringWeights()
    weight_map = {
        "limit_up": weights.limit_up,
        "limit_down": weights.limit_down,
        "ladder_height": weights.ladder_height,
        "advancement": weights.advancement,
        "premium": weights.premium,
    }

    components: dict[str, float] = {}
    explanations: dict[str, str] = {}
    available_weight = 0.0

    for component, (metric_name, normalize) in _COMPONENTS.items():
        raw = metrics.get(metric_name)
        if raw is None:
            explanations[component] = "missing"
            continue
        score = normalize(raw)
        components[component] = score
        explanations[component] = f"{metric_name}={raw} -> {score:.3f}"
        available_weight += weight_map[component]

    if available_weight <= 0:
        return EmotionScoreV1(total=0.0, components=components, explanations=explanations)

    total = sum(components[c] * weight_map[c] for c in components) / available_weight
    return EmotionScoreV1(total=round(total, 4), components=components, explanations=explanations)
