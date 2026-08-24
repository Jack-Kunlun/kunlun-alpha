"""HotTopic aggregation and HotScore V1 acceptance tests (P3-N08)."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from event_core.models import (
    MARKET_EVENT_SCHEMA_VERSION,
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
)
from hotspot_core import (
    HOT_SCORE_VERSION,
    TOPIC_ASSIGNMENT_VERSION,
    ConflictingDuplicateEventError,
    FutureDataError,
    HotScorePolicy,
    PreviousSnapshotError,
    TopicLifecycle,
    TopicObservation,
    build_hot_topic_snapshot,
)

DECISION = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def event(
    index: int,
    *,
    available_time: datetime,
    confidence_bps: int = 9000,
    source_id: str = "source-a",
    instrument_id: str = "600001.SH",
    sector_id: str = "sector-ai",
) -> MarketEvent:
    excerpt = f"事件证据{index}"
    publish_time = available_time - timedelta(minutes=1)
    return MarketEvent(
        event_type=MarketEventType.INDUSTRY,
        headline=f"热点事件 {index}",
        summary=f"热点事件 {index} 的可追溯摘要。",
        occur_time=publish_time,
        publish_time=publish_time,
        available_time=available_time,
        instrument_ids=(instrument_id,),
        sector_ids=(sector_id,),
        evidence=(
            EventEvidence(
                evidence_id=digest(f"evidence-{index}"),
                content_record_id=f"record-{index}",
                content_version_id=digest(f"content-{index}"),
                source_id=source_id,
                source_version="v1",
                available_time=publish_time,
                start_offset=0,
                end_offset=len(excerpt),
                excerpt=excerpt,
            ),
        ),
        model_provenance=ModelProvenance(
            producer_type=ProducerType.MODEL,
            provider="provider-a",
            model_id="event-extractor",
            model_version="model-v1",
            prompt_version="prompt-v1",
            output_schema_version=MARKET_EVENT_SCHEMA_VERSION,
            configuration_fingerprint=digest("event-config"),
            extraction_run_id=f"run-{index}",
            processing_time=available_time,
        ),
        confidence_bps=confidence_bps,
    )


def observation(
    index: int,
    *,
    available_time: datetime,
    confidence_bps: int = 9000,
    relevance_bps: int = 9000,
    source_id: str = "source-a",
    instrument_id: str = "600001.SH",
) -> TopicObservation:
    market_event = event(
        index,
        available_time=available_time,
        confidence_bps=confidence_bps,
        source_id=source_id,
        instrument_id=instrument_id,
    )
    return TopicObservation(
        event=market_event,
        topic_id="topic-ai",
        topic_name="人工智能",
        relevance_bps=relevance_bps,
        assignment_version=TOPIC_ASSIGNMENT_VERSION,
        assignment_fingerprint=digest(f"assignment-{index}"),
        assignment_available_time=available_time,
    )


def snapshot(
    observations: list[TopicObservation],
    *,
    decision_time: datetime = DECISION,
    policy: HotScorePolicy | None = None,
    previous: object | None = None,
):
    return build_hot_topic_snapshot(
        topic_id="topic-ai",
        topic_name="人工智能",
        observations=observations,
        decision_time=decision_time,
        policy=policy,
        previous_snapshot=previous,  # type: ignore[arg-type]
    )


def test_snapshot_is_deterministic_versioned_and_immutable() -> None:
    observations = [
        observation(1, available_time=DECISION - timedelta(minutes=5)),
        observation(2, available_time=DECISION - timedelta(minutes=10), source_id="source-b"),
    ]
    first = snapshot(observations)
    second = snapshot(list(reversed(observations)))
    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert first.algorithm_version == HOT_SCORE_VERSION
    assert len(first.policy_fingerprint) == 64
    assert len(first.snapshot_id) == 64
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.score_bps = 0  # type: ignore[misc]


def test_window_is_left_open_right_closed() -> None:
    policy = HotScorePolicy(lookback_minutes=60, recent_window_minutes=15)
    observations = [
        observation(1, available_time=DECISION - timedelta(minutes=60)),
        observation(
            2,
            available_time=DECISION - timedelta(minutes=60) + timedelta(microseconds=1),
        ),
        observation(3, available_time=DECISION),
    ]
    result = snapshot(observations, policy=policy)
    assert result.event_count == 2
    assert result.stale_event_count == 1
    assert observations[0].event.event_id not in result.event_ids
    assert observations[1].event.event_id in result.event_ids
    assert observations[2].event.event_id in result.event_ids


def test_future_event_or_assignment_is_rejected_not_silently_filtered() -> None:
    future = observation(1, available_time=DECISION + timedelta(seconds=1))
    with pytest.raises(FutureDataError, match="unavailable"):
        snapshot([future])

    current = observation(2, available_time=DECISION - timedelta(minutes=1))
    future_assignment = dataclasses.replace(
        current,
        assignment_available_time=DECISION + timedelta(seconds=1),
    )
    with pytest.raises(FutureDataError, match="unavailable"):
        snapshot([future_assignment])


def test_duplicate_delivery_is_idempotent_but_conflict_fails_closed() -> None:
    item = observation(1, available_time=DECISION - timedelta(minutes=1))
    deduplicated = snapshot([item, item])
    assert deduplicated.event_count == 1
    with pytest.raises(ConflictingDuplicateEventError, match="conflicting"):
        snapshot([item, dataclasses.replace(item, relevance_bps=8000)])


def test_event_count_does_not_equal_hot_strength() -> None:
    weak = [
        observation(
            index,
            available_time=DECISION - timedelta(minutes=index),
            confidence_bps=2000,
            relevance_bps=3000,
            source_id="single-source",
            instrument_id="600001.SH",
        )
        for index in range(1, 21)
    ]
    strong = [
        observation(
            101,
            available_time=DECISION - timedelta(minutes=1),
            source_id="source-a",
            instrument_id="600001.SH",
        ),
        observation(
            102,
            available_time=DECISION - timedelta(minutes=2),
            source_id="source-b",
            instrument_id="600002.SH",
        ),
    ]
    weak_result = snapshot(weak)
    strong_result = snapshot(strong)
    assert weak_result.event_count == 20
    assert strong_result.event_count == 2
    assert strong_result.score_bps > weak_result.score_bps
    assert strong_result.lifecycle is TopicLifecycle.HOT
    assert weak_result.lifecycle is not TopicLifecycle.HOT


def test_sparse_high_quality_topic_cannot_be_hot_without_minimum_sample() -> None:
    result = snapshot([observation(1, available_time=DECISION)])
    assert result.event_count == 1
    assert result.lifecycle is not TopicLifecycle.HOT
    assert result.confidence_bps < result.components.evidence_quality_bps


def test_lifecycle_progresses_to_hot_cooling_and_dormant() -> None:
    hot_observations = [
        observation(1, available_time=DECISION - timedelta(minutes=1), source_id="source-a"),
        observation(
            2,
            available_time=DECISION - timedelta(minutes=2),
            source_id="source-b",
            instrument_id="600002.SH",
        ),
    ]
    hot = snapshot(hot_observations)
    assert hot.lifecycle is TopicLifecycle.HOT
    cooling_time = DECISION + timedelta(hours=20)
    cooling = snapshot(hot_observations, decision_time=cooling_time, previous=hot)
    assert cooling.lifecycle is TopicLifecycle.COOLING
    dormant_time = DECISION + timedelta(hours=25)
    dormant = snapshot(hot_observations, decision_time=dormant_time, previous=cooling)
    assert dormant.lifecycle is TopicLifecycle.DORMANT
    assert dormant.event_count == 0
    assert dormant.previous_snapshot_id == cooling.snapshot_id


def test_source_diversity_counts_independent_sources_not_messages() -> None:
    same_source = snapshot(
        [
            observation(1, available_time=DECISION, source_id="source-a"),
            observation(2, available_time=DECISION, source_id="source-a"),
        ]
    )
    diverse = snapshot(
        [
            observation(3, available_time=DECISION, source_id="source-a"),
            observation(4, available_time=DECISION, source_id="source-b"),
        ]
    )
    assert same_source.source_count == 1
    assert diverse.source_count == 2
    assert diverse.components.source_diversity_bps > same_source.components.source_diversity_bps


def test_policy_is_strict_versioned_and_content_addressed() -> None:
    default = HotScorePolicy()
    changed = dataclasses.replace(default, source_saturation_count=5)
    assert default.fingerprint != changed.fingerprint
    with pytest.raises(TypeError, match="strict integer"):
        dataclasses.replace(default, minimum_hot_events=True)
    with pytest.raises(ValueError, match="sum to 10000"):
        dataclasses.replace(default, quality_weight_bps=3999)


def test_previous_snapshot_must_match_topic_policy_and_time() -> None:
    prior = snapshot([observation(1, available_time=DECISION)], decision_time=DECISION)
    with pytest.raises(PreviousSnapshotError, match="predate"):
        snapshot(
            [observation(2, available_time=DECISION)],
            decision_time=DECISION,
            previous=prior,
        )
    with pytest.raises(PreviousSnapshotError, match="policy"):
        snapshot(
            [observation(3, available_time=DECISION + timedelta(minutes=1))],
            decision_time=DECISION + timedelta(minutes=1),
            policy=HotScorePolicy(source_saturation_count=5),
            previous=prior,
        )


def test_topic_assignment_cannot_predate_event() -> None:
    item = observation(1, available_time=DECISION)
    with pytest.raises(ValueError, match="cannot predate"):
        dataclasses.replace(
            item,
            assignment_available_time=DECISION - timedelta(seconds=1),
        )
