from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .models import (
    EVENT_STUDY_ALGORITHM_VERSION,
    AnalyzedEventSample,
    BenchmarkSpec,
    ClusteredObservation,
    EventCandidate,
    EventCandidateSnapshot,
    EventChartPoint,
    EventDropReason,
    EventFutureDataError,
    EventResearchInputError,
    EventResearchStatus,
    EventSelectionField,
    EventSelectionRule,
    EventStudyPolicy,
    EventStudyResult,
    NonTradablePolicy,
    OverlapPolicy,
    PathProvenance,
    RelativeSessionResult,
    ReturnPath,
    ReturnPoint,
    TradingStatus,
)
from .statistics import clustered_mean, mean


@dataclass(frozen=True, slots=True)
class _SelectedCandidate:
    candidate: EventCandidate
    selection_time: datetime


@dataclass(frozen=True, slots=True)
class _PathEvaluation:
    points: tuple[ReturnPoint, ...]
    contains_non_tradable: bool
    logical_available_time: datetime | None
    drop_reason: EventDropReason | None


def _deduplicate(candidates: tuple[EventCandidate, ...]) -> tuple[EventCandidate, ...]:
    by_event_id: dict[str, EventCandidate] = {}
    for candidate in candidates:
        existing = by_event_id.get(candidate.event_id)
        if existing is None:
            by_event_id[candidate.event_id] = candidate
        elif existing != candidate:
            raise EventResearchInputError(f"conflicting duplicate event_id: {candidate.event_id}")
    return tuple(sorted(by_event_id.values(), key=lambda item: (item.event_time, item.event_id)))


def _select_candidates(
    candidates: tuple[EventCandidate, ...],
    rule: EventSelectionRule,
    data_cutoff_time: datetime,
) -> tuple[_SelectedCandidate, ...]:
    selected: list[_SelectedCandidate] = []
    for candidate in candidates:
        if (
            selection_rule_time := max(
                rule.effective_time, rule.available_time, rule.processing_time
            )
        ) > candidate.event_time:
            raise EventFutureDataError(
                f"selection rule must be predefined before event: {candidate.event_id}"
            )
        eligibility = candidate.eligibility_snapshot
        if not eligibility.is_complete:
            raise EventResearchInputError(
                f"event requires a complete eligibility snapshot: {candidate.event_id}"
            )
        if (
            eligibility.as_of_time > candidate.event_time
            or eligibility.available_time > candidate.event_time
            or eligibility.processing_time > candidate.event_time
        ):
            raise EventFutureDataError(
                f"eligibility snapshot must be available by event_time: {candidate.event_id}"
            )
        if (
            candidate.cluster_available_time > candidate.event_time
            or candidate.cluster_processing_time > candidate.event_time
            or candidate.control_cohort.available_time > candidate.event_time
            or candidate.control_cohort.processing_time > candidate.event_time
        ):
            raise EventFutureDataError(
                f"event grouping inputs must be available by event_time: {candidate.event_id}"
            )
        fields = {field.name: field for field in candidate.selection_fields}
        used_fields: list[EventSelectionField] = []
        matches = True
        for name, expected_value in rule.required_fields:
            field = fields.get(name)
            if field is None:
                matches = False
                break
            if field.effective_time > candidate.event_time:
                raise EventFutureDataError(
                    f"post-event selection field is forbidden: {candidate.event_id}:{name}"
                )
            if (
                field.available_time > candidate.event_time
                or field.processing_time > candidate.event_time
            ):
                raise EventFutureDataError(
                    f"post-event selection field is forbidden: {candidate.event_id}:{name}"
                )
            if field.processing_time > data_cutoff_time:
                raise EventFutureDataError(
                    f"selection field exceeds data cutoff: {candidate.event_id}:{name}"
                )
            used_fields.append(field)
            if field.value != expected_value:
                matches = False
                break
        if not matches:
            continue
        selection_time = max(
            candidate.processing_time,
            selection_rule_time,
            eligibility.processing_time,
            candidate.cluster_processing_time,
            candidate.control_cohort.processing_time,
            *(field.processing_time for field in used_fields),
        )
        if selection_time > data_cutoff_time:
            raise EventFutureDataError(
                f"event selection inputs exceed data cutoff: {candidate.event_id}"
            )
        if (
            candidate.window_schedule.anchor_predecessor_time > selection_time
            or candidate.anchor_session_time <= selection_time
        ):
            raise EventFutureDataError(
                "anchor session must be the first scheduled session after selection: "
                f"{candidate.event_id}"
            )
        selected.append(_SelectedCandidate(candidate, selection_time))
    return tuple(selected)


def _overlap_components(
    selected: tuple[_SelectedCandidate, ...],
) -> tuple[set[str], dict[str, str]]:
    by_entity: dict[str, list[EventCandidate]] = defaultdict(list)
    for item in selected:
        by_entity[item.candidate.entity_id].append(item.candidate)
    overlapping_ids: set[str] = set()
    clustered_ids: dict[str, str] = {}
    for entity_id, candidates in by_entity.items():
        ordered = sorted(
            candidates,
            key=lambda item: (item.window_start_time, item.window_end_time, item.event_id),
        )
        component: list[EventCandidate] = []
        component_end: datetime | None = None
        components: list[list[EventCandidate]] = []
        for candidate in ordered:
            if component_end is None or candidate.window_start_time > component_end:
                if component:
                    components.append(component)
                component = [candidate]
                component_end = candidate.window_end_time
            else:
                component.append(candidate)
                component_end = max(component_end, candidate.window_end_time)
        if component:
            components.append(component)
        for index, overlapping in enumerate(components):
            if len(overlapping) < 2:
                continue
            component_id = f"overlap:{entity_id}:{index}"
            for candidate in overlapping:
                overlapping_ids.add(candidate.event_id)
                clustered_ids[candidate.event_id] = component_id
    return overlapping_ids, clustered_ids


def _evaluate_path(
    path: ReturnPath,
    *,
    candidate: EventCandidate,
    policy: EventStudyPolicy,
    data_cutoff_time: datetime,
    missing_reason: EventDropReason,
) -> _PathEvaluation:
    points_by_offset = {point.relative_session: point for point in path.points}
    if any(offset not in points_by_offset for offset in policy.window.offsets):
        return _PathEvaluation((), False, None, missing_reason)
    points = tuple(points_by_offset[offset] for offset in policy.window.offsets)
    scheduled_sessions = {
        session.relative_session: session.session_time
        for session in candidate.window_schedule.sessions
    }
    if tuple(sorted(scheduled_sessions)) != policy.window.offsets or any(
        point.session_time != scheduled_sessions[point.relative_session] for point in points
    ):
        return _PathEvaluation((), False, None, EventDropReason.WINDOW_CALENDAR_MISMATCH)
    if any(
        point.return_semantics is not candidate.benchmark_spec.return_semantics for point in points
    ):
        return _PathEvaluation((), False, None, EventDropReason.RETURN_SEMANTICS_MISMATCH)
    if any(point.processing_time > data_cutoff_time for point in points):
        return _PathEvaluation((), False, None, EventDropReason.OUTCOME_UNAVAILABLE_AT_CUTOFF)
    has_suspension = any(point.trading_status is TradingStatus.SUSPENDED for point in points)
    has_untradable = any(point.trading_status is TradingStatus.UNTRADABLE for point in points)
    if policy.non_tradable_policy is NonTradablePolicy.EXCLUDE_EVENT:
        if has_suspension:
            return _PathEvaluation((), True, None, EventDropReason.SUSPENDED_WINDOW)
        if has_untradable:
            return _PathEvaluation((), True, None, EventDropReason.UNTRADABLE_WINDOW)
    return _PathEvaluation(
        points=points,
        contains_non_tradable=has_suspension or has_untradable,
        logical_available_time=max(point.processing_time for point in points),
        drop_reason=None,
    )


def _compound(points: tuple[ReturnPoint, ...]) -> Decimal:
    result = Decimal(1)
    for point in points:
        result *= Decimal(1) + point.return_value
    return result - Decimal(1)


def _provenance(path: ReturnPath) -> PathProvenance:
    sources = {
        (point.source_id, point.source_version, point.return_semantics) for point in path.points
    }
    return PathProvenance(
        entity_id=path.entity_id,
        sources=tuple(sorted(sources, key=lambda item: (item[0], item[1], item[2].value))),
    )


def _analyze_candidate(
    selected: _SelectedCandidate,
    *,
    effective_cluster_id: str,
    policy: EventStudyPolicy,
    data_cutoff_time: datetime,
) -> tuple[AnalyzedEventSample | None, EventDropReason | None, int]:
    candidate = selected.candidate
    subject = _evaluate_path(
        candidate.subject_path,
        candidate=candidate,
        policy=policy,
        data_cutoff_time=data_cutoff_time,
        missing_reason=EventDropReason.INCOMPLETE_EVENT_PATH,
    )
    if subject.drop_reason is not None:
        return None, subject.drop_reason, 0
    benchmark = _evaluate_path(
        candidate.benchmark_path,
        candidate=candidate,
        policy=policy,
        data_cutoff_time=data_cutoff_time,
        missing_reason=EventDropReason.INCOMPLETE_BENCHMARK_PATH,
    )
    if benchmark.drop_reason is not None:
        return None, benchmark.drop_reason, 0
    valid_controls: list[_PathEvaluation] = []
    valid_control_paths: list[ReturnPath] = []
    excluded_controls = 0
    for control_path in candidate.control_cohort.members:
        if control_path.entity_id in {
            candidate.entity_id,
            candidate.benchmark_spec.benchmark_id,
        }:
            excluded_controls += 1
            continue
        control = _evaluate_path(
            control_path,
            candidate=candidate,
            policy=policy,
            data_cutoff_time=data_cutoff_time,
            missing_reason=EventDropReason.INCOMPLETE_EVENT_PATH,
        )
        if control.drop_reason is not None:
            excluded_controls += 1
        else:
            valid_controls.append(control)
            valid_control_paths.append(control_path)
    if len(valid_controls) < policy.min_controls_per_event:
        return None, EventDropReason.INSUFFICIENT_CONTROLS, excluded_controls
    abnormal_returns = tuple(
        (
            offset,
            subject_point.return_value - benchmark_point.return_value,
        )
        for offset, subject_point, benchmark_point in zip(
            policy.window.offsets,
            subject.points,
            benchmark.points,
            strict=True,
        )
    )
    cumulative_abnormal_return = sum((value for _, value in abnormal_returns), start=Decimal(0))
    control_cars = tuple(
        sum(
            (
                control_point.return_value - benchmark_point.return_value
                for control_point, benchmark_point in zip(
                    control.points, benchmark.points, strict=True
                )
            ),
            start=Decimal(0),
        )
        for control in valid_controls
    )
    control_mean = mean(control_cars)
    logical_available_times = [
        selected.selection_time,
        candidate.processing_time,
        candidate.control_cohort.processing_time,
        subject.logical_available_time,
        benchmark.logical_available_time,
        *(control.logical_available_time for control in valid_controls),
    ]
    logical_available_time = max(value for value in logical_available_times if value is not None)
    contains_non_tradable = (
        subject.contains_non_tradable
        or benchmark.contains_non_tradable
        or any(control.contains_non_tradable for control in valid_controls)
    )
    return (
        AnalyzedEventSample(
            event_id=candidate.event_id,
            revision_id=candidate.revision_id,
            entity_id=candidate.entity_id,
            selection_time=selected.selection_time,
            logical_available_time=logical_available_time,
            cluster_id=effective_cluster_id,
            eligibility_snapshot_id=candidate.eligibility_snapshot.snapshot_id,
            eligibility_snapshot_version=candidate.eligibility_snapshot.snapshot_version,
            control_snapshot_id=candidate.control_cohort.snapshot_id,
            control_rule_version=candidate.control_cohort.rule_version,
            control_universe_version=candidate.control_cohort.universe_version,
            subject_path_provenance=_provenance(candidate.subject_path),
            benchmark_path_provenance=_provenance(candidate.benchmark_path),
            control_path_provenance=tuple(_provenance(path) for path in valid_control_paths),
            raw_cumulative_return=_compound(subject.points),
            benchmark_cumulative_return=_compound(benchmark.points),
            cumulative_abnormal_return=cumulative_abnormal_return,
            control_mean_cumulative_abnormal_return=control_mean,
            cross_sectional_effect=cumulative_abnormal_return - control_mean,
            abnormal_returns=abnormal_returns,
            valid_control_count=len(valid_controls),
            excluded_control_count=excluded_controls,
            contains_non_tradable_observation=contains_non_tradable,
        ),
        None,
        excluded_controls,
    )


def _chart_data(
    relative_results: tuple[RelativeSessionResult, ...],
    cross_sectional_mean: Decimal | None,
    cross_sectional_sample_count: int,
) -> tuple[EventChartPoint, ...]:
    result: list[EventChartPoint] = []
    cumulative = Decimal(0)
    for relative in relative_results:
        summary = relative.average_abnormal_return
        if summary.mean is None:
            continue
        cumulative += summary.mean
        result.extend(
            (
                EventChartPoint(
                    series="average_abnormal_return",
                    x=str(relative.relative_session),
                    value=summary.mean,
                    sample_count=summary.sample_count,
                ),
                EventChartPoint(
                    series="cumulative_average_abnormal_return",
                    x=str(relative.relative_session),
                    value=cumulative,
                    sample_count=summary.sample_count,
                ),
            )
        )
    if cross_sectional_mean is not None:
        result.append(
            EventChartPoint(
                series="cross_sectional_effect",
                x="window",
                value=cross_sectional_mean,
                sample_count=cross_sectional_sample_count,
            )
        )
    return tuple(result)


def analyze_event_study(
    snapshot: EventCandidateSnapshot,
    *,
    selection_rule: EventSelectionRule,
    policy: EventStudyPolicy,
    data_cutoff_time: datetime,
) -> EventStudyResult:
    if data_cutoff_time.tzinfo is None or data_cutoff_time.utcoffset() is None:
        raise EventResearchInputError("data_cutoff_time must be timezone-aware")
    if selection_rule.processing_time > data_cutoff_time:
        raise EventFutureDataError("selection rule exceeds data cutoff")
    if not snapshot.is_complete:
        raise EventResearchInputError("event study requires a complete candidate snapshot")
    if snapshot.as_of_time > data_cutoff_time or snapshot.processing_time > data_cutoff_time:
        raise EventFutureDataError("candidate snapshot exceeds data cutoff")
    candidates = _deduplicate(snapshot.candidates)
    selected = _select_candidates(candidates, selection_rule, data_cutoff_time)
    benchmark_specs = {item.candidate.benchmark_spec for item in selected}
    if len(benchmark_specs) > 1:
        raise EventResearchInputError("selected events must use one benchmark contract")
    benchmark_spec: BenchmarkSpec | None = next(iter(benchmark_specs), None)
    overlapping_ids, overlap_cluster_ids = _overlap_components(selected)
    drops: Counter[EventDropReason] = Counter()
    prequalified: list[_SelectedCandidate] = []
    for item in selected:
        if (
            policy.overlap_policy is OverlapPolicy.EXCLUDE_ALL_SAME_ENTITY_OVERLAP
            and item.candidate.event_id in overlapping_ids
        ):
            drops[EventDropReason.OVERLAPPING_EVENT_WINDOW] += 1
        else:
            prequalified.append(item)
    samples: list[AnalyzedEventSample] = []
    excluded_control_paths = 0
    for item in prequalified:
        effective_cluster_id = (
            overlap_cluster_ids.get(item.candidate.event_id, item.candidate.cluster_id)
            if policy.overlap_policy is OverlapPolicy.KEEP_CLUSTERED
            else item.candidate.cluster_id
        )
        sample, drop_reason, excluded_controls = _analyze_candidate(
            item,
            effective_cluster_id=effective_cluster_id,
            policy=policy,
            data_cutoff_time=data_cutoff_time,
        )
        excluded_control_paths += excluded_controls
        if drop_reason is not None:
            drops[drop_reason] += 1
        elif sample is not None:
            samples.append(sample)
    ordered_samples = tuple(sorted(samples, key=lambda item: (item.selection_time, item.event_id)))
    cumulative_summary = clustered_mean(
        tuple(
            ClusteredObservation(sample.cluster_id, sample.cumulative_abnormal_return)
            for sample in ordered_samples
        )
    )
    cross_sectional_summary = clustered_mean(
        tuple(
            ClusteredObservation(sample.cluster_id, sample.cross_sectional_effect)
            for sample in ordered_samples
        )
    )
    relative_results = tuple(
        RelativeSessionResult(
            relative_session=offset,
            average_abnormal_return=clustered_mean(
                tuple(
                    ClusteredObservation(sample.cluster_id, dict(sample.abnormal_returns)[offset])
                    for sample in ordered_samples
                )
            ),
        )
        for offset in policy.window.offsets
    )
    if not selected:
        status = EventResearchStatus.NO_SELECTED_EVENTS
    elif ordered_samples:
        status = EventResearchStatus.OK
    else:
        status = EventResearchStatus.NO_VALID_SAMPLES
    return EventStudyResult(
        algorithm_version=EVENT_STUDY_ALGORITHM_VERSION,
        data_cutoff_time=data_cutoff_time,
        status=status,
        candidate_snapshot_id=snapshot.snapshot_id,
        candidate_snapshot_version=snapshot.snapshot_version,
        selection_rule_version=selection_rule.rule_version,
        selection_rule_effective_time=selection_rule.effective_time,
        selection_rule_available_time=selection_rule.available_time,
        selection_rule_processing_time=selection_rule.processing_time,
        candidate_count=len(snapshot.candidates),
        selected_event_count=len(selected),
        prequalified_event_count=len(prequalified),
        analysis_sample_count=len(ordered_samples),
        non_tradable_sample_count=sum(
            sample.contains_non_tradable_observation for sample in ordered_samples
        ),
        excluded_control_path_count=excluded_control_paths,
        benchmark_spec=benchmark_spec,
        policy=policy,
        cumulative_abnormal_return=cumulative_summary,
        cross_sectional_effect=cross_sectional_summary,
        relative_session_results=relative_results,
        samples=ordered_samples,
        drop_counts=tuple((reason, drops[reason]) for reason in EventDropReason),
        chart_data=_chart_data(
            relative_results,
            cross_sectional_summary.mean,
            cross_sectional_summary.sample_count,
        ),
    )
