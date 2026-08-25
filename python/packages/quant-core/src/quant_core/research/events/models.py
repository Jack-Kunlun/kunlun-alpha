from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from decimal import Decimal
from enum import Enum

EVENT_STUDY_ALGORITHM_VERSION = "1.0.0"
_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:[-+][A-Za-z0-9.-]+)?$")


class EventResearchInputError(ValueError):
    """Raised when an event-study contract is internally inconsistent."""


class EventFutureDataError(EventResearchInputError):
    """Raised when event selection could depend on post-event information."""


class EventResearchStatus(str, Enum):
    OK = "ok"
    NO_SELECTED_EVENTS = "no_selected_events"
    NO_VALID_SAMPLES = "no_valid_samples"


class EventDropReason(str, Enum):
    OVERLAPPING_EVENT_WINDOW = "overlapping_event_window"
    EVENT_UNAVAILABLE_AT_CUTOFF = "event_unavailable_at_cutoff"
    INCOMPLETE_EVENT_PATH = "incomplete_event_path"
    INCOMPLETE_BENCHMARK_PATH = "incomplete_benchmark_path"
    WINDOW_CALENDAR_MISMATCH = "window_calendar_mismatch"
    RETURN_SEMANTICS_MISMATCH = "return_semantics_mismatch"
    OUTCOME_UNAVAILABLE_AT_CUTOFF = "outcome_unavailable_at_cutoff"
    SUSPENDED_WINDOW = "suspended_window"
    UNTRADABLE_WINDOW = "untradable_window"
    INSUFFICIENT_CONTROLS = "insufficient_controls"


class TradingStatus(str, Enum):
    TRADABLE = "tradable"
    SUSPENDED = "suspended"
    UNTRADABLE = "untradable"


class ReturnSemantics(str, Enum):
    ADJUSTED_CLOSE = "adjusted_close_return"
    UNADJUSTED_CLOSE = "unadjusted_close_return"


class OverlapPolicy(str, Enum):
    EXCLUDE_ALL_SAME_ENTITY_OVERLAP = "exclude_all_same_entity_overlap"
    KEEP_CLUSTERED = "keep_clustered"


class NonTradablePolicy(str, Enum):
    EXCLUDE_EVENT = "exclude_event"
    KEEP_OBSERVED_MARKED = "keep_observed_marked"


class ClusterInferenceStatus(str, Enum):
    NO_VALID_SAMPLES = "no_valid_samples"
    INSUFFICIENT_EVENT_SAMPLES = "insufficient_event_samples"
    INSUFFICIENT_CLUSTERS = "insufficient_clusters"
    SMALL_CLUSTER_COUNT = "small_cluster_count"
    ZERO_CLUSTER_VARIATION = "zero_cluster_variation"
    OK = "ok"


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventResearchInputError(f"{field} must be timezone-aware")


def _text(value: str, field: str) -> None:
    if not value.strip():
        raise EventResearchInputError(f"{field} must be non-empty")


def _version(value: str, field: str) -> None:
    if _VERSION.fullmatch(value) is None:
        raise EventResearchInputError(f"{field} must be a versioned identifier")


def _decimal(value: object, field: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise EventResearchInputError(f"{field} must be a finite Decimal")


def _enum(value: object, enum_type: type[Enum], field: str) -> None:
    if not isinstance(value, enum_type):
        raise EventResearchInputError(f"{field} must be a {enum_type.__name__}")


@dataclass(frozen=True, slots=True)
class EventWindow:
    start_offset_sessions: int
    end_offset_sessions: int

    def __post_init__(self) -> None:
        if type(self.start_offset_sessions) is not int or type(self.end_offset_sessions) is not int:
            raise EventResearchInputError("event-window offsets must be integers")
        if self.start_offset_sessions > 0 or self.end_offset_sessions < 0:
            raise EventResearchInputError("event window must contain offset zero")
        if self.start_offset_sessions > self.end_offset_sessions:
            raise EventResearchInputError("event-window start must not exceed end")
        if self.end_offset_sessions - self.start_offset_sessions > 500:
            raise EventResearchInputError("event window cannot exceed 500 sessions")

    @property
    def offsets(self) -> tuple[int, ...]:
        return tuple(range(self.start_offset_sessions, self.end_offset_sessions + 1))


@dataclass(frozen=True, slots=True)
class EventSelectionField:
    name: str
    value: str
    effective_time: datetime
    available_time: datetime
    processing_time: datetime

    def __post_init__(self) -> None:
        _text(self.name, "selection-field name")
        _text(self.value, "selection-field value")
        for field, value in (
            ("selection-field effective_time", self.effective_time),
            ("selection-field available_time", self.available_time),
            ("selection-field processing_time", self.processing_time),
        ):
            _aware(value, field)
        if self.available_time < self.effective_time:
            raise EventResearchInputError(
                "selection-field available_time cannot precede effective_time"
            )
        if self.processing_time < self.available_time:
            raise EventResearchInputError(
                "selection-field processing_time cannot precede available_time"
            )


@dataclass(frozen=True, slots=True)
class EventSelectionRule:
    rule_version: str
    effective_time: datetime
    available_time: datetime
    processing_time: datetime
    required_fields: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _version(self.rule_version, "selection rule_version")
        _aware(self.effective_time, "selection-rule effective_time")
        _aware(self.available_time, "selection-rule available_time")
        _aware(self.processing_time, "selection-rule processing_time")
        if not self.effective_time <= self.available_time <= self.processing_time:
            raise EventResearchInputError("selection-rule times must be monotonic")
        if not self.required_fields:
            raise EventResearchInputError("selection rule requires at least one field")
        names: set[str] = set()
        for name, value in self.required_fields:
            _text(name, "selection rule field")
            _text(value, "selection rule value")
            if name in names:
                raise EventResearchInputError("selection rule fields must be unique")
            names.add(name)


@dataclass(frozen=True, slots=True)
class ReturnPoint:
    relative_session: int
    session_time: datetime
    available_time: datetime
    processing_time: datetime
    return_value: Decimal
    trading_status: TradingStatus
    source_id: str
    source_version: str
    return_semantics: ReturnSemantics

    def __post_init__(self) -> None:
        if type(self.relative_session) is not int:
            raise EventResearchInputError("relative_session must be an integer")
        for field, value in (
            ("return session_time", self.session_time),
            ("return available_time", self.available_time),
            ("return processing_time", self.processing_time),
        ):
            _aware(value, field)
        if self.available_time < self.session_time:
            raise EventResearchInputError("return available_time cannot precede session_time")
        if self.processing_time < self.available_time:
            raise EventResearchInputError("return processing_time cannot precede available_time")
        _decimal(self.return_value, "return_value")
        if self.return_value < Decimal(-1):
            raise EventResearchInputError("simple return cannot be less than -1")
        _enum(self.trading_status, TradingStatus, "trading_status")
        _enum(self.return_semantics, ReturnSemantics, "return_semantics")
        _text(self.source_id, "return source_id")
        _version(self.source_version, "return source_version")


@dataclass(frozen=True, slots=True)
class ReturnPath:
    entity_id: str
    points: tuple[ReturnPoint, ...]

    def __post_init__(self) -> None:
        _text(self.entity_id, "return-path entity_id")
        offsets = tuple(point.relative_session for point in self.points)
        if len(offsets) != len(set(offsets)):
            raise EventResearchInputError("return-path offsets must be unique")
        ordered = tuple(sorted(self.points, key=lambda point: point.relative_session))
        session_times = tuple(point.session_time for point in ordered)
        if any(
            current <= prior
            for prior, current in zip(session_times, session_times[1:], strict=False)
        ):
            raise EventResearchInputError("return-path session times must increase by offset")


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    benchmark_id: str
    benchmark_version: str
    source_id: str
    source_version: str
    data_version: str
    schema_version: str
    calendar_version: str
    return_semantics: ReturnSemantics

    def __post_init__(self) -> None:
        for field, value in (
            ("benchmark_id", self.benchmark_id),
            ("benchmark source_id", self.source_id),
            ("benchmark data_version", self.data_version),
            ("benchmark calendar_version", self.calendar_version),
        ):
            _text(value, field)
        for field, value in (
            ("benchmark_version", self.benchmark_version),
            ("benchmark source_version", self.source_version),
            ("benchmark schema_version", self.schema_version),
        ):
            _version(value, field)
        _enum(
            self.return_semantics,
            ReturnSemantics,
            "benchmark return_semantics",
        )


@dataclass(frozen=True, slots=True)
class ControlCohortSnapshot:
    snapshot_id: str
    rule_version: str
    universe_version: str
    available_time: datetime
    processing_time: datetime
    members: tuple[ReturnPath, ...]

    def __post_init__(self) -> None:
        _text(self.snapshot_id, "control snapshot_id")
        _version(self.rule_version, "control rule_version")
        _text(self.universe_version, "control universe_version")
        _aware(self.available_time, "control available_time")
        _aware(self.processing_time, "control processing_time")
        if self.processing_time < self.available_time:
            raise EventResearchInputError("control processing_time cannot precede available_time")
        entity_ids = tuple(member.entity_id for member in self.members)
        if len(entity_ids) != len(set(entity_ids)):
            raise EventResearchInputError("control member entity_id values must be unique")


@dataclass(frozen=True, slots=True)
class EventEligibilitySnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of_time: datetime
    available_time: datetime
    processing_time: datetime
    is_complete: bool

    def __post_init__(self) -> None:
        _text(self.snapshot_id, "eligibility snapshot_id")
        _version(self.snapshot_version, "eligibility snapshot_version")
        _aware(self.as_of_time, "eligibility snapshot as_of_time")
        _aware(self.available_time, "eligibility snapshot available_time")
        _aware(self.processing_time, "eligibility snapshot processing_time")
        if not self.as_of_time <= self.available_time <= self.processing_time:
            raise EventResearchInputError("eligibility snapshot times must be monotonic")
        if type(self.is_complete) is not bool:
            raise EventResearchInputError("eligibility snapshot completeness must be boolean")


@dataclass(frozen=True, slots=True)
class EventWindowSession:
    relative_session: int
    session_time: datetime

    def __post_init__(self) -> None:
        if type(self.relative_session) is not int:
            raise EventResearchInputError("window relative_session must be an integer")
        _aware(self.session_time, "window session_time")


@dataclass(frozen=True, slots=True)
class EventWindowSchedule:
    calendar_version: str
    anchor_predecessor_time: datetime
    sessions: tuple[EventWindowSession, ...]

    def __post_init__(self) -> None:
        _text(self.calendar_version, "window calendar_version")
        _aware(self.anchor_predecessor_time, "anchor predecessor_time")
        offsets = tuple(session.relative_session for session in self.sessions)
        if not offsets or 0 not in offsets:
            raise EventResearchInputError("window schedule must contain anchor offset zero")
        if len(offsets) != len(set(offsets)):
            raise EventResearchInputError("window schedule offsets must be unique")
        ordered = tuple(sorted(self.sessions, key=lambda session: session.relative_session))
        expected_offsets = tuple(
            range(ordered[0].relative_session, ordered[-1].relative_session + 1)
        )
        if tuple(session.relative_session for session in ordered) != expected_offsets:
            raise EventResearchInputError("window schedule offsets must be contiguous")
        session_times = tuple(session.session_time for session in ordered)
        if any(
            current <= prior
            for prior, current in zip(session_times, session_times[1:], strict=False)
        ):
            raise EventResearchInputError("window schedule session times must increase")
        anchor_time = next(
            session.session_time for session in ordered if session.relative_session == 0
        )
        if self.anchor_predecessor_time >= anchor_time:
            raise EventResearchInputError("anchor predecessor must precede anchor session")
        predecessor = next((session for session in ordered if session.relative_session == -1), None)
        if predecessor is not None and predecessor.session_time != self.anchor_predecessor_time:
            raise EventResearchInputError("offset -1 must equal the declared anchor predecessor")

    @property
    def anchor_session_time(self) -> datetime:
        return next(
            session.session_time for session in self.sessions if session.relative_session == 0
        )

    @property
    def window_start_time(self) -> datetime:
        return min(self.sessions, key=lambda session: session.relative_session).session_time

    @property
    def window_end_time(self) -> datetime:
        return max(self.sessions, key=lambda session: session.relative_session).session_time


@dataclass(frozen=True, slots=True)
class EventCandidate:
    event_id: str
    revision_id: str
    entity_id: str
    event_time: datetime
    publish_time: datetime
    ingest_time: datetime
    available_time: datetime
    processing_time: datetime
    eligibility_snapshot: EventEligibilitySnapshot
    window_schedule: EventWindowSchedule
    cluster_id: str
    cluster_available_time: datetime
    cluster_processing_time: datetime
    selection_fields: tuple[EventSelectionField, ...]
    subject_path: ReturnPath
    benchmark_spec: BenchmarkSpec
    benchmark_path: ReturnPath
    control_cohort: ControlCohortSnapshot

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        _version(self.revision_id, "revision_id")
        _text(self.entity_id, "entity_id")
        for field, value in (
            ("event_time", self.event_time),
            ("publish_time", self.publish_time),
            ("ingest_time", self.ingest_time),
            ("event available_time", self.available_time),
            ("event processing_time", self.processing_time),
            ("cluster_available_time", self.cluster_available_time),
            ("cluster_processing_time", self.cluster_processing_time),
        ):
            _aware(value, field)
        if not (
            self.event_time
            <= self.publish_time
            <= self.ingest_time
            <= self.available_time
            <= self.processing_time
        ):
            raise EventResearchInputError("event provenance times must be monotonic")
        if self.cluster_processing_time < self.cluster_available_time:
            raise EventResearchInputError("cluster processing_time cannot precede available_time")
        _text(self.cluster_id, "cluster_id")
        field_names = tuple(field.name for field in self.selection_fields)
        if len(field_names) != len(set(field_names)):
            raise EventResearchInputError("selection-field names must be unique")
        if self.subject_path.entity_id != self.entity_id:
            raise EventResearchInputError("subject path must match event entity_id")
        if self.benchmark_path.entity_id != self.benchmark_spec.benchmark_id:
            raise EventResearchInputError("benchmark path must match benchmark_id")
        if self.window_schedule.calendar_version != self.benchmark_spec.calendar_version:
            raise EventResearchInputError("window and benchmark calendar versions must match")

    @property
    def anchor_session_time(self) -> datetime:
        return self.window_schedule.anchor_session_time

    @property
    def window_start_time(self) -> datetime:
        return self.window_schedule.window_start_time

    @property
    def window_end_time(self) -> datetime:
        return self.window_schedule.window_end_time


@dataclass(frozen=True, slots=True)
class EventCandidateSnapshot:
    snapshot_id: str
    snapshot_version: str
    as_of_time: datetime
    processing_time: datetime
    is_complete: bool
    candidates: tuple[EventCandidate, ...]

    def __post_init__(self) -> None:
        _text(self.snapshot_id, "candidate snapshot_id")
        _version(self.snapshot_version, "candidate snapshot_version")
        _aware(self.as_of_time, "candidate snapshot as_of_time")
        _aware(self.processing_time, "candidate snapshot processing_time")
        if self.processing_time < self.as_of_time:
            raise EventResearchInputError(
                "candidate snapshot processing_time cannot precede as_of_time"
            )
        if type(self.is_complete) is not bool:
            raise EventResearchInputError("candidate snapshot completeness must be boolean")


@dataclass(frozen=True, slots=True)
class EventStudyPolicy:
    window: EventWindow
    overlap_policy: OverlapPolicy
    non_tradable_policy: NonTradablePolicy
    min_controls_per_event: int

    def __post_init__(self) -> None:
        _enum(self.overlap_policy, OverlapPolicy, "overlap_policy")
        _enum(
            self.non_tradable_policy,
            NonTradablePolicy,
            "non_tradable_policy",
        )
        if type(self.min_controls_per_event) is not int or self.min_controls_per_event < 1:
            raise EventResearchInputError("min_controls_per_event must be positive")


@dataclass(frozen=True, slots=True)
class ClusteredObservation:
    cluster_id: str
    value: Decimal

    def __post_init__(self) -> None:
        _text(self.cluster_id, "clustered observation cluster_id")
        _decimal(self.value, "clustered observation value")


@dataclass(frozen=True, slots=True)
class ClusteredMeanSummary:
    sample_count: int
    cluster_count: int
    mean: Decimal | None
    standard_error: Decimal | None
    degrees_of_freedom: int | None
    finite_sample_correction: Decimal | None
    inference_status: ClusterInferenceStatus


@dataclass(frozen=True, slots=True)
class PathProvenance:
    entity_id: str
    sources: tuple[tuple[str, str, ReturnSemantics], ...]


@dataclass(frozen=True, slots=True)
class AnalyzedEventSample:
    event_id: str
    revision_id: str
    entity_id: str
    selection_time: datetime
    logical_available_time: datetime
    cluster_id: str
    eligibility_snapshot_id: str
    eligibility_snapshot_version: str
    control_snapshot_id: str
    control_rule_version: str
    control_universe_version: str
    subject_path_provenance: PathProvenance
    benchmark_path_provenance: PathProvenance
    control_path_provenance: tuple[PathProvenance, ...]
    raw_cumulative_return: Decimal
    benchmark_cumulative_return: Decimal
    cumulative_abnormal_return: Decimal
    control_mean_cumulative_abnormal_return: Decimal
    cross_sectional_effect: Decimal
    abnormal_returns: tuple[tuple[int, Decimal], ...]
    valid_control_count: int
    excluded_control_count: int
    contains_non_tradable_observation: bool
    observational_only: bool = dataclass_field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class RelativeSessionResult:
    relative_session: int
    average_abnormal_return: ClusteredMeanSummary


@dataclass(frozen=True, slots=True)
class EventChartPoint:
    series: str
    x: str
    value: Decimal
    sample_count: int


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    algorithm_version: str
    data_cutoff_time: datetime
    status: EventResearchStatus
    candidate_snapshot_id: str
    candidate_snapshot_version: str
    selection_rule_version: str
    selection_rule_effective_time: datetime
    selection_rule_available_time: datetime
    selection_rule_processing_time: datetime
    candidate_count: int
    selected_event_count: int
    prequalified_event_count: int
    analysis_sample_count: int
    non_tradable_sample_count: int
    excluded_control_path_count: int
    benchmark_spec: BenchmarkSpec | None
    policy: EventStudyPolicy
    cumulative_abnormal_return: ClusteredMeanSummary
    cross_sectional_effect: ClusteredMeanSummary
    relative_session_results: tuple[RelativeSessionResult, ...]
    samples: tuple[AnalyzedEventSample, ...]
    drop_counts: tuple[tuple[EventDropReason, int], ...]
    chart_data: tuple[EventChartPoint, ...]
    observational_only: bool = dataclass_field(default=True, init=False)
