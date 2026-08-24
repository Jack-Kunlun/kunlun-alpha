"""Immutable HotTopic observations, policy, components, and snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from event_core.models import MarketEvent

HOT_SCORE_VERSION = "hot-score-v1"
TOPIC_ASSIGNMENT_VERSION = "topic-assignment-v1"

_COORDINATE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")


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


def _strict_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be a strict integer")
    return value


def _basis_points(value: object, field_name: str) -> int:
    result = _strict_integer(value, field_name)
    if not 0 <= result <= 10_000:
        raise ValueError(f"{field_name} must be between 0 and 10000")
    return result


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class TopicLifecycle(str, Enum):
    EMERGING = "EMERGING"
    RISING = "RISING"
    HOT = "HOT"
    COOLING = "COOLING"
    DORMANT = "DORMANT"


@dataclass(frozen=True, slots=True)
class HotScorePolicy:
    """All HotScore V1 behavior-affecting parameters."""

    version: str = HOT_SCORE_VERSION
    lookback_minutes: int = 1_440
    recent_window_minutes: int = 360
    source_saturation_count: int = 4
    activity_saturation_events: int = 8
    breadth_instrument_step_bps: int = 2_000
    breadth_sector_step_bps: int = 1_000
    quality_weight_bps: int = 4_000
    recency_weight_bps: int = 2_000
    source_diversity_weight_bps: int = 1_500
    breadth_weight_bps: int = 1_000
    momentum_weight_bps: int = 1_500
    rising_threshold_bps: int = 4_500
    hot_threshold_bps: int = 7_000
    cooling_drop_bps: int = 500
    minimum_hot_events: int = 2
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.version != HOT_SCORE_VERSION:
            raise ValueError(f"version must be {HOT_SCORE_VERSION!r}")
        integer_fields = {
            "activity_saturation_events": self.activity_saturation_events,
            "breadth_instrument_step_bps": self.breadth_instrument_step_bps,
            "breadth_sector_step_bps": self.breadth_sector_step_bps,
            "cooling_drop_bps": self.cooling_drop_bps,
            "hot_threshold_bps": self.hot_threshold_bps,
            "lookback_minutes": self.lookback_minutes,
            "minimum_hot_events": self.minimum_hot_events,
            "recent_window_minutes": self.recent_window_minutes,
            "rising_threshold_bps": self.rising_threshold_bps,
            "source_saturation_count": self.source_saturation_count,
        }
        for field_name, value in integer_fields.items():
            _strict_integer(value, field_name)
        if self.lookback_minutes <= 0:
            raise ValueError("lookback_minutes must be positive")
        if not 0 < self.recent_window_minutes < self.lookback_minutes:
            raise ValueError("recent_window_minutes must be inside the lookback window")
        if self.source_saturation_count <= 0 or self.activity_saturation_events <= 0:
            raise ValueError("saturation counts must be positive")
        if self.minimum_hot_events <= 0:
            raise ValueError("minimum_hot_events must be positive")
        for field_name in (
            "breadth_instrument_step_bps",
            "breadth_sector_step_bps",
            "cooling_drop_bps",
            "hot_threshold_bps",
            "rising_threshold_bps",
        ):
            _basis_points(getattr(self, field_name), field_name)
        if self.rising_threshold_bps >= self.hot_threshold_bps:
            raise ValueError("rising threshold must be lower than hot threshold")
        weights = {
            "breadthWeightBps": _basis_points(self.breadth_weight_bps, "breadth_weight_bps"),
            "momentumWeightBps": _basis_points(self.momentum_weight_bps, "momentum_weight_bps"),
            "qualityWeightBps": _basis_points(self.quality_weight_bps, "quality_weight_bps"),
            "recencyWeightBps": _basis_points(self.recency_weight_bps, "recency_weight_bps"),
            "sourceDiversityWeightBps": _basis_points(
                self.source_diversity_weight_bps,
                "source_diversity_weight_bps",
            ),
        }
        if sum(weights.values()) != 10_000:
            raise ValueError("HotScore component weights must sum to 10000")
        object.__setattr__(
            self,
            "fingerprint",
            _fingerprint(
                {
                    "activitySaturationEvents": self.activity_saturation_events,
                    "breadthInstrumentStepBps": self.breadth_instrument_step_bps,
                    "breadthSectorStepBps": self.breadth_sector_step_bps,
                    "coolingDropBps": self.cooling_drop_bps,
                    "hotThresholdBps": self.hot_threshold_bps,
                    "lookbackMinutes": self.lookback_minutes,
                    "minimumHotEvents": self.minimum_hot_events,
                    "recentWindowMinutes": self.recent_window_minutes,
                    "risingThresholdBps": self.rising_threshold_bps,
                    "sourceSaturationCount": self.source_saturation_count,
                    "version": self.version,
                    **weights,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TopicObservation:
    """Versioned topic assignment for one immutable MarketEvent."""

    event: MarketEvent
    topic_id: str
    topic_name: str
    relevance_bps: int
    assignment_version: str
    assignment_fingerprint: str
    assignment_available_time: datetime

    def __post_init__(self) -> None:
        if type(self.event) is not MarketEvent:
            raise TypeError("event must be a MarketEvent")
        _coordinate(self.topic_id, "topic_id")
        _text(self.topic_name, "topic_name", maximum=200)
        _basis_points(self.relevance_bps, "relevance_bps")
        _coordinate(self.assignment_version, "assignment_version")
        assignment_fingerprint = _text(
            self.assignment_fingerprint,
            "assignment_fingerprint",
        )
        if _HEX_64.fullmatch(assignment_fingerprint) is None:
            raise ValueError("assignment_fingerprint must be a lowercase SHA-256 digest")
        available_time = _aware_utc(
            self.assignment_available_time,
            "assignment_available_time",
        )
        if available_time < self.event.available_time:
            raise ValueError("topic assignment cannot predate its event")
        object.__setattr__(self, "assignment_available_time", available_time)


@dataclass(frozen=True, slots=True)
class HotScoreComponents:
    evidence_quality_bps: int
    recency_bps: int
    source_diversity_bps: int
    breadth_bps: int
    momentum_bps: int

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_quality_bps",
            "recency_bps",
            "source_diversity_bps",
            "breadth_bps",
            "momentum_bps",
        ):
            _basis_points(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class HotTopicSnapshot:
    """Immutable point-in-time topic score and lifecycle state."""

    topic_id: str
    topic_name: str
    lifecycle: TopicLifecycle
    decision_time: datetime
    window_start: datetime
    window_end: datetime
    score_bps: int
    confidence_bps: int
    components: HotScoreComponents
    event_count: int
    recent_event_count: int
    stale_event_count: int
    source_count: int
    instrument_count: int
    sector_count: int
    event_ids: tuple[str, ...]
    policy_fingerprint: str
    previous_snapshot_id: str | None = None
    algorithm_version: str = HOT_SCORE_VERSION
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        _coordinate(self.topic_id, "topic_id")
        _text(self.topic_name, "topic_name", maximum=200)
        if type(self.lifecycle) is not TopicLifecycle:
            raise TypeError("lifecycle must be a TopicLifecycle")
        decision_time = _aware_utc(self.decision_time, "decision_time")
        window_start = _aware_utc(self.window_start, "window_start")
        window_end = _aware_utc(self.window_end, "window_end")
        if not window_start < window_end or window_end != decision_time:
            raise ValueError("window must end at decision_time and have positive width")
        _basis_points(self.score_bps, "score_bps")
        _basis_points(self.confidence_bps, "confidence_bps")
        if type(self.components) is not HotScoreComponents:
            raise TypeError("components must be HotScoreComponents")
        for field_name in (
            "event_count",
            "recent_event_count",
            "stale_event_count",
            "source_count",
            "instrument_count",
            "sector_count",
        ):
            value = _strict_integer(getattr(self, field_name), field_name)
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.recent_event_count > self.event_count:
            raise ValueError("recent_event_count cannot exceed event_count")
        if type(self.event_ids) is not tuple:
            raise TypeError("event_ids must be a tuple")
        if self.event_ids != tuple(sorted(self.event_ids)) or len(set(self.event_ids)) != len(
            self.event_ids
        ):
            raise ValueError("event_ids must be sorted and unique")
        if len(self.event_ids) != self.event_count:
            raise ValueError("event_count must equal the number of event_ids")
        policy_fingerprint = _text(self.policy_fingerprint, "policy_fingerprint")
        if _HEX_64.fullmatch(policy_fingerprint) is None:
            raise ValueError("policy_fingerprint must be a lowercase SHA-256 digest")
        if self.previous_snapshot_id is not None:
            previous = _text(self.previous_snapshot_id, "previous_snapshot_id")
            if _HEX_64.fullmatch(previous) is None:
                raise ValueError("previous_snapshot_id must be a lowercase SHA-256 digest")
        if self.algorithm_version != HOT_SCORE_VERSION:
            raise ValueError(f"algorithm_version must be {HOT_SCORE_VERSION!r}")
        object.__setattr__(self, "decision_time", decision_time)
        object.__setattr__(self, "window_start", window_start)
        object.__setattr__(self, "window_end", window_end)
        object.__setattr__(
            self,
            "snapshot_id",
            _fingerprint(
                {
                    "algorithmVersion": self.algorithm_version,
                    "components": {
                        "breadthBps": self.components.breadth_bps,
                        "evidenceQualityBps": self.components.evidence_quality_bps,
                        "momentumBps": self.components.momentum_bps,
                        "recencyBps": self.components.recency_bps,
                        "sourceDiversityBps": self.components.source_diversity_bps,
                    },
                    "confidenceBps": self.confidence_bps,
                    "decisionTime": _timestamp(decision_time),
                    "eventCount": self.event_count,
                    "eventIds": list(self.event_ids),
                    "instrumentCount": self.instrument_count,
                    "lifecycle": self.lifecycle.value,
                    "policyFingerprint": self.policy_fingerprint,
                    "previousSnapshotId": self.previous_snapshot_id,
                    "recentEventCount": self.recent_event_count,
                    "scoreBps": self.score_bps,
                    "sectorCount": self.sector_count,
                    "sourceCount": self.source_count,
                    "staleEventCount": self.stale_event_count,
                    "topicId": self.topic_id,
                    "topicName": self.topic_name,
                    "windowEnd": _timestamp(window_end),
                    "windowStart": _timestamp(window_start),
                }
            ),
        )


__all__ = [
    "HOT_SCORE_VERSION",
    "TOPIC_ASSIGNMENT_VERSION",
    "HotScoreComponents",
    "HotScorePolicy",
    "HotTopicSnapshot",
    "TopicLifecycle",
    "TopicObservation",
]
