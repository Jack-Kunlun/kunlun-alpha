"""Typed queue, provider, retry, result, and storage boundaries."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol

from event_core.models import MarketEvent

from intelligence_engine.llm import ModelSpec

EVENT_EXTRACTION_PIPELINE_VERSION = "event-extraction-pipeline-v1"
MAX_PROVIDER_OUTPUT_CHARACTERS = 500_000

_HEX_64 = re.compile(r"[0-9a-f]{64}")


def _text(value: object, field_name: str, *, maximum: int = 256) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds its maximum length")
    return value


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


def _identity_digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Trusted source facts used to verify model evidence before persistence."""

    content_record_id: str
    content_version_id: str
    source_id: str
    source_version: str
    raw_text: str
    publish_time: datetime
    available_time: datetime
    usage_allowed: bool
    deleted: bool = False
    deleted_at: datetime | None = None
    content_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.content_record_id, "content_record_id")
        version_id = _text(self.content_version_id, "content_version_id")
        if _HEX_64.fullmatch(version_id) is None:
            raise ValueError("content_version_id must be a lowercase SHA-256 digest")
        _text(self.source_id, "source_id")
        _text(self.source_version, "source_version")
        raw_text = _text(self.raw_text, "raw_text", maximum=2_000_000)
        publish_time = _aware_utc(self.publish_time, "publish_time")
        available_time = _aware_utc(self.available_time, "available_time")
        if publish_time > available_time:
            raise ValueError("publish_time must be <= available_time")
        if type(self.usage_allowed) is not bool:
            raise TypeError("usage_allowed must be a strict boolean")
        if type(self.deleted) is not bool:
            raise TypeError("deleted must be a strict boolean")
        deleted_at = self.deleted_at
        if self.deleted:
            if deleted_at is None:
                raise ValueError("deleted source must include deleted_at")
            deleted_at = _aware_utc(deleted_at, "deleted_at")
            if deleted_at < publish_time:
                raise ValueError("deleted_at must be >= publish_time")
        elif deleted_at is not None:
            raise ValueError("non-deleted source must not include deleted_at")
        object.__setattr__(self, "publish_time", publish_time)
        object.__setattr__(self, "available_time", available_time)
        object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(
            self, "content_fingerprint", hashlib.sha256(raw_text.encode()).hexdigest()
        )

    def is_usable(self, decision_time: datetime) -> bool:
        """Apply availability, authorization, and point-in-time deletion gates."""
        moment = _aware_utc(decision_time, "decision_time")
        if not self.usage_allowed or self.available_time > moment:
            return False
        return not (self.deleted and self.deleted_at is not None and self.deleted_at <= moment)


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """One retryable queue command with a stable, derived idempotency key."""

    request_id: str
    extraction_run_id: str
    profile_id: str
    routing_key: str
    document: SourceDocument
    decision_time: datetime
    processing_time: datetime
    attempt: int
    idempotency_key: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        _text(self.extraction_run_id, "extraction_run_id")
        _text(self.profile_id, "profile_id")
        _text(self.routing_key, "routing_key")
        if type(self.document) is not SourceDocument:
            raise TypeError("document must be a SourceDocument")
        decision_time = _aware_utc(self.decision_time, "decision_time")
        processing_time = _aware_utc(self.processing_time, "processing_time")
        if processing_time < decision_time:
            raise ValueError("processing_time must be >= decision_time")
        attempt = _strict_integer(self.attempt, "attempt")
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        object.__setattr__(self, "decision_time", decision_time)
        object.__setattr__(self, "processing_time", processing_time)
        object.__setattr__(
            self,
            "idempotency_key",
            _identity_digest(
                EVENT_EXTRACTION_PIPELINE_VERSION,
                self.document.content_version_id,
                self.document.content_fingerprint,
                self.profile_id,
                self.routing_key,
                decision_time.isoformat(),
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderInvocation:
    """Credential-free provider input prepared from a registered profile."""

    request_id: str
    extraction_run_id: str
    attempt: int
    rendered_prompt: str
    model: ModelSpec
    final_output_schema_version: str
    configuration_fingerprint: str


class ExtractionStatus(str, Enum):
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    REJECTED = "REJECTED"


class FailureReason(str, Enum):
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MODEL_TRANSIENT = "MODEL_TRANSIENT"
    MODEL_PERMANENT = "MODEL_PERMANENT"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    INVALID_JSON = "INVALID_JSON"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    EVIDENCE_MISMATCH = "EVIDENCE_MISMATCH"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    EVENT_VALIDATION = "EVENT_VALIDATION"
    STORE_TRANSIENT = "STORE_TRANSIENT"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


class CommitDisposition(str, Enum):
    COMMITTED = "COMMITTED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


@dataclass(frozen=True, slots=True)
class FailureRecord:
    """Isolated provider failure evidence; never part of the fact layer."""

    reason: FailureReason
    detail_code: str
    raw_provider_output: str | None = None
    raw_output_sha256: str | None = field(init=False)

    def __post_init__(self) -> None:
        if type(self.reason) is not FailureReason:
            raise TypeError("reason must be a FailureReason")
        _text(self.detail_code, "detail_code")
        if self.raw_provider_output is not None and type(self.raw_provider_output) is not str:
            raise TypeError("raw_provider_output must be a string or None")
        digest = (
            hashlib.sha256(self.raw_provider_output.encode()).hexdigest()
            if self.raw_provider_output is not None
            else None
        )
        object.__setattr__(self, "raw_output_sha256", digest)


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Queue disposition and complete audit payload for one attempt."""

    status: ExtractionStatus
    request_id: str
    extraction_run_id: str
    idempotency_key: str
    attempt: int
    recorded_at: datetime
    event: MarketEvent | None = None
    failure: FailureRecord | None = None
    retry_at: datetime | None = None
    deployment_id: str | None = None
    configuration_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not ExtractionStatus:
            raise TypeError("status must be an ExtractionStatus")
        _text(self.request_id, "request_id")
        _text(self.extraction_run_id, "extraction_run_id")
        key = _text(self.idempotency_key, "idempotency_key")
        if _HEX_64.fullmatch(key) is None:
            raise ValueError("idempotency_key must be a lowercase SHA-256 digest")
        _strict_integer(self.attempt, "attempt")
        recorded_at = _aware_utc(self.recorded_at, "recorded_at")
        retry_at = self.retry_at
        if retry_at is not None:
            retry_at = _aware_utc(retry_at, "retry_at")
        if self.status in (ExtractionStatus.STORED, ExtractionStatus.DUPLICATE):
            if (
                type(self.event) is not MarketEvent
                or self.failure is not None
                or retry_at is not None
            ):
                raise ValueError("successful result must contain only an event")
        elif self.status is ExtractionStatus.RETRY_SCHEDULED:
            if self.event is not None or self.failure is None or retry_at is None:
                raise ValueError("retry result must contain a failure and retry_at")
        elif self.event is not None or self.failure is None or retry_at is not None:
            raise ValueError("rejected result must contain only a failure")
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "retry_at", retry_at)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential retry policy."""

    max_attempts: int = 3
    initial_delay_seconds: int = 5
    maximum_delay_seconds: int = 60

    def __post_init__(self) -> None:
        maximum_attempts = _strict_integer(self.max_attempts, "max_attempts")
        initial = _strict_integer(self.initial_delay_seconds, "initial_delay_seconds")
        maximum = _strict_integer(self.maximum_delay_seconds, "maximum_delay_seconds")
        if not 1 <= maximum_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if initial < 1 or maximum < initial:
            raise ValueError("retry delays must be positive and bounded")

    def delay_after(self, failed_attempt: int) -> timedelta:
        attempt = _strict_integer(failed_attempt, "failed_attempt")
        if attempt < 1:
            raise ValueError("failed_attempt must be >= 1")
        exponent = min(attempt - 1, 30)
        seconds = min(self.initial_delay_seconds * 2**exponent, self.maximum_delay_seconds)
        return timedelta(seconds=seconds)


class ModelGatewayError(RuntimeError):
    """Known provider boundary failure."""


class ModelTimeoutError(ModelGatewayError):
    pass


class ModelRateLimitError(ModelGatewayError):
    pass


class ModelTransientError(ModelGatewayError):
    pass


class ModelPermanentError(ModelGatewayError):
    pass


class ExtractionStoreTransientError(RuntimeError):
    """Retryable storage boundary failure."""


class ModelGateway(Protocol):
    def generate(self, invocation: ProviderInvocation) -> str:
        """Return raw untrusted provider output or raise a classified error."""
        ...


class ExtractionStore(Protocol):
    def find_committed(self, idempotency_key: str) -> MarketEvent | None:
        """Return an already committed fact-layer event."""
        ...

    def commit_validated(
        self,
        idempotency_key: str,
        event: MarketEvent,
        result: ExtractionResult,
    ) -> CommitDisposition:
        """Atomically commit the validated event and its STORED audit record."""
        ...

    def record_outcome(self, result: ExtractionResult) -> None:
        """Persist a duplicate, retry, or isolated rejection audit record."""
        ...


__all__ = [
    "CommitDisposition",
    "EVENT_EXTRACTION_PIPELINE_VERSION",
    "ExtractionRequest",
    "ExtractionResult",
    "ExtractionStatus",
    "ExtractionStore",
    "ExtractionStoreTransientError",
    "FailureReason",
    "FailureRecord",
    "MAX_PROVIDER_OUTPUT_CHARACTERS",
    "ModelGateway",
    "ModelGatewayError",
    "ModelPermanentError",
    "ModelRateLimitError",
    "ModelTimeoutError",
    "ModelTransientError",
    "ProviderInvocation",
    "RetryPolicy",
    "SourceDocument",
]
