from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from .scenarios import (
    MembershipSnapshotState,
    PointInTimeScenario,
    ResolvedPointInTimeSnapshot,
    SyntheticFeatureRevision,
    SyntheticMembershipRevision,
)


class PointInTimeViolationError(AssertionError):
    pass


class FutureDataLeakageError(PointInTimeViolationError):
    pass


class RevisionLeakageError(PointInTimeViolationError):
    pass


class RevisionIdentityConflictError(RevisionLeakageError):
    pass


class AmbiguousRevisionError(RevisionLeakageError):
    pass


class SurvivorshipBiasError(PointInTimeViolationError):
    pass


class MissingUniverseSnapshotError(SurvivorshipBiasError):
    pass


class ClockLeakageError(PointInTimeViolationError):
    pass


@dataclass(frozen=True, slots=True)
class FrozenClock:
    decision_time: datetime

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None:
            raise ValueError("frozen decision_time must be timezone-aware")

    def now(self) -> datetime:
        return self.decision_time


type PointInTimeResolver = Callable[
    [PointInTimeScenario, FrozenClock],
    ResolvedPointInTimeSnapshot,
]


def _validate_revision_identities(scenario: PointInTimeScenario) -> None:
    revisions: tuple[object, ...] = (
        *scenario.feature_revisions,
        *scenario.membership_revisions,
    )
    by_revision_id: dict[str, object] = {}
    for revision in revisions:
        revision_id = revision.revision_id
        prior = by_revision_id.get(revision_id)
        if prior is not None and prior != revision:
            raise RevisionIdentityConflictError(
                "one revision_id identifies conflicting synthetic payloads"
            )
        by_revision_id[revision_id] = revision


def _latest_memberships(
    scenario: PointInTimeScenario,
    decision_time: datetime,
) -> dict[str, SyntheticMembershipRevision]:
    grouped: dict[str, list[SyntheticMembershipRevision]] = {}
    for revision in scenario.membership_revisions:
        if revision.visible_at(decision_time):
            grouped.setdefault(revision.entity_id, []).append(revision)
    latest: dict[str, SyntheticMembershipRevision] = {}
    for entity_id, revisions in grouped.items():
        latest_time = max(revision.visibility_order for revision in revisions)
        latest_bucket = {
            revision for revision in revisions if revision.visibility_order == latest_time
        }
        if len(latest_bucket) != 1:
            raise AmbiguousRevisionError(
                "membership revisions conflict in the latest visible time bucket"
            )
        latest[entity_id] = next(iter(latest_bucket))
    return latest


def _latest_features(
    scenario: PointInTimeScenario,
    decision_time: datetime,
    universe_entity_ids: set[str],
) -> dict[tuple[str, str, datetime], SyntheticFeatureRevision]:
    grouped: dict[tuple[str, str, datetime], list[SyntheticFeatureRevision]] = {}
    for revision in scenario.feature_revisions:
        if revision.entity_id not in universe_entity_ids or not revision.visible_at(decision_time):
            continue
        grouped.setdefault(revision.sample_key, []).append(revision)
    latest: dict[tuple[str, str, datetime], SyntheticFeatureRevision] = {}
    for sample_key, revisions in grouped.items():
        latest_time = max(revision.visibility_order for revision in revisions)
        latest_bucket = {
            revision for revision in revisions if revision.visibility_order == latest_time
        }
        if len(latest_bucket) != 1:
            raise AmbiguousRevisionError(
                "feature revisions conflict in the latest visible time bucket"
            )
        latest[sample_key] = next(iter(latest_bucket))
    return latest


def expected_snapshot(
    scenario: PointInTimeScenario,
    clock: FrozenClock,
) -> ResolvedPointInTimeSnapshot:
    _validate_revision_identities(scenario)
    if scenario.membership_snapshot_state is MembershipSnapshotState.MISSING:
        raise MissingUniverseSnapshotError(
            "membership snapshot is missing at the frozen decision_time"
        )
    decision_time = clock.now()
    memberships = _latest_memberships(scenario, decision_time)
    universe = {
        entity_id
        for entity_id, revision in memberships.items()
        if revision.active_at(decision_time)
    }
    features = _latest_features(scenario, decision_time, universe)
    return ResolvedPointInTimeSnapshot(
        decision_time=decision_time,
        feature_revisions=tuple(features[key] for key in sorted(features)),
        universe_entity_ids=tuple(sorted(universe)),
    )


def _feature_map(
    revisions: tuple[SyntheticFeatureRevision, ...],
    field: str,
) -> dict[tuple[str, str, datetime], SyntheticFeatureRevision]:
    result: dict[tuple[str, str, datetime], SyntheticFeatureRevision] = {}
    for candidate in revisions:
        if type(cast(object, candidate)) is not SyntheticFeatureRevision:
            raise PointInTimeViolationError(f"{field} contains an invalid revision type")
        prior = result.get(candidate.sample_key)
        if prior is not None and prior != candidate:
            raise PointInTimeViolationError(f"{field} contains conflicting sample keys")
        result[candidate.sample_key] = candidate
    return result


def assert_point_in_time_safe(
    resolver: PointInTimeResolver,
    scenario: PointInTimeScenario,
) -> ResolvedPointInTimeSnapshot:
    clock = FrozenClock(scenario.decision_time)
    expected = expected_snapshot(scenario, clock)
    actual = resolver(scenario, clock)
    if type(cast(object, actual)) is not ResolvedPointInTimeSnapshot:
        raise PointInTimeViolationError("resolver returned an invalid snapshot type")
    if actual.decision_time != clock.now():
        raise ClockLeakageError("resolver used a wall-clock or non-frozen decision_time")
    actual_universe = tuple(sorted(actual.universe_entity_ids))
    if len(actual_universe) != len(set(actual_universe)):
        raise SurvivorshipBiasError("resolver returned duplicate universe entities")
    if actual_universe != expected.universe_entity_ids:
        raise SurvivorshipBiasError(
            "resolver used a current or otherwise non-point-in-time universe"
        )

    known_revisions = {revision.revision_id: revision for revision in scenario.feature_revisions}
    for revision in actual.feature_revisions:
        if known_revisions.get(revision.revision_id) != revision:
            raise RevisionIdentityConflictError(
                "resolver returned an unknown or conflicting revision payload"
            )
    expected_features = _feature_map(expected.feature_revisions, "oracle snapshot")
    actual_features = _feature_map(actual.feature_revisions, "resolver snapshot")
    for sample_key in expected_features.keys() & actual_features.keys():
        if actual_features[sample_key] != expected_features[sample_key]:
            raise RevisionLeakageError(
                "resolver selected a different revision for the same event timestamp"
            )
    extra_keys = actual_features.keys() - expected_features.keys()
    if extra_keys:
        leaked = tuple(actual_features[key] for key in sorted(extra_keys))
        if any(not revision.visible_at(clock.now()) for revision in leaked):
            raise FutureDataLeakageError(
                "resolver admitted data unavailable or unprocessed at decision_time"
            )
        raise PointInTimeViolationError("resolver returned samples outside the PIT oracle")
    missing_keys = expected_features.keys() - actual_features.keys()
    if missing_keys:
        raise PointInTimeViolationError("resolver omitted samples visible at decision_time")
    return actual
