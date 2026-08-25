"""Pure, fake-port claim extraction pipeline models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from kol_core.extraction import (
    CLAIM_EXTRACTION_ALGORITHM_VERSION,
    ClaimExtractionCandidate,
    EvidenceGrade,
)

from intelligence_engine.llm.models import ResolvedProfile

CLAIMS_PIPELINE_VERSION: Final = "kol-claim-pipeline-v1"
RAW_CANDIDATE_SCHEMA_VERSION: Final = "claim-extraction-response-v1"


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, name: str, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _strict_int(value: object, name: str, minimum: int = 0, maximum: int = 10_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a strict bounded integer")
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ClaimContentSource:
    source_index: int
    content_id: str
    content_version: str
    content_revision_id: str
    text: str
    available_time: datetime
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    source: str
    source_version: str
    evidence_grade: EvidenceGrade
    evidence_grade_version: str = "evidence-grade-v1"
    authorized: bool = True
    deleted: bool = False
    deleted_at: datetime | None = None
    deletion_reason: str | None = None

    def __post_init__(self) -> None:
        _strict_int(self.source_index, "source_index", 0, 100_000)
        _text(self.content_id, "content_id")
        _text(self.content_version, "content_version")
        _text(self.content_revision_id, "content_revision_id")
        _text(self.text, "text", 1_000_000)
        _text(self.source, "source")
        _text(self.source_version, "source_version")
        for value, name in (
            (self.available_time, "available_time"),
            (self.publish_time, "publish_time"),
            (self.ingest_time, "ingest_time"),
            (self.processing_time, "processing_time"),
        ):
            _aware(value, name)
        if not self.publish_time <= self.ingest_time <= self.processing_time <= self.available_time:
            raise ValueError(
                "source times must satisfy publish <= ingest <= processing <= available"
            )
        if type(self.authorized) is not bool or type(self.deleted) is not bool:
            raise TypeError("authorized and deleted must be strict bools")
        if self.evidence_grade_version != "evidence-grade-v1":
            raise ValueError("unsupported evidence grade version")
        if self.deleted and self.deleted_at is None:
            raise ValueError("deleted source must have deleted_at")
        if not self.deleted and (self.deleted_at is not None or self.deletion_reason is not None):
            raise ValueError("non-deleted source carries tombstone metadata")


@dataclass(frozen=True, slots=True)
class ClaimMediaSegment:
    index: int
    text: str
    start_offset: int
    end_offset: int
    start_ms: int | None = None
    end_ms: int | None = None
    confidence_bps: int = 10_000
    quality_bps: int = 10_000

    def __post_init__(self) -> None:
        _strict_int(self.index, "segment index", 0, 100_000)
        _text(self.text, "segment text", 200_000)
        _strict_int(self.start_offset, "start_offset", 0, 10_000_000)
        _strict_int(self.end_offset, "end_offset", 1, 10_000_000)
        if self.end_offset <= self.start_offset:
            raise ValueError("segment offsets must increase")
        for value, name in ((self.start_ms, "start_ms"), (self.end_ms, "end_ms")):
            if value is not None:
                _strict_int(value, name, 0, 864_000_000)
        if self.start_ms is not None and self.end_ms is not None and self.end_ms <= self.start_ms:
            raise ValueError("segment time range must increase")
        _strict_int(self.confidence_bps, "segment confidence_bps")
        _strict_int(self.quality_bps, "segment quality_bps")


@dataclass(frozen=True, slots=True)
class ClaimMediaSource:
    source_index: int
    content_id: str
    content_version: str
    content_revision_id: str
    evidence_id: str
    evidence_revision_id: str
    media_id: str
    media_version: str
    media_manifest_revision_id: str
    text: str
    segments: tuple[ClaimMediaSegment, ...]
    available_time: datetime
    content_available_time: datetime
    evidence_available_time: datetime
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    source: str
    source_version: str
    evidence_grade: EvidenceGrade
    overall_confidence_bps: int
    overall_quality_bps: int
    evidence_grade_version: str = "evidence-grade-v1"
    authorized: bool = True
    deleted: bool = False

    def __post_init__(self) -> None:
        _strict_int(self.source_index, "source_index", 0, 100_000)
        _text(self.content_id, "content_id")
        _text(self.content_version, "content_version")
        _text(self.content_revision_id, "content_revision_id")
        _text(self.evidence_id, "evidence_id")
        _text(self.evidence_revision_id, "evidence_revision_id")
        _text(self.media_id, "media_id")
        _text(self.media_version, "media_version")
        _text(self.media_manifest_revision_id, "media_manifest_revision_id")
        _text(self.text, "text", 2_000_000)
        _text(self.source, "source")
        _text(self.source_version, "source_version")
        if (
            type(self.segments) is not tuple
            or not self.segments
            or any(type(item) is not ClaimMediaSegment for item in self.segments)
        ):
            raise ValueError("media source requires typed segments")
        if tuple(item.index for item in self.segments) != tuple(
            sorted(item.index for item in self.segments)
        ):
            raise ValueError("segments must be sorted")
        for value, name in (
            (self.available_time, "available_time"),
            (self.content_available_time, "content_available_time"),
            (self.evidence_available_time, "evidence_available_time"),
            (self.publish_time, "publish_time"),
            (self.ingest_time, "ingest_time"),
            (self.processing_time, "processing_time"),
        ):
            _aware(value, name)
        if not self.publish_time <= self.ingest_time <= self.processing_time <= self.available_time:
            raise ValueError(
                "media source times must satisfy publish <= ingest <= processing <= available"
            )
        if self.content_available_time > self.evidence_available_time:
            raise ValueError("content availability must not exceed evidence availability")
        if self.evidence_available_time > self.available_time:
            raise ValueError("evidence availability must not exceed media availability")
        _strict_int(self.overall_confidence_bps, "overall_confidence_bps")
        _strict_int(self.overall_quality_bps, "overall_quality_bps")
        if type(self.authorized) is not bool or type(self.deleted) is not bool:
            raise TypeError("authorized and deleted must be strict bools")
        if self.evidence_grade_version != "evidence-grade-v1":
            raise ValueError("unsupported evidence grade version")


ClaimSource = ClaimContentSource | ClaimMediaSource


def _source_fingerprint(item: ClaimSource) -> str:
    value: dict[str, object] = {
        "availableTime": item.available_time.astimezone(UTC).isoformat(),
        "authorized": item.authorized,
        "contentId": item.content_id,
        "contentRevisionId": item.content_revision_id,
        "contentVersion": item.content_version,
        "deleted": item.deleted,
        "ingestTime": item.ingest_time.astimezone(UTC).isoformat(),
        "processingTime": item.processing_time.astimezone(UTC).isoformat(),
        "publishTime": item.publish_time.astimezone(UTC).isoformat(),
        "source": item.source,
        "sourceVersion": item.source_version,
        "text": item.text,
    }
    if isinstance(item, ClaimContentSource):
        value["deletedAt"] = (
            None if item.deleted_at is None else item.deleted_at.astimezone(UTC).isoformat()
        )
        value["deletionReason"] = item.deletion_reason
    else:
        value.update(
            {
                "evidenceAvailableTime": item.evidence_available_time.astimezone(UTC).isoformat(),
                "evidenceGrade": item.evidence_grade.value,
                "evidenceGradeVersion": item.evidence_grade_version,
                "evidenceId": item.evidence_id,
                "evidenceRevisionId": item.evidence_revision_id,
                "mediaId": item.media_id,
                "mediaManifestRevisionId": item.media_manifest_revision_id,
                "mediaVersion": item.media_version,
                "overallConfidenceBps": item.overall_confidence_bps,
                "overallQualityBps": item.overall_quality_bps,
                "segments": [
                    {
                        "confidenceBps": segment.confidence_bps,
                        "endOffset": segment.end_offset,
                        "endMs": segment.end_ms,
                        "index": segment.index,
                        "qualityBps": segment.quality_bps,
                        "startOffset": segment.start_offset,
                        "startMs": segment.start_ms,
                        "text": segment.text,
                    }
                    for segment in item.segments
                ],
            }
        )
    return _digest(value)


@dataclass(frozen=True, slots=True)
class ClaimExtractionPolicy:
    max_response_bytes: int = 256_000
    max_statement_codepoints: int = 10_000
    max_anchor_count: int = 32
    max_anchor_codepoints: int = 10_000
    minimum_confidence_bps: int = 7_000
    max_attempts: int = 3
    pipeline_version: str = CLAIMS_PIPELINE_VERSION
    algorithm_version: str = CLAIM_EXTRACTION_ALGORITHM_VERSION
    raw_schema_version: str = RAW_CANDIDATE_SCHEMA_VERSION
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name, maximum in (
            (self.max_response_bytes, "max_response_bytes", 10_000_000),
            (self.max_statement_codepoints, "max_statement_codepoints", 100_000),
            (self.max_anchor_count, "max_anchor_count", 1000),
            (self.max_anchor_codepoints, "max_anchor_codepoints", 100_000),
            (self.minimum_confidence_bps, "minimum_confidence_bps", 10_000),
            (self.max_attempts, "max_attempts", 10),
        ):
            _strict_int(value, name, 1, maximum)
        _text(self.pipeline_version, "pipeline_version")
        _text(self.algorithm_version, "algorithm_version")
        _text(self.raw_schema_version, "raw_schema_version")
        object.__setattr__(
            self,
            "fingerprint",
            _digest(
                {
                    "algorithmVersion": self.algorithm_version,
                    "maxAnchorCodepoints": self.max_anchor_codepoints,
                    "maxAnchorCount": self.max_anchor_count,
                    "maxAttempts": self.max_attempts,
                    "maxResponseBytes": self.max_response_bytes,
                    "maxStatementCodepoints": self.max_statement_codepoints,
                    "minimumConfidenceBps": self.minimum_confidence_bps,
                    "pipelineVersion": self.pipeline_version,
                    "rawSchemaVersion": self.raw_schema_version,
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class ClaimExtractionRequest:
    request_id: str
    extraction_run_id: str
    sources: tuple[ClaimSource, ...]
    decision_time: datetime
    processing_time: datetime
    resolved_profile: ResolvedProfile
    attempt: int = 1
    instrument_index: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        _text(self.extraction_run_id, "extraction_run_id")
        _aware(self.decision_time, "decision_time")
        _aware(self.processing_time, "processing_time")
        _strict_int(self.attempt, "attempt", 1, 100)
        if type(self.sources) is not tuple or not self.sources:
            raise ValueError("sources must be a non-empty tuple")
        if tuple(item.source_index for item in self.sources) != tuple(range(len(self.sources))):
            raise ValueError("source indexes must be contiguous and ordered")
        for code in self.instrument_index:
            _text(code, "instrument_index", 9)

    @property
    def idempotency_key(self) -> str:
        return _digest(
            {
                "decisionTime": self.decision_time.astimezone(UTC).isoformat(),
                "profileConfigurationFingerprint": self.resolved_profile.configuration_fingerprint,
                "requestId": self.request_id,
                "runId": self.extraction_run_id,
                "sources": [
                    {
                        "availableTime": item.available_time.astimezone(UTC).isoformat(),
                        "sourceFingerprint": _source_fingerprint(item),
                        "sourceIndex": item.source_index,
                    }
                    for item in self.sources
                ],
                "processingTime": self.processing_time.astimezone(UTC).isoformat(),
                "attempt": self.attempt,
                "instrumentIndex": list(self.instrument_index),
            }
        )

    def effective_idempotency_key(self, policy_fingerprint: str) -> str:
        _text(policy_fingerprint, "policy_fingerprint", 64)
        if len(policy_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in policy_fingerprint
        ):
            raise ValueError("policy_fingerprint must be lowercase SHA-256")
        return _digest(
            {"policyFingerprint": policy_fingerprint, "requestFingerprint": self.idempotency_key}
        )


class ClaimProcessStatus(StrEnum):
    COMMITTED = "COMMITTED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    REJECTED = "REJECTED"


class ClaimFailureReason(StrEnum):
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    STORE_TRANSIENT = "STORE_TRANSIENT"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    CONFLICT = "CONFLICT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    EXTRACTOR_FAILURE = "EXTRACTOR_FAILURE"


class ClaimTransientError(Exception):
    pass


class ClaimTimeoutError(ClaimTransientError):
    pass


class ClaimRateLimitError(ClaimTransientError):
    pass


class ClaimTemporaryUnavailableError(ClaimTransientError):
    pass


class ClaimStoreTransientError(ClaimTransientError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimAuditRecord:
    audit_id: str
    status: str
    reason: str
    request_fingerprint: str
    policy_fingerprint: str
    configuration_fingerprint: str
    run_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ClaimProcessResult:
    status: ClaimProcessStatus
    idempotency_key: str
    candidate: ClaimExtractionCandidate | None = None
    failure: ClaimFailureReason | None = None
    audit: ClaimAuditRecord | None = None


__all__ = [
    "CLAIMS_PIPELINE_VERSION",
    "RAW_CANDIDATE_SCHEMA_VERSION",
    "ClaimAuditRecord",
    "ClaimContentSource",
    "ClaimExtractionPolicy",
    "ClaimExtractionRequest",
    "ClaimFailureReason",
    "ClaimMediaSegment",
    "ClaimMediaSource",
    "ClaimProcessResult",
    "ClaimProcessStatus",
    "ClaimRateLimitError",
    "ClaimStoreTransientError",
    "ClaimTemporaryUnavailableError",
    "ClaimTimeoutError",
    "ClaimSource",
]
