"""Emotion score V1.

A deterministic, versioned sentiment score. Each component is normalized to
[0, 1] and combined with fixed weights; the total and per-component scores are
reported with explanations. A missing component is handled by re-normalizing
the remaining weights (an explicit degradation rule) rather than guessing.
Version upgrades never overwrite old scores — v1 lives in this module, and a
future v2 would live in ``scoring/v2``.

P2-R01 (round 3): metrics are typed :class:`ScoredMetric` inputs, not bare
floats. Every metric carries its ``available_time`` and provenance, and all
contributing metrics must be available at a single mandatory ``decision_time``.
A metric that is missing or not yet available at the decision instant is
excluded with a structured reason. The aggregated :class:`SampleProvenance`
(source versions, evidence ids, sample size) and the per-component
:class:`MetricProvenance` are built from the real inputs — never blanks.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from emotion_core.pit import Instant
from emotion_core.provenance import MetricProvenance, SampleProvenance, ScoredMetric

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
    provenance: SampleProvenance
    components: dict[str, float] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    metric_provenance: dict[str, MetricProvenance] = field(default_factory=dict)
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


_COMPONENTS: dict[str, tuple[str, Callable[[float], float]]] = {
    "limit_up": ("limit_up_count", _normalize_limit_up),
    "limit_down": ("limit_down_count", _normalize_limit_down),
    "ladder_height": ("max_board", _normalize_height),
    "advancement": ("advancement_rate", _normalize_advancement),
    "premium": ("premium", _normalize_premium),
}


def score_emotion_v1(
    metrics: Mapping[str, ScoredMetric | None],
    weights: ScoringWeights | None = None,
    *,
    decision_time: str,
) -> EmotionScoreV1:
    """Score sentiment deterministically from typed, point-in-time metrics.

    ``metrics`` maps raw metric names (e.g. ``limit_up_count``) to typed
    :class:`ScoredMetric` inputs; a ``None`` value (or missing key) marks the
    component unavailable. ``decision_time`` is the single mandatory instant at
    which the score is computed: a metric whose ``available_time`` is after it
    is excluded (``not_yet_available``), so a score never mixes data from
    different decision instants. Excluded components are dropped from the
    weighted average with the remaining weights re-normalized, and every
    exclusion carries a structured reason.
    """
    if not decision_time or not decision_time.strip():
        raise ValueError("decision_time is mandatory and must be non-empty")
    decision = Instant.parse(decision_time)

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
    excluded: dict[str, str] = {}
    metric_provenance: dict[str, MetricProvenance] = {}
    source_versions: list[str] = []
    evidence_ids: list[str] = []
    available_weight = 0.0

    for component, (metric_name, normalize) in _COMPONENTS.items():
        metric = metrics.get(metric_name)
        if metric is None:
            explanations[component] = "missing"
            excluded[component] = "missing"
            continue
        if not metric.available_at(decision):
            explanations[component] = "not_yet_available"
            excluded[component] = "not_yet_available"
            continue
        score = normalize(metric.value)
        components[component] = score
        explanations[component] = f"{metric_name}={metric.value} -> {score:.3f}"
        metric_provenance[component] = MetricProvenance(
            value=metric.value,
            as_of=metric.available_time,
            source=metric.source,
            source_version=metric.source_version,
            evidence_id=metric.evidence_id,
        )
        source_versions.append(metric.source_version)
        evidence_ids.append(metric.evidence_id)
        available_weight += weight_map[component]

    provenance = SampleProvenance(
        algorithm_version=SCORE_VERSION,
        as_of=decision.isoformat(),
        included=tuple(components.keys()),
        excluded=excluded,
        source_versions=tuple(dict.fromkeys(source_versions)),
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
    )

    if available_weight <= 0:
        return EmotionScoreV1(
            total=0.0,
            provenance=provenance,
            components=components,
            explanations=explanations,
            metric_provenance=metric_provenance,
        )

    total = sum(components[c] * weight_map[c] for c in components) / available_weight
    return EmotionScoreV1(
        total=round(total, 4),
        provenance=provenance,
        components=components,
        explanations=explanations,
        metric_provenance=metric_provenance,
    )
