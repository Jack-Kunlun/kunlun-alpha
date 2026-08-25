from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from quant_core.research.events import (
    EVENT_STUDY_ALGORITHM_VERSION,
    BenchmarkSpec,
    ClusteredObservation,
    ClusterInferenceStatus,
    ControlCohortSnapshot,
    EventCandidate,
    EventCandidateSnapshot,
    EventDropReason,
    EventEligibilitySnapshot,
    EventFutureDataError,
    EventResearchInputError,
    EventResearchStatus,
    EventSelectionField,
    EventSelectionRule,
    EventStudyPolicy,
    EventWindow,
    EventWindowSchedule,
    EventWindowSession,
    NonTradablePolicy,
    OverlapPolicy,
    ReturnPath,
    ReturnPoint,
    ReturnSemantics,
    TradingStatus,
    analyze_event_study,
    clustered_mean,
)

BASE = datetime(2026, 1, 1, 8, tzinfo=UTC)
CUTOFF = BASE + timedelta(days=120)
WINDOW = EventWindow(start_offset_sessions=-1, end_offset_sessions=1)
RULE = EventSelectionRule(
    rule_version="1.0.0",
    effective_time=BASE - timedelta(days=1),
    available_time=BASE - timedelta(days=1),
    processing_time=BASE - timedelta(days=1),
    required_fields=(("event_type", "earnings"),),
)
POLICY = EventStudyPolicy(
    window=WINDOW,
    overlap_policy=OverlapPolicy.EXCLUDE_ALL_SAME_ENTITY_OVERLAP,
    non_tradable_policy=NonTradablePolicy.EXCLUDE_EVENT,
    min_controls_per_event=2,
)
BENCHMARK = BenchmarkSpec(
    benchmark_id="000300.SH",
    benchmark_version="1.0.0",
    source_id="market-daily",
    source_version="1.0.0",
    data_version="2026.01",
    schema_version="1.0.0",
    calendar_version="sse-2026.1",
    return_semantics=ReturnSemantics.ADJUSTED_CLOSE,
)


def _path(
    entity_id: str,
    event_time: datetime,
    values: tuple[Decimal, ...],
    *,
    offsets: tuple[int, ...] = (-1, 0, 1),
    statuses: dict[int, TradingStatus] | None = None,
    unavailable_offset: int | None = None,
) -> ReturnPath:
    anchor_time = event_time + timedelta(days=1)
    return ReturnPath(
        entity_id=entity_id,
        points=tuple(
            ReturnPoint(
                relative_session=offset,
                session_time=anchor_time + timedelta(days=offset),
                available_time=(
                    CUTOFF + timedelta(seconds=1)
                    if offset == unavailable_offset
                    else anchor_time + timedelta(days=offset, hours=1)
                ),
                processing_time=(
                    CUTOFF + timedelta(minutes=1)
                    if offset == unavailable_offset
                    else anchor_time + timedelta(days=offset, hours=1, minutes=1)
                ),
                return_value=value,
                trading_status=(statuses or {}).get(offset, TradingStatus.TRADABLE),
                source_id=f"daily-return:{entity_id}",
                source_version="1.0.0",
                return_semantics=ReturnSemantics.ADJUSTED_CLOSE,
            )
            for offset, value in zip(offsets, values, strict=True)
        ),
    )


def _candidate(
    *,
    event_id: str,
    entity_id: str,
    period_days: int,
    cluster_id: str,
    cumulative_abnormal_return: Decimal = Decimal("0.03"),
    event_type: str = "earnings",
    statuses: dict[int, TradingStatus] | None = None,
    unavailable_offset: int | None = None,
    control_count: int = 2,
) -> EventCandidate:
    event_time = BASE + timedelta(days=period_days)
    anchor_time = event_time + timedelta(days=1)
    per_session = cumulative_abnormal_return / Decimal(3)
    controls = tuple(
        _path(
            f"control-{event_id}-{index}",
            event_time,
            (Decimal(0), Decimal(0), Decimal(0)),
        )
        for index in range(control_count)
    )
    return EventCandidate(
        event_id=event_id,
        revision_id="1.0.0",
        entity_id=entity_id,
        event_time=event_time,
        publish_time=event_time + timedelta(minutes=1),
        ingest_time=event_time + timedelta(minutes=2),
        available_time=event_time + timedelta(minutes=3),
        processing_time=event_time + timedelta(minutes=4),
        eligibility_snapshot=EventEligibilitySnapshot(
            snapshot_id=f"eligible:{event_id}",
            snapshot_version="1.0.0",
            as_of_time=event_time,
            available_time=event_time,
            processing_time=event_time,
            is_complete=True,
        ),
        window_schedule=EventWindowSchedule(
            calendar_version="sse-2026.1",
            anchor_predecessor_time=event_time,
            sessions=tuple(
                EventWindowSession(
                    relative_session=offset,
                    session_time=anchor_time + timedelta(days=offset),
                )
                for offset in (-1, 0, 1)
            ),
        ),
        cluster_id=cluster_id,
        cluster_available_time=event_time,
        cluster_processing_time=event_time,
        selection_fields=(
            EventSelectionField(
                name="event_type",
                value=event_type,
                effective_time=event_time,
                available_time=event_time,
                processing_time=event_time,
            ),
        ),
        subject_path=_path(
            entity_id,
            event_time,
            (per_session, per_session, per_session),
            statuses=statuses,
            unavailable_offset=unavailable_offset,
        ),
        benchmark_spec=BENCHMARK,
        benchmark_path=_path(
            BENCHMARK.benchmark_id,
            event_time,
            (Decimal(0), Decimal(0), Decimal(0)),
        ),
        control_cohort=ControlCohortSnapshot(
            snapshot_id=f"controls:{event_id}",
            rule_version="1.0.0",
            universe_version="cn-equity-2026.1",
            available_time=event_time,
            processing_time=event_time,
            members=controls,
        ),
    )


def _snapshot(*candidates: EventCandidate, complete: bool = True) -> EventCandidateSnapshot:
    return EventCandidateSnapshot(
        snapshot_id="events:2026-q1",
        snapshot_version="1.0.0",
        as_of_time=CUTOFF,
        processing_time=CUTOFF,
        is_complete=complete,
        candidates=tuple(candidates),
    )


def test_event_study_selects_pit_candidates_and_reports_clustered_outputs() -> None:
    candidates = (
        _candidate(
            event_id="e1",
            entity_id="600001.SH",
            period_days=0,
            cluster_id="cluster-a",
            cumulative_abnormal_return=Decimal("0.03"),
        ),
        _candidate(
            event_id="e2",
            entity_id="600002.SH",
            period_days=10,
            cluster_id="cluster-a",
            cumulative_abnormal_return=Decimal("0.06"),
        ),
        _candidate(
            event_id="e3",
            entity_id="600003.SH",
            period_days=20,
            cluster_id="cluster-b",
            cumulative_abnormal_return=Decimal("0.09"),
        ),
        _candidate(
            event_id="e4",
            entity_id="600004.SH",
            period_days=30,
            cluster_id="cluster-b",
            cumulative_abnormal_return=Decimal("0.12"),
        ),
        _candidate(
            event_id="not-selected",
            entity_id="600005.SH",
            period_days=40,
            cluster_id="cluster-c",
            event_type="other",
        ),
    )

    result = analyze_event_study(
        _snapshot(*reversed(candidates)),
        selection_rule=RULE,
        policy=POLICY,
        data_cutoff_time=CUTOFF,
    )

    assert result.status is EventResearchStatus.OK
    assert result.algorithm_version == EVENT_STUDY_ALGORITHM_VERSION
    assert result.candidate_count == 5
    assert result.selected_event_count == 4
    assert result.analysis_sample_count == 4
    assert result.cumulative_abnormal_return.mean == Decimal("0.075")
    assert result.cumulative_abnormal_return.standard_error == Decimal("0.03")
    assert result.cumulative_abnormal_return.sample_count == 4
    assert result.cumulative_abnormal_return.cluster_count == 2
    assert (
        result.cumulative_abnormal_return.inference_status
        is ClusterInferenceStatus.SMALL_CLUSTER_COUNT
    )
    assert result.cross_sectional_effect.mean == Decimal("0.075")
    assert [point.relative_session for point in result.relative_session_results] == [
        -1,
        0,
        1,
    ]
    assert all(
        point.average_abnormal_return.mean == Decimal("0.025")
        for point in result.relative_session_results
    )
    assert [sample.event_id for sample in result.samples] == ["e1", "e2", "e3", "e4"]
    assert all(sample.observational_only for sample in result.samples)
    assert result.observational_only
    assert result.selection_rule_available_time == RULE.available_time
    assert all(sample.eligibility_snapshot_id.startswith("eligible:") for sample in result.samples)
    assert all(sample.control_snapshot_id.startswith("controls:") for sample in result.samples)
    assert all(sample.subject_path_provenance.sources for sample in result.samples)
    assert all(sample.logical_available_time >= sample.selection_time for sample in result.samples)
    assert {point.series for point in result.chart_data} == {
        "average_abnormal_return",
        "cumulative_average_abnormal_return",
        "cross_sectional_effect",
    }


def test_post_event_selection_data_and_incomplete_snapshots_fail_closed() -> None:
    candidate = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="cluster-a",
    )
    future_field = replace(
        candidate.selection_fields[0],
        effective_time=candidate.event_time + timedelta(seconds=1),
        available_time=candidate.event_time + timedelta(seconds=1),
        processing_time=candidate.event_time + timedelta(seconds=1),
    )
    late_field = replace(
        candidate.selection_fields[0],
        available_time=candidate.event_time + timedelta(seconds=1),
        processing_time=candidate.event_time + timedelta(seconds=1),
    )

    with pytest.raises(EventFutureDataError, match="post-event selection field"):
        analyze_event_study(
            _snapshot(replace(candidate, selection_fields=(future_field,))),
            selection_rule=RULE,
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )
    with pytest.raises(EventResearchInputError, match="complete candidate snapshot"):
        analyze_event_study(
            _snapshot(candidate, complete=False),
            selection_rule=RULE,
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )
    with pytest.raises(EventFutureDataError, match="post-event selection field"):
        analyze_event_study(
            _snapshot(replace(candidate, selection_fields=(late_field,))),
            selection_rule=RULE,
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )
    with pytest.raises(EventFutureDataError, match="eligibility snapshot"):
        analyze_event_study(
            _snapshot(
                replace(
                    candidate,
                    eligibility_snapshot=replace(
                        candidate.eligibility_snapshot,
                        as_of_time=candidate.event_time + timedelta(seconds=1),
                        available_time=candidate.event_time + timedelta(seconds=1),
                        processing_time=candidate.event_time + timedelta(seconds=1),
                    ),
                )
            ),
            selection_rule=RULE,
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )
    with pytest.raises(EventFutureDataError, match="selection rule"):
        analyze_event_study(
            _snapshot(candidate),
            selection_rule=replace(
                RULE,
                effective_time=candidate.event_time + timedelta(seconds=1),
                available_time=candidate.event_time + timedelta(seconds=1),
                processing_time=candidate.event_time + timedelta(seconds=1),
            ),
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )


def test_same_entity_overlap_is_excluded_before_outcome_validation() -> None:
    first = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="600001.SH",
    )
    second = _candidate(
        event_id="e2",
        entity_id="600001.SH",
        period_days=1,
        cluster_id="600001.SH",
        unavailable_offset=0,
    )

    result = analyze_event_study(
        _snapshot(first, second),
        selection_rule=RULE,
        policy=POLICY,
        data_cutoff_time=CUTOFF,
    )

    assert result.status is EventResearchStatus.NO_VALID_SAMPLES
    assert result.analysis_sample_count == 0
    assert dict(result.drop_counts)[EventDropReason.OVERLAPPING_EVENT_WINDOW] == 2
    assert dict(result.drop_counts)[EventDropReason.OUTCOME_UNAVAILABLE_AT_CUTOFF] == 0


def test_invalid_paths_and_nontradable_samples_are_explicitly_dropped() -> None:
    suspended = _candidate(
        event_id="suspended",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="a",
        statuses={0: TradingStatus.SUSPENDED},
    )
    untradable = _candidate(
        event_id="untradable",
        entity_id="600002.SH",
        period_days=10,
        cluster_id="b",
        statuses={1: TradingStatus.UNTRADABLE},
    )
    incomplete_subject_base = _candidate(
        event_id="subject-missing",
        entity_id="600003.SH",
        period_days=20,
        cluster_id="c",
    )
    incomplete_subject = replace(
        incomplete_subject_base,
        subject_path=replace(
            incomplete_subject_base.subject_path,
            points=incomplete_subject_base.subject_path.points[:-1],
        ),
    )
    incomplete_benchmark_base = _candidate(
        event_id="benchmark-missing",
        entity_id="600004.SH",
        period_days=30,
        cluster_id="d",
    )
    incomplete_benchmark = replace(
        incomplete_benchmark_base,
        benchmark_path=replace(
            incomplete_benchmark_base.benchmark_path,
            points=incomplete_benchmark_base.benchmark_path.points[:-1],
        ),
    )
    insufficient_controls = _candidate(
        event_id="controls-missing",
        entity_id="600005.SH",
        period_days=40,
        cluster_id="e",
        control_count=1,
    )
    unavailable = _candidate(
        event_id="unavailable",
        entity_id="600006.SH",
        period_days=50,
        cluster_id="f",
        unavailable_offset=1,
    )

    result = analyze_event_study(
        _snapshot(
            suspended,
            untradable,
            incomplete_subject,
            incomplete_benchmark,
            insufficient_controls,
            unavailable,
        ),
        selection_rule=RULE,
        policy=POLICY,
        data_cutoff_time=CUTOFF,
    )

    assert result.analysis_sample_count == 0
    drops = dict(result.drop_counts)
    assert drops[EventDropReason.SUSPENDED_WINDOW] == 1
    assert drops[EventDropReason.UNTRADABLE_WINDOW] == 1
    assert drops[EventDropReason.INCOMPLETE_EVENT_PATH] == 1
    assert drops[EventDropReason.INCOMPLETE_BENCHMARK_PATH] == 1
    assert drops[EventDropReason.INSUFFICIENT_CONTROLS] == 1
    assert drops[EventDropReason.OUTCOME_UNAVAILABLE_AT_CUTOFF] == 1


def test_keep_observed_nontradable_marks_sample_as_non_executable() -> None:
    candidate = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="a",
        statuses={0: TradingStatus.SUSPENDED},
    )
    policy = replace(POLICY, non_tradable_policy=NonTradablePolicy.KEEP_OBSERVED_MARKED)

    result = analyze_event_study(
        _snapshot(candidate),
        selection_rule=RULE,
        policy=policy,
        data_cutoff_time=CUTOFF,
    )

    assert result.analysis_sample_count == 1
    assert result.non_tradable_sample_count == 1
    assert result.samples[0].contains_non_tradable_observation
    assert result.samples[0].observational_only
    assert (
        result.cumulative_abnormal_return.inference_status
        is ClusterInferenceStatus.INSUFFICIENT_EVENT_SAMPLES
    )


def test_every_window_session_must_match_the_versioned_schedule() -> None:
    candidate = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="a",
    )
    offsets = (-2, -1, 0, 1, 2)
    values = tuple(Decimal("0.01") for _ in offsets)
    zeroes = tuple(Decimal(0) for _ in offsets)
    schedule = EventWindowSchedule(
        calendar_version="sse-2026.1",
        anchor_predecessor_time=candidate.event_time,
        sessions=tuple(
            EventWindowSession(
                relative_session=offset,
                session_time=candidate.anchor_session_time + timedelta(days=offset),
            )
            for offset in offsets
        ),
    )
    subject = _path(candidate.entity_id, candidate.event_time, values, offsets=offsets)
    shifted_middle = replace(
        subject.points[1],
        session_time=subject.points[1].session_time + timedelta(minutes=1),
    )
    subject = replace(
        subject,
        points=(subject.points[0], shifted_middle, *subject.points[2:]),
    )
    wide_candidate = replace(
        candidate,
        window_schedule=schedule,
        subject_path=subject,
        benchmark_path=_path(
            BENCHMARK.benchmark_id,
            candidate.event_time,
            zeroes,
            offsets=offsets,
        ),
        control_cohort=replace(
            candidate.control_cohort,
            members=tuple(
                _path(member.entity_id, candidate.event_time, zeroes, offsets=offsets)
                for member in candidate.control_cohort.members
            ),
        ),
    )

    result = analyze_event_study(
        _snapshot(wide_candidate),
        selection_rule=RULE,
        policy=replace(
            POLICY,
            window=EventWindow(start_offset_sessions=-2, end_offset_sessions=2),
        ),
        data_cutoff_time=CUTOFF,
    )

    assert result.analysis_sample_count == 0
    assert dict(result.drop_counts)[EventDropReason.WINDOW_CALENDAR_MISMATCH] == 1


def test_keep_clustered_uses_one_overlap_cluster() -> None:
    first = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="first",
    )
    second = _candidate(
        event_id="e2",
        entity_id="600001.SH",
        period_days=1,
        cluster_id="second",
    )

    result = analyze_event_study(
        _snapshot(first, second),
        selection_rule=RULE,
        policy=replace(POLICY, overlap_policy=OverlapPolicy.KEEP_CLUSTERED),
        data_cutoff_time=CUTOFF,
    )

    assert result.analysis_sample_count == 2
    assert len({sample.cluster_id for sample in result.samples}) == 1
    assert result.cumulative_abnormal_return.cluster_count == 1
    assert dict(result.drop_counts)[EventDropReason.OVERLAPPING_EVENT_WINDOW] == 0


def test_invalid_control_is_excluded_when_enough_pit_controls_remain() -> None:
    candidate = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="a",
        control_count=3,
    )
    first, *remaining = candidate.control_cohort.members
    invalid = replace(first, points=first.points[:-1])
    candidate = replace(
        candidate,
        control_cohort=replace(
            candidate.control_cohort,
            members=(invalid, *remaining),
        ),
    )

    result = analyze_event_study(
        _snapshot(candidate),
        selection_rule=RULE,
        policy=POLICY,
        data_cutoff_time=CUTOFF,
    )

    assert result.analysis_sample_count == 1
    assert result.excluded_control_path_count == 1
    assert result.samples[0].valid_control_count == 2
    assert result.samples[0].excluded_control_count == 1
    assert len(result.samples[0].control_path_provenance) == 2


def test_runtime_enum_boundaries_fail_closed() -> None:
    candidate = _candidate(
        event_id="e1",
        entity_id="600001.SH",
        period_days=0,
        cluster_id="a",
    )

    with pytest.raises(EventResearchInputError, match="trading_status"):
        replace(
            candidate.subject_path.points[0],
            trading_status=cast(TradingStatus, "suspended"),
        )
    with pytest.raises(EventResearchInputError, match="overlap_policy"):
        replace(POLICY, overlap_policy=cast(OverlapPolicy, "invalid"))
    with pytest.raises(EventResearchInputError, match="non_tradable_policy"):
        replace(
            POLICY,
            non_tradable_policy=cast(NonTradablePolicy, "invalid"),
        )


def test_empty_snapshot_still_rejects_rule_after_data_cutoff() -> None:
    future_time = CUTOFF + timedelta(seconds=1)

    with pytest.raises(EventFutureDataError, match="selection rule exceeds data cutoff"):
        analyze_event_study(
            _snapshot(),
            selection_rule=replace(
                RULE,
                effective_time=future_time,
                available_time=future_time,
                processing_time=future_time,
            ),
            policy=POLICY,
            data_cutoff_time=CUTOFF,
        )


def test_observational_flags_cannot_be_overridden() -> None:
    result = analyze_event_study(
        _snapshot(
            _candidate(
                event_id="e1",
                entity_id="600001.SH",
                period_days=0,
                cluster_id="a",
            )
        ),
        selection_rule=RULE,
        policy=POLICY,
        data_cutoff_time=CUTOFF,
    )

    with pytest.raises(ValueError, match="init=False"):
        replace(result, observational_only=False)
    with pytest.raises(ValueError, match="init=False"):
        replace(result.samples[0], observational_only=False)


def test_clustered_mean_cr1_handles_unequal_clusters_and_small_samples() -> None:
    summary = clustered_mean(
        (
            ClusteredObservation(cluster_id="a", value=Decimal(1)),
            ClusteredObservation(cluster_id="a", value=Decimal(3)),
            ClusteredObservation(cluster_id="b", value=Decimal(5)),
        )
    )

    assert summary.mean == Decimal(3)
    assert summary.standard_error == Decimal(4) / Decimal(3)
    assert summary.cluster_count == 2
    assert summary.degrees_of_freedom == 1
    assert summary.finite_sample_correction == Decimal(2)
    assert summary.inference_status is ClusterInferenceStatus.SMALL_CLUSTER_COUNT

    one_cluster = clustered_mean(
        (
            ClusteredObservation(cluster_id="a", value=Decimal(1)),
            ClusteredObservation(cluster_id="a", value=Decimal(2)),
        )
    )
    assert one_cluster.standard_error is None
    assert one_cluster.inference_status is ClusterInferenceStatus.INSUFFICIENT_CLUSTERS

    zero_variation = clustered_mean(
        (
            ClusteredObservation(cluster_id="a", value=Decimal(1)),
            ClusteredObservation(cluster_id="b", value=Decimal(1)),
        )
    )
    assert zero_variation.standard_error == 0
    assert zero_variation.inference_status is ClusterInferenceStatus.ZERO_CLUSTER_VARIATION
