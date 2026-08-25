"""Reusable point-in-time safety fixtures for feature and research tests."""

from .harness import (
    AmbiguousRevisionError,
    ClockLeakageError,
    FrozenClock,
    FutureDataLeakageError,
    MissingUniverseSnapshotError,
    PointInTimeResolver,
    PointInTimeViolationError,
    RevisionIdentityConflictError,
    RevisionLeakageError,
    SurvivorshipBiasError,
    assert_point_in_time_safe,
    expected_snapshot,
)
from .scenarios import (
    MembershipSnapshotState,
    PointInTimeScenario,
    ResolvedPointInTimeSnapshot,
    SyntheticFeatureRevision,
    SyntheticMembershipRevision,
    synthetic_point_in_time_scenario,
)

__all__ = [
    "AmbiguousRevisionError",
    "ClockLeakageError",
    "FrozenClock",
    "FutureDataLeakageError",
    "MembershipSnapshotState",
    "MissingUniverseSnapshotError",
    "PointInTimeResolver",
    "PointInTimeScenario",
    "PointInTimeViolationError",
    "ResolvedPointInTimeSnapshot",
    "RevisionIdentityConflictError",
    "RevisionLeakageError",
    "SurvivorshipBiasError",
    "SyntheticFeatureRevision",
    "SyntheticMembershipRevision",
    "assert_point_in_time_safe",
    "expected_snapshot",
    "synthetic_point_in_time_scenario",
]
