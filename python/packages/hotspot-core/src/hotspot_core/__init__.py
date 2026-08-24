"""Point-in-time HotTopic aggregation and deterministic HotScore V1."""

from hotspot_core.models import (
    HOT_SCORE_VERSION,
    TOPIC_ASSIGNMENT_VERSION,
    HotScoreComponents,
    HotScorePolicy,
    HotTopicSnapshot,
    TopicLifecycle,
    TopicObservation,
)
from hotspot_core.scoring import (
    ConflictingDuplicateEventError,
    FutureDataError,
    HotTopicError,
    PreviousSnapshotError,
    build_hot_topic_snapshot,
)

__all__ = [
    "HOT_SCORE_VERSION",
    "TOPIC_ASSIGNMENT_VERSION",
    "ConflictingDuplicateEventError",
    "FutureDataError",
    "HotScoreComponents",
    "HotScorePolicy",
    "HotTopicError",
    "HotTopicSnapshot",
    "PreviousSnapshotError",
    "TopicLifecycle",
    "TopicObservation",
    "build_hot_topic_snapshot",
]
