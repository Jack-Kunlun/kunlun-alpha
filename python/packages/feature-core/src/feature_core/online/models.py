from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast

from feature_core.batch.models import (
    CalculatorIdentity,
    JsonValue,
    RegistrySnapshotRef,
    canonical_checksum,
    freeze_json_value,
)


class OnlineValidationError(ValueError):
    pass


class OnlineIntegrityError(RuntimeError):
    pass


class OnlineConflictError(OnlineIntegrityError):
    pass


class OnlineEventSource(StrEnum):
    MARKET = "MARKET"
    DOMAIN = "DOMAIN"


class OnlineEventDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED_LATE = "REJECTED_LATE"
    REJECTED_EXPIRED = "REJECTED_EXPIRED"


class OnlineProcessDisposition(StrEnum):
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"
    REJECTED_LATE = "REJECTED_LATE"
    REJECTED_EXPIRED = "REJECTED_EXPIRED"


class OnlineFreshness(StrEnum):
    FRESH = "FRESH"
    DEGRADED_STALE = "DEGRADED_STALE"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"


class OnlineCasStatus(StrEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"
    EXISTING_SAME = "EXISTING_SAME"
    CONFLICT = "CONFLICT"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise OnlineValidationError(f"{field} must be a non-empty string")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise OnlineValidationError(f"{field} must be timezone-aware")
    return value


def _duration(value: timedelta, field: str, *, allow_zero: bool = False) -> None:
    zero = timedelta(0)
    if value < zero or (not allow_zero and value == zero):
        qualifier = "non-negative" if allow_zero else "positive"
        raise OnlineValidationError(f"{field} must be {qualifier}")


def duration_microseconds(value: timedelta) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


@dataclass(frozen=True, slots=True)
class OnlineWindowPolicy:
    size: timedelta
    allowed_lateness: timedelta
    stale_after: timedelta
    ttl: timedelta
    replay_horizon: timedelta

    def __post_init__(self) -> None:
        _duration(self.size, "window size")
        _duration(self.allowed_lateness, "allowed_lateness", allow_zero=True)
        _duration(self.stale_after, "stale_after")
        _duration(self.ttl, "ttl")
        _duration(self.replay_horizon, "replay_horizon")
        if self.ttl <= self.stale_after:
            raise OnlineValidationError("ttl must be greater than stale_after")
        if self.replay_horizon < self.ttl + self.allowed_lateness:
            raise OnlineValidationError("replay_horizon must cover ttl plus allowed_lateness")

    @property
    def identity_checksum(self) -> str:
        return canonical_checksum(
            {
                "size_microseconds": duration_microseconds(self.size),
                "allowed_lateness_microseconds": duration_microseconds(self.allowed_lateness),
                "stale_after_microseconds": duration_microseconds(self.stale_after),
                "ttl_microseconds": duration_microseconds(self.ttl),
                "replay_horizon_microseconds": duration_microseconds(self.replay_horizon),
            },
        )


@dataclass(frozen=True, slots=True)
class EventTimeWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        _aware(self.start, "window start")
        _aware(self.end, "window end")
        if self.start >= self.end:
            raise OnlineValidationError("event-time window must be non-empty")


@dataclass(frozen=True, slots=True)
class OnlineFeatureEvent:
    event_id: str
    entity_id: str
    source: OnlineEventSource
    contract_name: str
    contract_version: str
    source_revision: str
    event_time: datetime
    available_time: datetime
    ingest_time: datetime
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        _text(self.entity_id, "entity_id")
        if type(cast(object, self.source)) is not OnlineEventSource:
            raise OnlineValidationError("source must be an OnlineEventSource")
        _text(self.contract_name, "contract_name")
        _text(self.contract_version, "contract_version")
        _text(self.source_revision, "source_revision")
        _aware(self.event_time, "event_time")
        _aware(self.available_time, "available_time")
        _aware(self.ingest_time, "ingest_time")
        if self.available_time < self.event_time:
            raise OnlineValidationError("available_time cannot precede event_time")
        if self.ingest_time < self.available_time:
            raise OnlineValidationError("ingest_time cannot precede available_time")
        frozen = freeze_json_value(self.payload)
        if not isinstance(frozen, Mapping):
            raise OnlineValidationError("event payload must be an object")
        object.__setattr__(self, "payload", frozen)

    @property
    def content_checksum(self) -> str:
        return canonical_checksum(self)


@dataclass(frozen=True, slots=True)
class OnlineInputLineage:
    event_id: str
    content_checksum: str
    source_revision: str
    event_time: datetime
    available_time: datetime

    @classmethod
    def from_event(cls, event: OnlineFeatureEvent) -> OnlineInputLineage:
        return cls(
            event_id=event.event_id,
            content_checksum=event.content_checksum,
            source_revision=event.source_revision,
            event_time=event.event_time,
            available_time=event.available_time,
        )


@dataclass(frozen=True, slots=True)
class OnlineEventReceipt:
    event_id: str
    content_checksum: str
    disposition: OnlineEventDisposition
    retain_until: datetime

    def __post_init__(self) -> None:
        _text(self.event_id, "receipt event_id")
        _text(self.content_checksum, "receipt checksum")
        if type(cast(object, self.disposition)) is not OnlineEventDisposition:
            raise OnlineValidationError("receipt disposition type is invalid")
        _aware(self.retain_until, "receipt retain_until")


@dataclass(frozen=True, slots=True)
class OnlineRejection:
    event_id: str
    content_checksum: str
    reason: OnlineEventDisposition
    event_time: datetime
    observed_watermark: datetime | None
    processing_time: datetime

    def __post_init__(self) -> None:
        if self.reason is OnlineEventDisposition.ACCEPTED:
            raise OnlineValidationError("rejection reason cannot be ACCEPTED")
        _text(self.content_checksum, "rejection content_checksum")
        _aware(self.event_time, "rejected event_time")
        if self.observed_watermark is not None:
            _aware(self.observed_watermark, "observed_watermark")
        _aware(self.processing_time, "rejection processing_time")


@dataclass(frozen=True, slots=True)
class OnlineFeatureValue:
    registry_ref: RegistrySnapshotRef
    entity_id: str
    window: EventTimeWindow
    value: JsonValue
    input_lineage: tuple[OnlineInputLineage, ...]
    input_checksum: str
    calculator_identity: CalculatorIdentity
    policy_checksum: str
    available_time: datetime
    computed_at: datetime
    stale_at: datetime
    expires_at: datetime
    state_revision: int

    def __post_init__(self) -> None:
        if type(cast(object, self.registry_ref)) is not RegistrySnapshotRef:
            raise OnlineValidationError("online value registry_ref type is invalid")
        _text(self.entity_id, "online value entity_id")
        if type(cast(object, self.window)) is not EventTimeWindow:
            raise OnlineValidationError("online value window type is invalid")
        event_ids = [item.event_id for item in self.input_lineage]
        if not event_ids or len(event_ids) != len(set(event_ids)):
            raise OnlineValidationError("online value lineage must be unique and non-empty")
        _text(self.input_checksum, "online value input_checksum")
        if type(cast(object, self.calculator_identity)) is not CalculatorIdentity:
            raise OnlineValidationError("calculator identity type is invalid")
        _text(self.policy_checksum, "policy_checksum")
        _aware(self.available_time, "online value available_time")
        _aware(self.computed_at, "online value computed_at")
        _aware(self.stale_at, "online value stale_at")
        _aware(self.expires_at, "online value expires_at")
        if self.computed_at < self.available_time:
            raise OnlineValidationError("computed_at cannot precede available_time")
        if not self.available_time < self.stale_at < self.expires_at:
            raise OnlineValidationError(
                "online value times must satisfy available < stale < expires"
            )
        if type(self.state_revision) is not int or self.state_revision < 1:
            raise OnlineValidationError("state_revision must be a positive integer")

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(item.event_id for item in self.input_lineage)

    @property
    def output_checksum(self) -> str:
        return canonical_checksum(self)


@dataclass(frozen=True, slots=True)
class OnlineStreamState:
    stream_key: str
    registry_ref: RegistrySnapshotRef
    calculator_identity: CalculatorIdentity
    entity_id: str
    policy_checksum: str
    revision: int
    last_processing_time: datetime | None
    max_event_time: datetime | None
    watermark: datetime | None
    watermark_anchor: OnlineFeatureEvent | None
    events: tuple[OnlineFeatureEvent, ...]
    accepted_evidence: tuple[OnlineFeatureEvent, ...]
    receipts: tuple[OnlineEventReceipt, ...]
    values: tuple[OnlineFeatureValue, ...]
    rejections: tuple[OnlineRejection, ...]

    def __post_init__(self) -> None:
        _text(self.stream_key, "stream_key")
        if type(cast(object, self.registry_ref)) is not RegistrySnapshotRef:
            raise OnlineValidationError("state registry_ref type is invalid")
        if type(cast(object, self.calculator_identity)) is not CalculatorIdentity:
            raise OnlineValidationError("state calculator identity type is invalid")
        _text(self.entity_id, "state entity_id")
        _text(self.policy_checksum, "state policy_checksum")
        if type(self.revision) is not int or self.revision < 0:
            raise OnlineValidationError("state revision must be a non-negative integer")
        if self.last_processing_time is not None:
            _aware(self.last_processing_time, "last_processing_time")
        if self.max_event_time is not None:
            _aware(self.max_event_time, "state max_event_time")
        if self.watermark is not None:
            _aware(self.watermark, "state watermark")
        if (self.max_event_time is None) != (self.watermark is None):
            raise OnlineValidationError("max_event_time and watermark must be set together")
        if (
            self.max_event_time is not None
            and self.watermark is not None
            and self.watermark > self.max_event_time
        ):
            raise OnlineValidationError("watermark cannot exceed max_event_time")

    @classmethod
    def empty(
        cls,
        *,
        stream_key: str,
        registry_ref: RegistrySnapshotRef,
        calculator_identity: CalculatorIdentity,
        entity_id: str,
        policy_checksum: str,
    ) -> OnlineStreamState:
        return cls(
            stream_key=stream_key,
            registry_ref=registry_ref,
            calculator_identity=calculator_identity,
            entity_id=entity_id,
            policy_checksum=policy_checksum,
            revision=0,
            last_processing_time=None,
            max_event_time=None,
            watermark=None,
            watermark_anchor=None,
            events=(),
            accepted_evidence=(),
            receipts=(),
            values=(),
            rejections=(),
        )

    @property
    def state_checksum(self) -> str:
        return canonical_checksum(self)


@dataclass(frozen=True, slots=True)
class OnlineStateEnvelope:
    state: OnlineStreamState
    retain_until: datetime
    integrity_tag: str

    def __post_init__(self) -> None:
        if type(cast(object, self.state)) is not OnlineStreamState:
            raise OnlineValidationError("envelope state type is invalid")
        _aware(self.retain_until, "envelope retain_until")
        _text(self.integrity_tag, "envelope integrity_tag")


@dataclass(frozen=True, slots=True)
class OnlineCasResult:
    status: OnlineCasStatus
    persisted: OnlineStateEnvelope | None

    def __post_init__(self) -> None:
        if type(cast(object, self.status)) is not OnlineCasStatus:
            raise OnlineIntegrityError("CAS status must be an exact OnlineCasStatus")
        if self.status is not OnlineCasStatus.CONFLICT and self.persisted is None:
            raise OnlineIntegrityError("successful CAS must carry the persisted envelope")


@dataclass(frozen=True, slots=True)
class OnlineProcessResult:
    disposition: OnlineProcessDisposition
    state: OnlineStreamState
    value: OnlineFeatureValue | None
    rejection: OnlineRejection | None


@dataclass(frozen=True, slots=True)
class OnlineReadResult:
    freshness: OnlineFreshness
    value: OnlineFeatureValue | None
