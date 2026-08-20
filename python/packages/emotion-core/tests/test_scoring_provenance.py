"""Emotion score V1 provenance & availability tests (P2-R01 R3-5, blocking #6).

The score no longer takes bare floats: every metric is a typed
:class:`ScoredMetric` carrying its value, its ``available_time`` and its
source / source_version / evidence_id provenance. All metrics that contribute
to one score must be available at a single ``decision_time``; a metric that is
not yet available at that instant is excluded with a structured reason. The
score's ``decision_time`` / ``as_of`` is mandatory and never an empty string,
and the aggregated provenance is built from the real inputs (source versions,
evidence ids, sample size) — never filled with blanks.
"""

from __future__ import annotations

import pytest
from emotion_core.provenance import ScoredMetric
from emotion_core.scoring import SCORE_VERSION, score_emotion_v1


def _metric(
    value: float,
    *,
    available_time: str = "2026-08-14T07:00:00.000Z",
    source: str = "emotion-engine",
    source_version: str = "emotion_v1",
    evidence_id: str = "ev-1",
) -> ScoredMetric:
    return ScoredMetric(
        value=value,
        available_time=available_time,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id,
    )


def test_decision_time_is_mandatory_and_non_empty() -> None:
    with pytest.raises(ValueError, match="decision_time"):
        score_emotion_v1({"limit_up_count": _metric(80)}, decision_time="")


def test_typed_metrics_produce_score_with_aggregated_provenance() -> None:
    metrics = {
        "limit_up_count": _metric(80, source_version="limit_v1", evidence_id="ev-lu"),
        "premium": _metric(0.03, source_version="premium_v1", evidence_id="ev-pm"),
    }
    result = score_emotion_v1(metrics, decision_time="2026-08-14T07:30:00.000Z")

    assert result.total > 0
    prov = result.provenance
    assert prov.algorithm_version == SCORE_VERSION
    assert prov.as_of == "2026-08-14T07:30:00+00:00"
    assert prov.as_of != ""
    # Provenance aggregated from the real inputs, not blanks.
    assert "limit_v1" in prov.source_versions
    assert "premium_v1" in prov.source_versions
    assert "ev-lu" in prov.evidence_ids
    assert "ev-pm" in prov.evidence_ids
    assert prov.sample_size == 2


def test_metric_not_available_at_decision_time_is_excluded() -> None:
    metrics = {
        "limit_up_count": _metric(80, available_time="2026-08-14T07:00:00.000Z"),
        # premium only becomes available AFTER the decision instant.
        "premium": _metric(0.03, available_time="2026-08-14T09:00:00.000Z"),
    }
    result = score_emotion_v1(metrics, decision_time="2026-08-14T07:30:00.000Z")

    assert "limit_up" in result.provenance.included
    assert "premium" not in result.provenance.included
    assert result.provenance.excluded["premium"] == "not_yet_available"


def test_missing_metric_is_excluded_with_reason() -> None:
    metrics = {
        "limit_up_count": _metric(80),
        "limit_down_count": None,
    }
    result = score_emotion_v1(metrics, decision_time="2026-08-14T07:30:00.000Z")
    assert result.provenance.excluded["limit_down"] == "missing"


def test_all_excluded_gives_zero() -> None:
    result = score_emotion_v1({}, decision_time="2026-08-14T07:30:00.000Z")
    assert result.total == 0.0
    assert result.provenance.sample_size == 0


def test_component_carries_value_as_of_and_provenance() -> None:
    metrics = {"limit_up_count": _metric(80, evidence_id="ev-lu", source_version="limit_v1")}
    result = score_emotion_v1(metrics, decision_time="2026-08-14T07:30:00.000Z")
    comp = result.metric_provenance["limit_up"]
    assert comp.as_of == "2026-08-14T07:00:00+00:00"  # the metric's available_time
    assert comp.source_version == "limit_v1"
    assert comp.evidence_id == "ev-lu"
    assert comp.value == 80
