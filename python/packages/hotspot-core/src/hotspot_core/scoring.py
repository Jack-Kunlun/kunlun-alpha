"""Deterministic integer HotScore V1 aggregation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from hotspot_core.models import (
    HotScoreComponents,
    HotScorePolicy,
    HotTopicSnapshot,
    TopicLifecycle,
    TopicObservation,
)

_COORDINATE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def _text(value: object, field_name: str, *, maximum: int = 256) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds its maximum length")
    return value


def _coordinate(value: object, field_name: str) -> str:
    text = _text(value, field_name, maximum=128)
    if _COORDINATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{field_name} must be a version-safe coordinate")
    return text


def _aware_utc(value: object, field_name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class HotTopicError(ValueError):
    """Base HotTopic aggregation error."""


class FutureDataError(HotTopicError):
    """An event or topic assignment was unavailable at decision time."""


class ConflictingDuplicateEventError(HotTopicError):
    """The same event ID arrived with conflicting topic-assignment facts."""


class PreviousSnapshotError(HotTopicError):
    """The prior lifecycle snapshot is incompatible with this calculation."""


def _round_ratio(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _timedelta_microseconds(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def _event_quality(observation: TopicObservation) -> int:
    return _round_ratio(
        observation.event.confidence_bps * observation.relevance_bps,
        10_000,
    )


def _lifecycle(
    *,
    score_bps: int,
    event_count: int,
    policy: HotScorePolicy,
    previous: HotTopicSnapshot | None,
) -> TopicLifecycle:
    if event_count == 0:
        return TopicLifecycle.DORMANT
    if (
        previous is not None
        and previous.lifecycle in (TopicLifecycle.HOT, TopicLifecycle.RISING)
        and score_bps + policy.cooling_drop_bps <= previous.score_bps
    ):
        return TopicLifecycle.COOLING
    if score_bps >= policy.hot_threshold_bps and event_count >= policy.minimum_hot_events:
        return TopicLifecycle.HOT
    if score_bps >= policy.rising_threshold_bps:
        return TopicLifecycle.RISING
    return TopicLifecycle.EMERGING


def build_hot_topic_snapshot(
    *,
    topic_id: str,
    topic_name: str,
    observations: Iterable[TopicObservation],
    decision_time: datetime,
    policy: HotScorePolicy | None = None,
    previous_snapshot: HotTopicSnapshot | None = None,
) -> HotTopicSnapshot:
    """Build one immutable, point-in-time topic snapshot."""
    _coordinate(topic_id, "topic_id")
    _text(topic_name, "topic_name", maximum=200)
    moment = _aware_utc(decision_time, "decision_time")
    active_policy = policy or HotScorePolicy()
    if type(active_policy) is not HotScorePolicy:
        raise TypeError("policy must be a HotScorePolicy")
    if previous_snapshot is not None:
        if type(previous_snapshot) is not HotTopicSnapshot:
            raise TypeError("previous_snapshot must be a HotTopicSnapshot")
        if previous_snapshot.topic_id != topic_id:
            raise PreviousSnapshotError("previous snapshot belongs to another topic")
        if previous_snapshot.policy_fingerprint != active_policy.fingerprint:
            raise PreviousSnapshotError("previous snapshot uses another policy")
        if previous_snapshot.decision_time >= moment:
            raise PreviousSnapshotError("previous snapshot must predate decision_time")

    deduplicated: dict[str, TopicObservation] = {}
    for observation in observations:
        if type(observation) is not TopicObservation:
            raise TypeError("observations must contain TopicObservation records")
        if observation.topic_id != topic_id or observation.topic_name != topic_name:
            raise HotTopicError("observation topic identity does not match the requested topic")
        if (
            observation.event.available_time > moment
            or observation.assignment_available_time > moment
        ):
            raise FutureDataError("observation was unavailable at decision_time")
        event_id = observation.event.event_id
        existing = deduplicated.get(event_id)
        if existing is not None and existing != observation:
            raise ConflictingDuplicateEventError(
                f"conflicting duplicate event observation: {event_id}"
            )
        deduplicated[event_id] = observation

    window_start = moment - timedelta(minutes=active_policy.lookback_minutes)
    recent_start = moment - timedelta(minutes=active_policy.recent_window_minutes)
    eligible = sorted(
        (
            observation
            for observation in deduplicated.values()
            if window_start < observation.assignment_available_time <= moment
        ),
        key=lambda item: item.event.event_id,
    )
    stale_count = len(deduplicated) - len(eligible)
    recent = [item for item in eligible if item.assignment_available_time > recent_start]

    qualities = [_event_quality(item) for item in eligible]
    evidence_quality = _round_ratio(sum(qualities), len(qualities)) if qualities else 0
    window_microseconds = active_policy.lookback_minutes * 60 * 1_000_000
    recencies = [
        _round_ratio(
            (window_microseconds - _timedelta_microseconds(moment - item.assignment_available_time))
            * 10_000,
            window_microseconds,
        )
        for item in eligible
    ]
    recency = _round_ratio(sum(recencies), len(recencies)) if recencies else 0

    source_ids = {
        evidence.source_id for observation in eligible for evidence in observation.event.evidence
    }
    instrument_ids = {
        instrument_id
        for observation in eligible
        for instrument_id in observation.event.instrument_ids
    }
    sector_ids = {
        sector_id for observation in eligible for sector_id in observation.event.sector_ids
    }
    source_diversity = min(
        10_000,
        _round_ratio(
            len(source_ids) * 10_000,
            active_policy.source_saturation_count,
        ),
    )
    breadth = min(
        10_000,
        len(instrument_ids) * active_policy.breadth_instrument_step_bps
        + len(sector_ids) * active_policy.breadth_sector_step_bps,
    )

    if eligible:
        recent_quality_sum = sum(_event_quality(item) for item in recent)
        prior_quality_sum = sum(
            _event_quality(item)
            for item in eligible
            if item.assignment_available_time <= recent_start
        )
        prior_minutes = active_policy.lookback_minutes - active_policy.recent_window_minutes
        equivalent_prior_sum = _round_ratio(
            prior_quality_sum * active_policy.recent_window_minutes,
            prior_minutes,
        )
        recent_intensity = min(
            10_000,
            _round_ratio(recent_quality_sum, active_policy.activity_saturation_events),
        )
        prior_intensity = min(
            10_000,
            _round_ratio(equivalent_prior_sum, active_policy.activity_saturation_events),
        )
        momentum = max(
            0,
            min(10_000, 5_000 + _round_ratio(recent_intensity - prior_intensity, 2)),
        )
    else:
        momentum = 0

    components = HotScoreComponents(
        evidence_quality_bps=evidence_quality,
        recency_bps=recency,
        source_diversity_bps=source_diversity,
        breadth_bps=breadth,
        momentum_bps=momentum,
    )
    score = _round_ratio(
        evidence_quality * active_policy.quality_weight_bps
        + recency * active_policy.recency_weight_bps
        + source_diversity * active_policy.source_diversity_weight_bps
        + breadth * active_policy.breadth_weight_bps
        + momentum * active_policy.momentum_weight_bps,
        10_000,
    )
    sample_factor = min(10_000, _round_ratio(len(eligible) * 10_000, 4))
    confidence_base = _round_ratio(evidence_quality * 3 + source_diversity, 4)
    confidence = _round_ratio(confidence_base * sample_factor, 10_000)
    return HotTopicSnapshot(
        topic_id=topic_id,
        topic_name=topic_name,
        lifecycle=_lifecycle(
            score_bps=score,
            event_count=len(eligible),
            policy=active_policy,
            previous=previous_snapshot,
        ),
        decision_time=moment,
        window_start=window_start,
        window_end=moment,
        score_bps=score,
        confidence_bps=confidence,
        components=components,
        event_count=len(eligible),
        recent_event_count=len(recent),
        stale_event_count=stale_count,
        source_count=len(source_ids),
        instrument_count=len(instrument_ids),
        sector_count=len(sector_ids),
        event_ids=tuple(item.event.event_id for item in eligible),
        policy_fingerprint=active_policy.fingerprint,
        previous_snapshot_id=(
            previous_snapshot.snapshot_id if previous_snapshot is not None else None
        ),
    )


__all__ = [
    "ConflictingDuplicateEventError",
    "FutureDataError",
    "HotTopicError",
    "PreviousSnapshotError",
    "build_hot_topic_snapshot",
]
