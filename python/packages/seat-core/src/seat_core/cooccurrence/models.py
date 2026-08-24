"""Immutable public contracts for P4-N05 seat co-occurrence research."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from seat_core.features.performance import DailyPriceObservation, PerformanceSample

COOCCURRENCE_SCHEMA_VERSION = "seat-cooccurrence-v1"
COOCCURRENCE_ALGORITHM_VERSION = "seat-cooccurrence-algorithm-v1"
COOCCURRENCE_POLICY_VERSION = "seat-cooccurrence-policy-v1"
SEAT_EVENT_ID_ALGORITHM_VERSION = "seat-event-id-v1"
TOPIC_MEMBERSHIP_SCHEMA_VERSION = "seat-event-topic-membership-v1"
BOOTSTRAP_ALGORITHM_VERSION = "decimal-bootstrap-mean-v1"
R7_QUANTILE_ALGORITHM_VERSION = "decimal-r7-v1"
HASH_TO_INDEX_ALGORITHM_VERSION = "sha256-hash-to-index-v1"
COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION = "seat-cooccurrence-fingerprint-v1"
SEED_SERIALIZATION_VERSION = "canonical-json-v1"

_SEAT_ID_RE = re.compile(r"^seat-[0-9a-f]{64}$")
_INSTRUMENT_ID_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")
_ROUND_HALF_EVEN = "ROUND_HALF_EVEN"


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_non_empty(value: str, name: str) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_decimal(value: Decimal, name: str) -> None:
    if type(value) is not Decimal:
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")


def _require_seat_id(value: str, name: str = "seat_id") -> None:
    if type(value) is not str or _SEAT_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must match seat-[0-9a-f]{{64}}")


def _require_instrument_id(value: str) -> None:
    if type(value) is not str or _INSTRUMENT_ID_RE.fullmatch(value) is None:
        raise ValueError("instrument_id must use canonical unified code form")


def _require_string_tuple(value: tuple[str, ...], name: str) -> None:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be a tuple")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    for item in value:
        _require_non_empty(item, f"{name} item")


class CooccurrenceInputError(ValueError):
    """Fail-closed error for invalid or ambiguous co-occurrence inputs."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class CIStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"


@dataclass(frozen=True, slots=True, order=True)
class SeatEventKey:
    """The seat event namespace, deliberately distinct from MarketEvent IDs."""

    instrument_id: str
    trade_date: date

    def __post_init__(self) -> None:
        _require_instrument_id(self.instrument_id)
        if type(self.trade_date) is not date:
            raise TypeError("trade_date must be date")


@dataclass(frozen=True, slots=True)
class EventTopicMembership:
    """A controlled, point-in-time topic assignment for one seat event."""

    seat_event_key: SeatEventKey
    topic_id: str
    taxonomy_id: str
    taxonomy_version: str
    assignment_version: str
    assignment_fingerprint: str
    source: str
    source_version: str
    evidence_id: str
    available_time: datetime
    upstream_market_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.seat_event_key) is not SeatEventKey:
            raise TypeError("seat_event_key must be SeatEventKey")
        for name in (
            "topic_id",
            "taxonomy_id",
            "taxonomy_version",
            "assignment_version",
            "assignment_fingerprint",
            "source",
            "source_version",
            "evidence_id",
        ):
            _require_non_empty(getattr(self, name), name)
        _require_aware(self.available_time, "available_time")
        if type(self.upstream_market_event_ids) is not tuple:
            raise TypeError("upstream_market_event_ids must be a tuple")
        for event_id in self.upstream_market_event_ids:
            _require_non_empty(event_id, "upstream_market_event_ids item")
        object.__setattr__(
            self,
            "upstream_market_event_ids",
            tuple(sorted(set(self.upstream_market_event_ids))),
        )

    @property
    def logical_key(self) -> tuple[SeatEventKey, str]:
        return self.seat_event_key, self.topic_id

    @property
    def assignment_key(self) -> tuple[str, str, str, str]:
        return (
            self.taxonomy_id,
            self.taxonomy_version,
            self.assignment_version,
            self.assignment_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class CooccurrencePolicy:
    """Versioned safety and deterministic-statistics policy."""

    policy_version: str = COOCCURRENCE_POLICY_VERSION
    schema_version: str = COOCCURRENCE_SCHEMA_VERSION
    algorithm_version: str = COOCCURRENCE_ALGORITHM_VERSION
    event_id_algorithm_version: str = SEAT_EVENT_ID_ALGORITHM_VERSION
    topic_membership_schema_version: str = TOPIC_MEMBERSHIP_SCHEMA_VERSION
    bootstrap_algorithm_version: str = BOOTSTRAP_ALGORITHM_VERSION
    r7_algorithm_version: str = R7_QUANTILE_ALGORITHM_VERSION
    hash_to_index_algorithm_version: str = HASH_TO_INDEX_ALGORITHM_VERSION
    fingerprint_algorithm_version: str = COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION
    seed_serialization_version: str = SEED_SERIALIZATION_VERSION
    alpha: Decimal = Decimal("0.05")
    resamples: int = 1000
    min_ci_samples: int = 5
    decimal_precision: int = 34
    rounding: str = _ROUND_HALF_EVEN
    allowed_taxonomy_ids: tuple[str, ...] = ()
    allowed_taxonomy_versions: tuple[str, ...] = ()
    allowed_topic_sources: tuple[str, ...] = ()
    max_seats_per_event: int = 32
    max_parent_features: int = 100_000
    max_events: int = 100_000
    max_edges: int = 100_000
    max_input_samples: int = 100_000
    max_topic_membership_records: int = 100_000
    max_topics_per_event: int = 32
    max_bootstrap_draws: int = 5_000_000

    def __post_init__(self) -> None:
        for name in (
            "policy_version",
            "schema_version",
            "algorithm_version",
            "event_id_algorithm_version",
            "topic_membership_schema_version",
            "bootstrap_algorithm_version",
            "r7_algorithm_version",
            "hash_to_index_algorithm_version",
            "fingerprint_algorithm_version",
            "seed_serialization_version",
            "rounding",
        ):
            _require_non_empty(getattr(self, name), name)
        _require_decimal(self.alpha, "alpha")
        expected_versions = {
            "policy_version": COOCCURRENCE_POLICY_VERSION,
            "schema_version": COOCCURRENCE_SCHEMA_VERSION,
            "algorithm_version": COOCCURRENCE_ALGORITHM_VERSION,
            "event_id_algorithm_version": SEAT_EVENT_ID_ALGORITHM_VERSION,
            "topic_membership_schema_version": TOPIC_MEMBERSHIP_SCHEMA_VERSION,
            "bootstrap_algorithm_version": BOOTSTRAP_ALGORITHM_VERSION,
            "r7_algorithm_version": R7_QUANTILE_ALGORITHM_VERSION,
            "hash_to_index_algorithm_version": HASH_TO_INDEX_ALGORITHM_VERSION,
            "fingerprint_algorithm_version": COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION,
            "seed_serialization_version": SEED_SERIALIZATION_VERSION,
        }
        for name, expected in expected_versions.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} must equal the current v1 implementation")
        if not Decimal("0") < self.alpha < Decimal("1"):
            raise ValueError("alpha must be between 0 and 1")
        if self.rounding != _ROUND_HALF_EVEN:
            raise ValueError("rounding must be ROUND_HALF_EVEN")
        for name in ("resamples", "min_ci_samples", "decimal_precision"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.decimal_precision != 34:
            raise ValueError("decimal_precision must be 34 for v1")
        for name in (
            "max_seats_per_event",
            "max_parent_features",
            "max_events",
            "max_edges",
            "max_input_samples",
            "max_topic_membership_records",
            "max_topics_per_event",
            "max_bootstrap_draws",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "allowed_taxonomy_ids",
            "allowed_taxonomy_versions",
            "allowed_topic_sources",
        ):
            _require_string_tuple(getattr(self, name), name)

    @property
    def fingerprint(self) -> str:
        payload = {
            "algorithmVersion": self.algorithm_version,
            "alpha": format(self.alpha, "f"),
            "allowedTaxonomyIds": sorted(self.allowed_taxonomy_ids),
            "allowedTaxonomyVersions": sorted(self.allowed_taxonomy_versions),
            "allowedTopicSources": sorted(self.allowed_topic_sources),
            "bootstrapAlgorithmVersion": self.bootstrap_algorithm_version,
            "decimalPrecision": self.decimal_precision,
            "eventIdAlgorithmVersion": self.event_id_algorithm_version,
            "fingerprintAlgorithmVersion": self.fingerprint_algorithm_version,
            "hashToIndexAlgorithmVersion": self.hash_to_index_algorithm_version,
            "maxEdges": self.max_edges,
            "maxEvents": self.max_events,
            "maxInputSamples": self.max_input_samples,
            "maxParentFeatures": self.max_parent_features,
            "maxSeatsPerEvent": self.max_seats_per_event,
            "maxBootstrapDraws": self.max_bootstrap_draws,
            "maxTopicMembershipRecords": self.max_topic_membership_records,
            "maxTopicsPerEvent": self.max_topics_per_event,
            "minCiSamples": self.min_ci_samples,
            "policyVersion": self.policy_version,
            "resamples": self.resamples,
            "r7AlgorithmVersion": self.r7_algorithm_version,
            "rounding": self.rounding,
            "schemaVersion": self.schema_version,
            "seedSerializationVersion": self.seed_serialization_version,
            "topicMembershipSchemaVersion": self.topic_membership_schema_version,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def allows_topic(self, membership: EventTopicMembership) -> bool:
        return (
            membership.taxonomy_id in self.allowed_taxonomy_ids
            and membership.taxonomy_version in self.allowed_taxonomy_versions
            and membership.source in self.allowed_topic_sources
        )


@dataclass(frozen=True, slots=True, order=True)
class CooccurrenceKey:
    """Canonical unordered seat pair, optionally conditioned on one topic."""

    left_seat_id: str
    right_seat_id: str
    topic_id: str | None = None

    def __post_init__(self) -> None:
        _require_seat_id(self.left_seat_id, "left_seat_id")
        _require_seat_id(self.right_seat_id, "right_seat_id")
        if self.left_seat_id >= self.right_seat_id:
            raise ValueError("co-occurrence seat pairs must be ordered and non-self")
        if self.topic_id is not None:
            _require_non_empty(self.topic_id, "topic_id")

    @property
    def canonical_tuple(self) -> tuple[str, str, str]:
        return self.left_seat_id, self.right_seat_id, self.topic_id or ""


@dataclass(frozen=True, slots=True)
class CooccurrenceMetric:
    """Descriptive distribution and deterministic bootstrap interval for one T+N."""

    horizon: int
    count: int
    mean: Decimal
    minimum: Decimal
    p25: Decimal
    p50: Decimal
    p75: Decimal
    maximum: Decimal
    ci_lower: Decimal | None
    ci_upper: Decimal | None
    ci_status: CIStatus

    def __post_init__(self) -> None:
        if self.horizon not in (1, 3, 5):
            raise ValueError("horizon must be one of 1, 3, 5")
        if type(self.count) is not int or self.count < 1:
            raise ValueError("count must be a positive integer")
        for name in ("mean", "minimum", "p25", "p50", "p75", "maximum"):
            _require_decimal(getattr(self, name), name)
        if self.ci_lower is not None:
            _require_decimal(self.ci_lower, "ci_lower")
        if self.ci_upper is not None:
            _require_decimal(self.ci_upper, "ci_upper")
        if type(self.ci_status) is not CIStatus:
            raise TypeError("ci_status must be CIStatus")
        if self.ci_status is CIStatus.INSUFFICIENT_SAMPLES and (
            self.ci_lower is not None or self.ci_upper is not None
        ):
            raise ValueError("insufficient CI must not have bounds")

    @property
    def min(self) -> Decimal:
        return self.minimum

    @property
    def max(self) -> Decimal:
        return self.maximum


@dataclass(frozen=True, slots=True)
class ParentFeatureProvenance:
    seat_id: str
    schema_version: str
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        _require_seat_id(self.seat_id)
        for name in (
            "schema_version",
            "algorithm_version",
            "policy_version",
            "policy_fingerprint",
        ):
            _require_non_empty(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class SeatEventReference:
    seat_event_key: SeatEventKey
    seat_event_id: str
    event_id_algorithm_version: str

    def __post_init__(self) -> None:
        if type(self.seat_event_key) is not SeatEventKey:
            raise TypeError("seat_event_key must be SeatEventKey")
        _require_non_empty(self.seat_event_id, "seat_event_id")
        _require_non_empty(self.event_id_algorithm_version, "event_id_algorithm_version")


@dataclass(frozen=True, slots=True)
class EventOutcomeProvenance:
    """Event-scoped selected bars retained for replayable multi-event edges."""

    event: SeatEventReference
    shared_bars: tuple[DailyPriceObservation, ...]

    def __post_init__(self) -> None:
        if type(self.event) is not SeatEventReference:
            raise TypeError("event must be SeatEventReference")
        if type(self.shared_bars) is not tuple:
            raise TypeError("shared_bars must be a tuple")
        if any(type(bar) is not DailyPriceObservation for bar in self.shared_bars):
            raise TypeError("shared_bars must contain DailyPriceObservation instances")


@dataclass(frozen=True, slots=True)
class SeatTradeEvidence:
    seat_id: str
    samples: tuple[PerformanceSample, ...]

    def __post_init__(self) -> None:
        _require_seat_id(self.seat_id)
        if type(self.samples) is not tuple:
            raise TypeError("samples must be a tuple")
        if any(type(sample) is not PerformanceSample for sample in self.samples):
            raise TypeError("samples must contain PerformanceSample instances")


@dataclass(frozen=True, slots=True)
class CooccurrenceProvenance:
    events: tuple[SeatEventReference, ...]
    event_outcomes: tuple[EventOutcomeProvenance, ...]
    parent_features: tuple[ParentFeatureProvenance, ...]
    seat_trade_evidence: tuple[SeatTradeEvidence, ...]
    shared_bars: tuple[DailyPriceObservation, ...]
    topic_memberships: tuple[EventTopicMembership, ...]
    logical_available_time: datetime

    def __post_init__(self) -> None:
        for name in (
            "events",
            "event_outcomes",
            "parent_features",
            "seat_trade_evidence",
            "shared_bars",
            "topic_memberships",
        ):
            if type(getattr(self, name)) is not tuple:
                raise TypeError(f"{name} must be a tuple")
        _require_aware(self.logical_available_time, "logical_available_time")


@dataclass(frozen=True, slots=True)
class CooccurrenceRecord:
    key: CooccurrenceKey
    support_count: int
    statistics: tuple[CooccurrenceMetric, ...]
    provenance: CooccurrenceProvenance
    semantic_label: str = "descriptive_event_study"
    as_of_semantics: str = "as_of_request_decision_time"

    def __post_init__(self) -> None:
        if type(self.support_count) is not int or self.support_count < 1:
            raise ValueError("support_count must be a positive integer")
        if type(self.statistics) is not tuple or tuple(
            metric.horizon for metric in self.statistics
        ) != (1, 3, 5):
            raise ValueError("statistics must contain T+1, T+3 and T+5 in order")
        for name in ("semantic_label", "as_of_semantics"):
            _require_non_empty(getattr(self, name), name)

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(event.seat_event_id for event in self.provenance.events)

    @property
    def logical_available_time(self) -> datetime:
        return self.provenance.logical_available_time


@dataclass(frozen=True, slots=True)
class CooccurrenceDiagnostic:
    code: str
    message: str
    seat_event_key: SeatEventKey | None = None
    seat_event_id: str | None = None
    topic_id: str | None = None
    taxonomy_id: str | None = None
    taxonomy_version: str | None = None
    source: str | None = None
    source_version: str | None = None
    evidence_id: str | None = None
    available_time: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.code, "code")
        _require_non_empty(self.message, "message")
        for name in (
            "seat_event_id",
            "topic_id",
            "taxonomy_id",
            "taxonomy_version",
            "source",
            "source_version",
            "evidence_id",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_non_empty(value, name)
        if self.available_time is not None:
            _require_aware(self.available_time, "available_time")


@dataclass(frozen=True, slots=True)
class CooccurrenceResult:
    schema_version: str
    algorithm_version: str
    policy_version: str
    policy_fingerprint: str
    window_start: date
    window_end: date
    decision_time: datetime
    records: tuple[CooccurrenceRecord, ...]
    diagnostics: tuple[CooccurrenceDiagnostic, ...]
    fingerprint: str
    semantic_label: str = "descriptive_event_study"
    as_of_semantics: str = "as_of_request_decision_time"

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "algorithm_version",
            "policy_version",
            "policy_fingerprint",
            "fingerprint",
            "semantic_label",
            "as_of_semantics",
        ):
            _require_non_empty(getattr(self, name), name)
        if type(self.window_start) is not date or type(self.window_end) is not date:
            raise TypeError("window bounds must be date")
        if self.window_end < self.window_start:
            raise ValueError("window_end must be greater than or equal to window_start")
        _require_aware(self.decision_time, "decision_time")
        if type(self.records) is not tuple or type(self.diagnostics) is not tuple:
            raise TypeError("records and diagnostics must be tuples")

    @property
    def pairs(self) -> tuple[CooccurrenceRecord, ...]:
        return self.records

    @property
    def edges(self) -> tuple[CooccurrenceRecord, ...]:
        return self.records


__all__ = [
    "BOOTSTRAP_ALGORITHM_VERSION",
    "CIStatus",
    "COOCCURRENCE_ALGORITHM_VERSION",
    "COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION",
    "COOCCURRENCE_POLICY_VERSION",
    "COOCCURRENCE_SCHEMA_VERSION",
    "CooccurrenceDiagnostic",
    "CooccurrenceInputError",
    "CooccurrenceKey",
    "CooccurrenceMetric",
    "CooccurrencePolicy",
    "CooccurrenceProvenance",
    "CooccurrenceRecord",
    "CooccurrenceResult",
    "EventOutcomeProvenance",
    "EventTopicMembership",
    "HASH_TO_INDEX_ALGORITHM_VERSION",
    "ParentFeatureProvenance",
    "R7_QUANTILE_ALGORITHM_VERSION",
    "SEAT_EVENT_ID_ALGORITHM_VERSION",
    "SEED_SERIALIZATION_VERSION",
    "SeatEventKey",
    "SeatEventReference",
    "SeatTradeEvidence",
    "TOPIC_MEMBERSHIP_SCHEMA_VERSION",
]
