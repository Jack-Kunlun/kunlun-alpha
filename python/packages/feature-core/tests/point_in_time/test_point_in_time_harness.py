from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import permutations

import pytest

from .harness import (
    AmbiguousRevisionError,
    ClockLeakageError,
    FrozenClock,
    FutureDataLeakageError,
    MissingUniverseSnapshotError,
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
    synthetic_point_in_time_scenario,
)


def _feature(
    scenario: PointInTimeScenario,
    revision_id: str,
) -> SyntheticFeatureRevision:
    return next(
        revision for revision in scenario.feature_revisions if revision.revision_id == revision_id
    )


def _manual_safe_resolver(
    scenario: PointInTimeScenario,
    clock: FrozenClock,
) -> ResolvedPointInTimeSnapshot:
    selected = (
        _feature(scenario, "delisted-visible-v1"),
        _feature(scenario, "momentum-visible-v1"),
    )
    return ResolvedPointInTimeSnapshot(
        decision_time=clock.now(),
        feature_revisions=tuple(sorted(selected, key=lambda revision: revision.sample_key)),
        universe_entity_ids=("000001.SZ", "600519.SH"),
    )


def test_oracle_matches_an_independently_enumerated_safe_snapshot() -> None:
    scenario = synthetic_point_in_time_scenario()
    manual = _manual_safe_resolver(scenario, FrozenClock(scenario.decision_time))

    assert expected_snapshot(scenario, FrozenClock(scenario.decision_time)) == manual
    assert assert_point_in_time_safe(_manual_safe_resolver, scenario) == manual
    assert all(
        revision.value_checksum.startswith("sha256:") for revision in manual.feature_revisions
    )
    assert all(
        revision.lineage_checksum.startswith("sha256:") and revision.source_snapshot_version
        for revision in manual.feature_revisions
    )


def test_injected_future_available_data_fails_the_point_in_time_assertion() -> None:
    scenario = synthetic_point_in_time_scenario()

    def future_injecting_resolver(
        candidate: PointInTimeScenario,
        clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        baseline = _manual_safe_resolver(candidate, clock)
        future = _feature(candidate, "future-only-v1")
        return replace(
            baseline,
            feature_revisions=(*baseline.feature_revisions, future),
        )

    with pytest.raises(FutureDataLeakageError, match="unavailable"):
        assert_point_in_time_safe(future_injecting_resolver, scenario)


def test_processing_only_future_data_fails_even_when_already_available() -> None:
    scenario = synthetic_point_in_time_scenario()
    processing_only = _feature(scenario, "processing-only-v1")
    assert processing_only.available_time <= scenario.decision_time
    assert scenario.decision_time < processing_only.processing_time

    def available_only_resolver(
        candidate: PointInTimeScenario,
        clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        baseline = _manual_safe_resolver(candidate, clock)
        return replace(
            baseline,
            feature_revisions=(*baseline.feature_revisions, processing_only),
        )

    with pytest.raises(FutureDataLeakageError, match="unprocessed"):
        assert_point_in_time_safe(available_only_resolver, scenario)


def test_post_decision_revision_fails_even_when_event_timestamps_match() -> None:
    scenario = synthetic_point_in_time_scenario()
    visible = _feature(scenario, "momentum-visible-v1")
    revised = _feature(scenario, "momentum-revised-v2")
    assert revised.event_time == visible.event_time

    def latest_revision_resolver(
        candidate: PointInTimeScenario,
        clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        baseline = _manual_safe_resolver(candidate, clock)
        selected = tuple(
            revised if revision.sample_key == visible.sample_key else revision
            for revision in baseline.feature_revisions
        )
        return replace(baseline, feature_revisions=selected)

    with pytest.raises(RevisionLeakageError, match="same event timestamp"):
        assert_point_in_time_safe(latest_revision_resolver, scenario)


def test_current_universe_fails_for_later_backfilled_delisting() -> None:
    scenario = synthetic_point_in_time_scenario()

    def current_universe_resolver(
        candidate: PointInTimeScenario,
        clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        baseline = _manual_safe_resolver(candidate, clock)
        return replace(
            baseline,
            feature_revisions=tuple(
                revision
                for revision in baseline.feature_revisions
                if revision.entity_id == "600519.SH"
            ),
            universe_entity_ids=("600519.SH",),
        )

    with pytest.raises(SurvivorshipBiasError, match="current"):
        assert_point_in_time_safe(current_universe_resolver, scenario)


def test_known_empty_universe_is_distinct_from_missing_snapshot() -> None:
    scenario = synthetic_point_in_time_scenario()
    known_empty = replace(scenario, membership_revisions=())
    expected_empty = ResolvedPointInTimeSnapshot(
        decision_time=scenario.decision_time,
        feature_revisions=(),
        universe_entity_ids=(),
    )

    assert expected_snapshot(known_empty, FrozenClock(scenario.decision_time)) == expected_empty
    assert (
        assert_point_in_time_safe(lambda _scenario, _clock: expected_empty, known_empty)
        == expected_empty
    )

    missing = replace(
        known_empty,
        membership_snapshot_state=MembershipSnapshotState.MISSING,
    )
    with pytest.raises(MissingUniverseSnapshotError, match="missing"):
        assert_point_in_time_safe(lambda _scenario, _clock: expected_empty, missing)


def test_same_visible_time_with_conflicting_revisions_fails_closed() -> None:
    scenario = synthetic_point_in_time_scenario()
    visible = _feature(scenario, "momentum-visible-v1")
    ambiguous = SyntheticFeatureRevision.create(
        entity_id=visible.entity_id,
        feature_name=visible.feature_name,
        event_time=visible.event_time,
        available_time=visible.available_time,
        processing_time=visible.processing_time,
        revision_id="momentum-ambiguous-v2",
        value="0.99",
        source_snapshot_version="ambiguous-source-v2",
    )
    conflict = replace(
        scenario,
        feature_revisions=(*scenario.feature_revisions, ambiguous),
    )

    with pytest.raises(AmbiguousRevisionError, match="latest visible time bucket"):
        expected_snapshot(conflict, FrozenClock(scenario.decision_time))


def test_latest_visibility_bucket_is_permutation_invariant() -> None:
    scenario = synthetic_point_in_time_scenario()
    visible = _feature(scenario, "momentum-visible-v1")
    ambiguous = SyntheticFeatureRevision.create(
        entity_id=visible.entity_id,
        feature_name=visible.feature_name,
        event_time=visible.event_time,
        available_time=visible.available_time,
        processing_time=visible.processing_time,
        revision_id="momentum-old-conflict-v2",
        value="0.50",
        source_snapshot_version="old-conflict-v2",
    )
    newer = SyntheticFeatureRevision.create(
        entity_id=visible.entity_id,
        feature_name=visible.feature_name,
        event_time=visible.event_time,
        available_time=visible.available_time + timedelta(hours=1),
        processing_time=visible.processing_time + timedelta(hours=1),
        revision_id="momentum-later-unique-v3",
        value="0.06",
        source_snapshot_version="later-unique-v3",
    )
    unrelated = tuple(
        revision
        for revision in scenario.feature_revisions
        if revision.revision_id != visible.revision_id
    )

    for ordering in permutations((visible, ambiguous)):
        conflict = replace(
            scenario,
            feature_revisions=(*unrelated, *ordering),
        )
        with pytest.raises(AmbiguousRevisionError):
            expected_snapshot(conflict, FrozenClock(scenario.decision_time))

    for ordering in permutations((visible, ambiguous, newer)):
        resolved = expected_snapshot(
            replace(scenario, feature_revisions=(*unrelated, *ordering)),
            FrozenClock(scenario.decision_time),
        )
        selected = next(
            revision
            for revision in resolved.feature_revisions
            if revision.sample_key == visible.sample_key
        )
        assert selected == newer


def test_duplicate_payload_is_idempotent_but_same_revision_id_conflict_fails() -> None:
    scenario = synthetic_point_in_time_scenario()
    visible = _feature(scenario, "momentum-visible-v1")
    duplicate = replace(
        scenario,
        feature_revisions=(*scenario.feature_revisions, visible),
    )
    assert expected_snapshot(
        duplicate, FrozenClock(scenario.decision_time)
    ) == _manual_safe_resolver(
        scenario,
        FrozenClock(scenario.decision_time),
    )

    conflicting_payload = SyntheticFeatureRevision.create(
        entity_id=visible.entity_id,
        feature_name=visible.feature_name,
        event_time=visible.event_time,
        available_time=visible.available_time,
        processing_time=visible.processing_time,
        revision_id=visible.revision_id,
        value="0.99",
        source_snapshot_version="conflicting-source-v2",
    )
    conflict = replace(
        scenario,
        feature_revisions=(*scenario.feature_revisions, conflicting_payload),
    )
    with pytest.raises(RevisionIdentityConflictError, match="conflicting"):
        expected_snapshot(conflict, FrozenClock(scenario.decision_time))


def test_lineage_and_source_snapshot_are_individually_tamper_evident() -> None:
    scenario = synthetic_point_in_time_scenario()
    visible = _feature(scenario, "momentum-visible-v1")

    with pytest.raises(ValueError, match="lineage_checksum"):
        replace(visible, lineage_checksum="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="lineage_checksum"):
        replace(visible, source_snapshot_version="tampered-source-v2")

    source_only_change = SyntheticFeatureRevision.create(
        entity_id=visible.entity_id,
        feature_name=visible.feature_name,
        event_time=visible.event_time,
        available_time=visible.available_time,
        processing_time=visible.processing_time,
        revision_id=visible.revision_id,
        value=visible.value,
        source_snapshot_version="changed-source-v2",
    )
    conflict = replace(
        scenario,
        feature_revisions=(*scenario.feature_revisions, source_only_change),
    )
    with pytest.raises(RevisionIdentityConflictError, match="conflicting"):
        expected_snapshot(conflict, FrozenClock(scenario.decision_time))


def test_wall_clock_label_and_masked_wall_clock_selection_both_fail() -> None:
    scenario = synthetic_point_in_time_scenario()

    def exposed_wall_clock_resolver(
        candidate: PointInTimeScenario,
        _clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        return expected_snapshot(candidate, FrozenClock(candidate.present_time))

    with pytest.raises(ClockLeakageError, match="wall-clock"):
        assert_point_in_time_safe(exposed_wall_clock_resolver, scenario)

    def masked_wall_clock_resolver(
        candidate: PointInTimeScenario,
        clock: FrozenClock,
    ) -> ResolvedPointInTimeSnapshot:
        current = expected_snapshot(candidate, FrozenClock(candidate.present_time))
        return replace(current, decision_time=clock.now())

    with pytest.raises(PointInTimeViolationError):
        assert_point_in_time_safe(masked_wall_clock_resolver, scenario)
