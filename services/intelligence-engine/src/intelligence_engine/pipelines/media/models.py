"""Immutable domain objects for the P4-N07 media text evidence pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from intelligence_engine.llm.models import ResolvedProfile

MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION = "kol-media-text-evidence-v1"
MEDIA_PIPELINE_VERSION = "media-text-pipeline-v1"
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class MediaKind(StrEnum):
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"


class MediaProcessorKind(StrEnum):
    ASR = "ASR"
    OCR = "OCR"


class MediaProcessStatus(StrEnum):
    COMMITTED = "COMMITTED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    TERMINAL = "TERMINAL"


class MediaCheckpointPhase(StrEnum):
    RECOGNIZING = "RECOGNIZING"
    READY_TO_COMMIT = "READY_TO_COMMIT"


class MediaClaimStatus(StrEnum):
    CLAIMED = "CLAIMED"
    EXISTING = "EXISTING"
    IN_PROGRESS = "IN_PROGRESS"
    CONFLICT = "CONFLICT"


class MediaFailureReason(StrEnum):
    FUTURE_MEDIA = "future_media"
    UNAUTHORIZED = "unauthorized"
    DELETED = "deleted"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    SILENCE = "silence"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    TEMPORARY_UNAVAILABLE = "temporary_unavailable"
    STORE_TRANSIENT = "store_transient"
    RETRY_EXHAUSTED = "retry_exhausted"
    INVALID_CANDIDATE = "invalid_candidate"
    DECODE_FAILURE = "decode_failure"
    TOO_LONG = "too_long"
    STORE_CONFLICT = "store_conflict"
    BUDGET_EXCEEDED = "budget_exceeded"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"


class MediaPipelineError(Exception):
    """Base error for a deterministic media processing port."""


class MediaSilenceError(MediaPipelineError):
    """Recognizer completed with no usable speech/text signal."""


class MediaTimeoutError(MediaPipelineError):
    """Recognizer timed out and may be retried."""


class MediaRateLimitError(MediaPipelineError):
    """Recognizer was rate limited and may be retried."""


class MediaTemporaryUnavailableError(MediaPipelineError):
    """Recognizer is temporarily unavailable and may be retried."""


class MediaStoreTransientError(MediaPipelineError):
    """Evidence store failed transiently and may be retried."""


class MediaDecodeError(MediaPipelineError):
    """Media cannot be decoded by the fake processing port."""


class MediaChecksumMismatchError(MediaPipelineError):
    """Reader-side checksum verification failed before recognition."""


class MediaTooLongError(MediaPipelineError):
    """Media exceeds the configured bounded processing policy."""


class MediaAuditStatus(StrEnum):
    QUALITY_REVIEW_REQUIRED = "QUALITY_REVIEW_REQUIRED"
    SILENCE = "SILENCE"
    NO_SPEECH = "NO_SPEECH"
    DUPLICATE_FRAME = "DUPLICATE_FRAME"
    DECODE_FAILED = "DECODE_FAILED"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    INVALID_CANDIDATE = "INVALID_CANDIDATE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    TRANSIENT_RETRY = "TRANSIENT_RETRY"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    COMMITTED = "COMMITTED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    DELETED = "DELETED"
    TOMBSTONED = "TOMBSTONED"
    CONFLICT = "CONFLICT"


class MediaAuditReason(StrEnum):
    QUALITY_REVIEW_REQUIRED = "quality_review_required"
    SILENCE = "silence"
    NO_SPEECH = "no_speech"
    DUPLICATE_FRAME = "duplicate_frame"
    DECODE_FAILED = "decode_failed"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    INVALID_CANDIDATE = "invalid_candidate"
    BUDGET_EXCEEDED = "budget_exceeded"
    TRANSIENT_RETRY = "transient_retry"
    RETRY_EXHAUSTED = "retry_exhausted"
    COMMITTED = "committed"
    ALREADY_COMMITTED = "already_committed"
    DELETED = "deleted"
    TOMBSTONED = "tombstoned"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class MediaAuditRecord:
    audit_id: str
    status: MediaAuditStatus
    reason: MediaAuditReason
    attempt: int
    manifest_fingerprint: str
    manifest_revision_fingerprint: str
    evidence_fingerprint: str | None
    evidence_revision_fingerprint: str | None
    recognition_run_fingerprint: str
    policy_fingerprint: str
    configuration_fingerprint: str
    logical_time: datetime

    def __post_init__(self) -> None:
        for value, name in (
            (self.audit_id, "audit_id"),
            (self.manifest_fingerprint, "manifest_fingerprint"),
            (self.manifest_revision_fingerprint, "manifest_revision_fingerprint"),
            (self.recognition_run_fingerprint, "recognition_run_fingerprint"),
        ):
            if _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if type(self.status) is not MediaAuditStatus or type(self.reason) is not MediaAuditReason:
            raise TypeError("audit status and reason must use their enums")
        attempt = _strict_int(self.attempt, "attempt")
        if attempt < 0:
            raise ValueError("attempt must be non-negative")
        for value, name in (
            (self.policy_fingerprint, "policy_fingerprint"),
            (self.configuration_fingerprint, "configuration_fingerprint"),
            (self.evidence_fingerprint, "evidence_fingerprint"),
            (self.evidence_revision_fingerprint, "evidence_revision_fingerprint"),
        ):
            if value is not None and (
                type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None
            ):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "logical_time", _aware_utc(self.logical_time, "logical_time"))

    def payload(self) -> dict[str, object]:
        return {
            "auditId": self.audit_id,
            "attempt": self.attempt,
            "configurationFingerprint": self.configuration_fingerprint,
            "evidenceFingerprint": self.evidence_fingerprint,
            "evidenceRevisionFingerprint": self.evidence_revision_fingerprint,
            "logicalTime": _timestamp(self.logical_time),
            "manifestFingerprint": self.manifest_fingerprint,
            "manifestRevisionFingerprint": self.manifest_revision_fingerprint,
            "policyFingerprint": self.policy_fingerprint,
            "reason": self.reason.value,
            "recognitionRunFingerprint": self.recognition_run_fingerprint,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class MediaChunk:
    index: int
    data: bytes
    start_ms: int | None
    end_ms: int | None
    frame_identity: str | None = None
    width: int | None = None
    height: int | None = None
    bbox_context: MediaBoundingBox | None = None
    digest: str = field(init=False)
    chunk_identity: str = field(init=False)
    prefix_byte_count: int = 0
    prefix_sha256: str = ""

    def __post_init__(self) -> None:
        index = _strict_int(self.index, "index")
        if index < 0 or type(self.data) is not bytes or not self.data:
            raise ValueError("chunk index and bytes are invalid")
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("chunk time range must have both bounds")
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and (
                type(self.start_ms) is not int
                or type(self.end_ms) is not int
                or self.start_ms < 0
                or self.end_ms <= self.start_ms
            )
        ):
            raise ValueError("chunk time range must be a positive half-open range")
        if self.frame_identity is not None and (
            type(self.frame_identity) is not str
            or _SHA256_PATTERN.fullmatch(self.frame_identity) is None
        ):
            raise ValueError("frame_identity must be a lowercase SHA-256 digest")
        if (self.width is None) != (self.height is None):
            raise ValueError("chunk dimensions must be paired")
        for value, name in ((self.width, "width"), (self.height, "height")):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{name} must be positive")
        if self.bbox_context is not None and type(self.bbox_context) is not MediaBoundingBox:
            raise TypeError("bbox_context must be a MediaBoundingBox")
        prefix_count = _strict_int(self.prefix_byte_count, "prefix_byte_count")
        if prefix_count < 0:
            raise ValueError("prefix_byte_count must be non-negative")
        if self.prefix_sha256 and _SHA256_PATTERN.fullmatch(self.prefix_sha256) is None:
            raise ValueError("prefix_sha256 must be a SHA-256 digest")
        digest = hashlib.sha256(self.data).hexdigest()
        identity = _fingerprint(
            {
                "digest": digest,
                "endMs": self.end_ms,
                "frameIdentity": self.frame_identity,
                "height": self.height,
                "index": index,
                "startMs": self.start_ms,
                "width": self.width,
            }
        )
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "chunk_identity", identity)
        object.__setattr__(self, "prefix_byte_count", prefix_count)

    @property
    def bytes(self) -> bytes:
        return self.data


@dataclass(frozen=True, slots=True)
class MediaStreamMetadata:
    byte_size: int
    chunk_count: int
    duration_ms: int | None
    layout_fingerprint: str
    content_sha256: str = ""
    prefix_byte_counts: tuple[int, ...] = ()
    prefix_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, name in ((self.byte_size, "byte_size"), (self.chunk_count, "chunk_count")):
            parsed = _strict_int(value, name)
            if parsed <= 0:
                raise ValueError(f"{name} must be positive")
        if self.duration_ms is not None:
            duration = _strict_int(self.duration_ms, "duration_ms")
            if duration <= 0:
                raise ValueError("duration_ms must be positive")
        if _SHA256_PATTERN.fullmatch(self.layout_fingerprint) is None:
            raise ValueError("layout_fingerprint must be a SHA-256 digest")
        if self.content_sha256 and _SHA256_PATTERN.fullmatch(self.content_sha256) is None:
            raise ValueError("content_sha256 must be a SHA-256 digest")
        if (
            len(self.prefix_byte_counts) != self.chunk_count
            or len(self.prefix_sha256s) != self.chunk_count
        ):
            raise ValueError("prefix metadata must match chunk_count")
        for count, digest in zip(self.prefix_byte_counts, self.prefix_sha256s, strict=True):
            if _strict_int(count, "prefix_byte_count") <= 0:
                raise ValueError("prefix byte counts must be positive")
            if _SHA256_PATTERN.fullmatch(digest) is None:
                raise ValueError("prefix sha256 values must be SHA-256 digests")


@dataclass(frozen=True, slots=True)
class MediaStoreClaim:
    status: MediaClaimStatus
    owner_id: str
    evidence: MediaTextEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not MediaClaimStatus:
            raise TypeError("status must be a MediaClaimStatus")
        _non_empty(self.owner_id, "owner_id")
        if self.evidence is not None and type(self.evidence) is not MediaTextEvidence:
            raise TypeError("evidence must be MediaTextEvidence or None")


def _strict_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _non_empty(value: object, name: str, maximum: int = 256) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds maximum length {maximum}")
    return value


def _aware_utc(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MediaBoundingBox:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        x = _strict_int(self.x, "x")
        y = _strict_int(self.y, "y")
        width = _strict_int(self.width, "width")
        height = _strict_int(self.height, "height")
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("bbox coordinates must be non-negative and dimensions positive")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)

    def payload(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass(frozen=True, slots=True)
class MediaManifest:
    content_id: str
    content_version: str
    media_id: str
    media_version: str
    revision_id: str
    previous_revision_id: str | None
    raw_sha256: str
    mime_type: str
    byte_size: int
    media_kind: MediaKind
    source: str
    source_version: str
    license_id: str
    usage_restriction: str
    authorized: bool
    input_available_time: datetime
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    deleted: bool = False
    deleted_at: datetime | None = None
    deletion_reason: str | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.content_id, "content_id"),
            (self.content_version, "content_version"),
            (self.media_id, "media_id"),
            (self.media_version, "media_version"),
            (self.revision_id, "revision_id"),
            (self.source, "source"),
            (self.source_version, "source_version"),
            (self.license_id, "license_id"),
            (self.usage_restriction, "usage_restriction"),
        ):
            _non_empty(value, name, 1000 if name == "usage_restriction" else 256)
        if self.previous_revision_id is not None:
            _non_empty(self.previous_revision_id, "previous_revision_id")
        if self.previous_revision_id == self.revision_id:
            raise ValueError("previous_revision_id must differ from revision_id")
        if type(self.raw_sha256) is not str or _SHA256_PATTERN.fullmatch(self.raw_sha256) is None:
            raise ValueError("raw_sha256 must be 64 lowercase hexadecimal characters")
        if type(self.mime_type) is not str or "/" not in self.mime_type:
            raise ValueError("mime_type must be a MIME type")
        if type(self.media_kind) is not MediaKind:
            raise TypeError("media_kind must be a MediaKind")
        expected_prefix = {
            MediaKind.AUDIO: "audio/",
            MediaKind.VIDEO: "video/",
            MediaKind.IMAGE: "image/",
        }[self.media_kind]
        if not self.mime_type.startswith(expected_prefix):
            raise ValueError("mime_type does not match media_kind")
        byte_size = _strict_int(self.byte_size, "byte_size")
        if byte_size <= 0 or byte_size > 1_000_000_000:
            raise ValueError("byte_size is outside the supported range")
        if type(self.authorized) is not bool:
            raise TypeError("authorized must be a boolean")
        available = _aware_utc(self.input_available_time, "input_available_time")
        for value, name in (
            (self.width, "width"),
            (self.height, "height"),
            (self.duration_ms, "duration_ms"),
        ):
            if value is not None:
                parsed = _strict_int(value, name)
                if parsed <= 0:
                    raise ValueError(f"{name} must be positive")
        if (self.width is None) != (self.height is None):
            raise ValueError("width and height must be provided together")
        if self.media_kind is MediaKind.IMAGE and (self.width is None or self.height is None):
            raise ValueError("image manifests require width and height")
        if self.media_kind in (MediaKind.AUDIO, MediaKind.VIDEO) and self.duration_ms is None:
            raise ValueError("audio and video manifests require duration_ms")
        if type(self.deleted) is not bool:
            raise TypeError("deleted must be a boolean")
        deleted_at = None if self.deleted_at is None else _aware_utc(self.deleted_at, "deleted_at")
        if self.deleted:
            _non_empty(self.deletion_reason, "deletion_reason", 1000)
            if deleted_at is None:
                raise ValueError("deleted manifests require deleted_at")
            if deleted_at < available:
                raise ValueError("deleted_at must be >= input_available_time")
        elif deleted_at is not None or self.deletion_reason is not None:
            raise ValueError("non-deleted manifests must not have deletion metadata")
        object.__setattr__(self, "input_available_time", available)
        if deleted_at is not None:
            object.__setattr__(self, "deleted_at", deleted_at)

    def is_usable(self, decision_time: datetime) -> bool:
        moment = _aware_utc(decision_time, "decision_time")
        return self.authorized and not self.deleted and self.input_available_time <= moment

    @property
    def identity(self) -> str:
        return _fingerprint(self.payload())

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "authorized": self.authorized,
            "byteSize": self.byte_size,
            "contentId": self.content_id,
            "contentVersion": self.content_version,
            "deleted": self.deleted,
            "deletedAt": None if self.deleted_at is None else _timestamp(self.deleted_at),
            "deletionReason": self.deletion_reason,
            "durationMs": self.duration_ms,
            "height": self.height,
            "inputAvailableTime": _timestamp(self.input_available_time),
            "licenseId": self.license_id,
            "mediaId": self.media_id,
            "mediaKind": self.media_kind.value,
            "mediaVersion": self.media_version,
            "mimeType": self.mime_type,
            "previousRevisionId": self.previous_revision_id,
            "rawSha256": self.raw_sha256,
            "revisionId": self.revision_id,
            "source": self.source,
            "sourceVersion": self.source_version,
            "usageRestriction": self.usage_restriction,
            "width": self.width,
        }
        return payload


def strict_int(value: object, name: str) -> int:
    """Publicly typed strict integer boundary for sibling pipeline modules."""
    return _strict_int(value, name)


@dataclass(frozen=True, slots=True)
class MediaTextSegment:
    text: str
    start_offset: int
    end_offset: int
    start_ms: int | None
    end_ms: int | None
    bbox: MediaBoundingBox | None
    confidence_bps: int
    quality_bps: int
    frame_identity: str | None = None

    def __post_init__(self) -> None:
        text = _non_empty(self.text, "text", 200_000)
        start_offset = _strict_int(self.start_offset, "start_offset")
        end_offset = _strict_int(self.end_offset, "end_offset")
        if start_offset < 0 or end_offset <= start_offset:
            raise ValueError("segment offsets must be a non-empty half-open range")
        for value, name in ((self.start_ms, "start_ms"), (self.end_ms, "end_ms")):
            if value is not None:
                _strict_int(value, name)
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("segment timecode must have both start_ms and end_ms")
        if (
            self.start_ms is not None
            and self.end_ms is not None
            and (self.start_ms < 0 or self.end_ms <= self.start_ms)
        ):
            raise ValueError("segment timecode must be a non-empty half-open range")
        for value, name in (
            (self.confidence_bps, "confidence_bps"),
            (self.quality_bps, "quality_bps"),
        ):
            parsed = _strict_int(value, name)
            if not 0 <= parsed <= 10_000:
                raise ValueError(f"{name} must be between 0 and 10000")
        if self.bbox is not None and type(self.bbox) is not MediaBoundingBox:
            raise TypeError("bbox must be a MediaBoundingBox or None")
        if (
            self.frame_identity is not None
            and _SHA256_PATTERN.fullmatch(self.frame_identity) is None
        ):
            raise ValueError("frame_identity must be a lowercase SHA-256 digest")
        object.__setattr__(self, "text", text)

    @property
    def identity(self) -> str:
        return _fingerprint(
            {
                "bbox": None if self.bbox is None else self.bbox.payload(),
                "endMs": self.end_ms,
                "endOffset": self.end_offset,
                "frameIdentity": self.frame_identity,
                "qualityBps": self.quality_bps,
                "startMs": self.start_ms,
                "startOffset": self.start_offset,
                "text": self.text,
            }
        )

    def payload(self) -> dict[str, object]:
        return {
            "bbox": None if self.bbox is None else self.bbox.payload(),
            "confidenceBps": self.confidence_bps,
            "endMs": self.end_ms,
            "endOffset": self.end_offset,
            "frameIdentity": self.frame_identity,
            "qualityBps": self.quality_bps,
            "startMs": self.start_ms,
            "startOffset": self.start_offset,
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class MediaEvidenceProvenance:
    pipeline_version: str
    processor_kind: MediaProcessorKind
    provider: str
    model: str
    model_version: str
    prompt_version: str
    configuration_fingerprint: str
    policy_fingerprint: str
    recognition_run_id: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.pipeline_version, "pipeline_version"),
            (self.provider, "provider"),
            (self.model, "model"),
            (self.model_version, "model_version"),
            (self.prompt_version, "prompt_version"),
            (self.recognition_run_id, "recognition_run_id"),
        ):
            _non_empty(value, name, 256)
        if type(self.processor_kind) is not MediaProcessorKind:
            raise TypeError("processor_kind must be a MediaProcessorKind")
        if not _SHA256_PATTERN.fullmatch(self.configuration_fingerprint):
            raise ValueError("configuration_fingerprint must be a SHA-256 hex digest")
        if not _SHA256_PATTERN.fullmatch(self.policy_fingerprint):
            raise ValueError("policy_fingerprint must be a SHA-256 hex digest")

    def payload(self) -> dict[str, object]:
        return {
            "configurationFingerprint": self.configuration_fingerprint,
            "model": self.model,
            "modelVersion": self.model_version,
            "pipelineVersion": self.pipeline_version,
            "policyFingerprint": self.policy_fingerprint,
            "processorKind": self.processor_kind.value,
            "provider": self.provider,
            "promptVersion": self.prompt_version,
            "recognitionRunId": self.recognition_run_id,
        }


@dataclass(frozen=True, slots=True)
class MediaTextEvidence:
    evidence_id: str
    revision_id: str
    previous_revision_id: str | None
    media_manifest: MediaManifest
    processor_kind: MediaProcessorKind
    text: str
    language: str
    segments: tuple[MediaTextSegment, ...]
    confidence_bps: int
    quality_bps: int
    event_time: datetime | None
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    provenance: MediaEvidenceProvenance
    deleted: bool = False
    deleted_at: datetime | None = None
    deletion_reason: str | None = None
    schema_version: str = field(init=False, default=MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION)
    available_time: datetime = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _non_empty(self.evidence_id, "evidence_id")
        _non_empty(self.revision_id, "revision_id")
        if self.previous_revision_id == self.revision_id:
            raise ValueError("previous_revision_id must differ from revision_id")
        if type(self.media_manifest) is not MediaManifest:
            raise TypeError("media_manifest must be a MediaManifest")
        if type(self.processor_kind) is not MediaProcessorKind:
            raise TypeError("processor_kind must be a MediaProcessorKind")
        if self.provenance.processor_kind is not self.processor_kind:
            raise ValueError("provenance processor kind must match evidence")
        _non_empty(self.text, "text", 2_000_000)
        if _LANGUAGE_PATTERN.fullmatch(self.language) is None:
            raise ValueError("language must be a BCP-47 language tag")
        if type(self.segments) is not tuple:
            raise TypeError("segments must be a tuple")
        if not self.segments:
            raise ValueError("evidence requires at least one segment")
        for value, name in (
            (self.confidence_bps, "confidence_bps"),
            (self.quality_bps, "quality_bps"),
        ):
            parsed = _strict_int(value, name)
            if not 0 <= parsed <= 10_000:
                raise ValueError(f"{name} must be between 0 and 10000")
        event_time = None if self.event_time is None else _aware_utc(self.event_time, "event_time")
        publish = _aware_utc(self.publish_time, "publish_time")
        ingest = _aware_utc(self.ingest_time, "ingest_time")
        processing = _aware_utc(self.processing_time, "processing_time")
        if publish > ingest or ingest > processing:
            raise ValueError("publish_time <= ingest_time <= processing_time is required")
        available = max(self.media_manifest.input_available_time, processing)
        for segment in self.segments:
            if type(segment) is not MediaTextSegment:
                raise TypeError("segments must contain MediaTextSegment values")
            if (
                segment.end_offset > len(self.text)
                or self.text[segment.start_offset : segment.end_offset] != segment.text
            ):
                raise ValueError("segment offsets must address the exact evidence text")
            if self.processor_kind is MediaProcessorKind.ASR:
                if self.media_manifest.media_kind not in (MediaKind.AUDIO, MediaKind.VIDEO):
                    raise ValueError("ASR requires audio or video media")
                if segment.start_ms is None or segment.end_ms is None:
                    raise ValueError("ASR segments require timecodes")
            elif self.media_manifest.media_kind is MediaKind.IMAGE:
                if segment.bbox is None:
                    raise ValueError("image OCR segments require a bbox")
            elif self.media_manifest.media_kind is MediaKind.VIDEO:
                if segment.start_ms is None and segment.bbox is None:
                    raise ValueError("video OCR segments require time or bbox")
            else:
                raise ValueError("OCR requires image or video media")
            if (
                segment.bbox is not None
                and self.media_manifest.width is not None
                and self.media_manifest.height is not None
                and (
                    segment.bbox.x + segment.bbox.width > self.media_manifest.width
                    or segment.bbox.y + segment.bbox.height > self.media_manifest.height
                )
            ):
                raise ValueError("bbox must be inside the media dimensions")
        if type(self.deleted) is not bool:
            raise TypeError("deleted must be a boolean")
        deleted_at = None if self.deleted_at is None else _aware_utc(self.deleted_at, "deleted_at")
        if self.deleted:
            _non_empty(self.deletion_reason, "deletion_reason", 1000)
            if deleted_at is None or deleted_at < available:
                raise ValueError("deleted evidence requires deleted_at >= available_time")
        elif deleted_at is not None or self.deletion_reason is not None:
            raise ValueError("non-deleted evidence must not have deletion metadata")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(self, "available_time", available)
        if deleted_at is not None:
            object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(self, "fingerprint", _fingerprint(self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "availableTime": _timestamp(self.available_time),
            "confidenceBps": self.confidence_bps,
            "deleted": self.deleted,
            "deletedAt": None if self.deleted_at is None else _timestamp(self.deleted_at),
            "deletionReason": self.deletion_reason,
            "eventTime": None if self.event_time is None else _timestamp(self.event_time),
            "evidenceId": self.evidence_id,
            "ingestTime": _timestamp(self.ingest_time),
            "language": self.language,
            "mediaManifest": self.media_manifest.payload(),
            "previousRevisionId": self.previous_revision_id,
            "processingTime": _timestamp(self.processing_time),
            "processorKind": self.processor_kind.value,
            "provenance": self.provenance.payload(),
            "publishTime": _timestamp(self.publish_time),
            "revisionId": self.revision_id,
            "schemaVersion": self.schema_version,
            "segments": [segment.payload() for segment in self.segments],
            "text": self.text,
            "qualityBps": self.quality_bps,
        }


@dataclass(frozen=True, slots=True)
class MediaCheckpoint:
    request_fingerprint: str
    raw_sha256: str
    next_chunk_index: int
    text: str
    segments: tuple[MediaTextSegment, ...]
    frame_identities: tuple[str, ...]
    language: str = "und"
    phase: MediaCheckpointPhase = MediaCheckpointPhase.RECOGNIZING
    chunk_count: int = 0
    manifest_identity: str = ""
    manifest_revision_id: str = ""
    policy_fingerprint: str = ""
    configuration_fingerprint: str = ""
    chunk_layout_fingerprint: str = ""
    rolling_byte_count: int = 0
    rolling_sha256: str = ""
    completed_chunk_indices: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.request_fingerprint) or not _SHA256_PATTERN.fullmatch(
            self.raw_sha256
        ):
            raise ValueError("checkpoint fingerprints must be SHA-256 hex digests")
        next_index = _strict_int(self.next_chunk_index, "next_chunk_index")
        if next_index < 0:
            raise ValueError("next_chunk_index must be non-negative")
        if type(self.text) is not str or len(self.text) > 2_000_000:
            raise ValueError("checkpoint text exceeds maximum length")
        if type(self.segments) is not tuple or type(self.frame_identities) is not tuple:
            raise TypeError("checkpoint collections must be tuples")
        for value, name in (
            (self.manifest_identity, "manifest_identity"),
            (self.policy_fingerprint, "policy_fingerprint"),
            (self.configuration_fingerprint, "configuration_fingerprint"),
            (self.chunk_layout_fingerprint, "chunk_layout_fingerprint"),
        ):
            if value and _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if self.manifest_revision_id:
            _non_empty(self.manifest_revision_id, "manifest_revision_id")
        rolling_count = _strict_int(self.rolling_byte_count, "rolling_byte_count")
        if rolling_count < 0:
            raise ValueError("rolling_byte_count must be non-negative")
        if self.rolling_sha256 and _SHA256_PATTERN.fullmatch(self.rolling_sha256) is None:
            raise ValueError("rolling_sha256 must be a SHA-256 hex digest")
        if type(self.completed_chunk_indices) is not tuple:
            raise TypeError("completed_chunk_indices must be a tuple")
        if type(self.phase) is not MediaCheckpointPhase:
            raise TypeError("phase must be a MediaCheckpointPhase")
        chunk_count = _strict_int(self.chunk_count, "chunk_count")
        if chunk_count < 0 or next_index > chunk_count:
            raise ValueError("checkpoint chunk index is outside chunk count")
        for completed in self.completed_chunk_indices:
            if _strict_int(completed, "completed_chunk_indices item") < 0:
                raise ValueError("completed chunk indices must be non-negative")
        object.__setattr__(self, "rolling_byte_count", rolling_count)
        object.__setattr__(self, "chunk_count", chunk_count)
        if self.phase is MediaCheckpointPhase.READY_TO_COMMIT:
            if chunk_count <= 0 or next_index != chunk_count:
                raise ValueError("READY_TO_COMMIT checkpoint must be complete")
            if not self.rolling_sha256 or not self.chunk_layout_fingerprint:
                raise ValueError("READY_TO_COMMIT checkpoint must be fully verified")

    @property
    def next_failed_chunk_index(self) -> int:
        return self.next_chunk_index


@dataclass(frozen=True, slots=True)
class MediaPipelinePolicy:
    pipeline_version: str = MEDIA_PIPELINE_VERSION
    chunk_size_bytes: int = 10_000_000
    max_attempts: int = 3
    max_media_bytes: int = 100_000_000
    max_duration_ms: int = 86_400_000
    retry_base_seconds: int = 1
    max_bytes: int | None = None
    max_chunks: int = 100_000
    max_segments: int = 100_000
    max_text_codepoints: int = 2_000_000
    max_frames: int = 100_000
    max_chunk_bytes: int = 10_000_000
    minimum_quality_bps: int = 5_000
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _non_empty(self.pipeline_version, "pipeline_version", 128)
        for value, name in (
            (self.chunk_size_bytes, "chunk_size_bytes"),
            (self.max_attempts, "max_attempts"),
            (self.max_media_bytes, "max_media_bytes"),
            (self.max_duration_ms, "max_duration_ms"),
            (self.retry_base_seconds, "retry_base_seconds"),
            (self.max_chunks, "max_chunks"),
            (self.max_segments, "max_segments"),
            (self.max_text_codepoints, "max_text_codepoints"),
            (self.max_frames, "max_frames"),
            (self.max_chunk_bytes, "max_chunk_bytes"),
            (self.minimum_quality_bps, "minimum_quality_bps"),
        ):
            parsed = _strict_int(value, name)
            if parsed <= 0:
                raise ValueError(f"{name} must be positive")
        effective_max_bytes = (
            self.max_media_bytes
            if self.max_bytes is None
            else _strict_int(self.max_bytes, "max_bytes")
        )
        if effective_max_bytes <= 0 or effective_max_bytes > 100_000_000:
            raise ValueError("max_bytes must be positive and no greater than 100000000")
        if self.chunk_size_bytes > self.max_chunk_bytes:
            raise ValueError("chunk_size_bytes must not exceed max_chunk_bytes")
        if self.minimum_quality_bps > 10_000:
            raise ValueError("minimum_quality_bps must be at most 10000")
        object.__setattr__(self, "max_bytes", effective_max_bytes)
        object.__setattr__(self, "max_media_bytes", effective_max_bytes)
        object.__setattr__(self, "fingerprint", _fingerprint(self.payload()))

    def payload(self) -> dict[str, object]:
        return {
            "chunkSizeBytes": self.chunk_size_bytes,
            "maxAttempts": self.max_attempts,
            "maxBytes": self.max_bytes,
            "maxChunks": self.max_chunks,
            "maxChunkBytes": self.max_chunk_bytes,
            "maxFrames": self.max_frames,
            "maxSegments": self.max_segments,
            "maxTextCodepoints": self.max_text_codepoints,
            "maxDurationMs": self.max_duration_ms,
            "maxMediaBytes": self.max_media_bytes,
            "minimumQualityBps": self.minimum_quality_bps,
            "pipelineVersion": self.pipeline_version,
            "retryBaseSeconds": self.retry_base_seconds,
        }

    @property
    def effective_max_bytes(self) -> int:
        return self.max_media_bytes if self.max_bytes is None else self.max_bytes


@dataclass(frozen=True, slots=True)
class MediaProcessingRequest:
    request_id: str
    manifest: MediaManifest
    processor_kind: MediaProcessorKind
    resolved_profile: ResolvedProfile
    decision_time: datetime
    event_time: datetime | None
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    attempt: int = 0
    checkpoint: MediaCheckpoint | None = None
    request_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _non_empty(self.request_id, "request_id")
        from intelligence_engine.llm.models import ResolvedProfile

        if type(self.manifest) is not MediaManifest:
            raise TypeError("manifest must be a MediaManifest")
        if type(self.processor_kind) is not MediaProcessorKind:
            raise TypeError("processor_kind must be a MediaProcessorKind")
        if type(self.resolved_profile) is not ResolvedProfile:
            raise TypeError("resolved_profile must be a ResolvedProfile")
        decision = _aware_utc(self.decision_time, "decision_time")
        event = None if self.event_time is None else _aware_utc(self.event_time, "event_time")
        publish = _aware_utc(self.publish_time, "publish_time")
        ingest = _aware_utc(self.ingest_time, "ingest_time")
        processing = _aware_utc(self.processing_time, "processing_time")
        if publish > ingest or ingest > processing:
            raise ValueError("publish_time <= ingest_time <= processing_time is required")
        if _aware_utc(self.resolved_profile.decision_time, "profile decision_time") != decision:
            raise ValueError("resolved profile decision_time must match request decision_time")
        attempt = _strict_int(self.attempt, "attempt")
        if attempt < 0:
            raise ValueError("attempt must be non-negative")
        if self.checkpoint is not None and type(self.checkpoint) is not MediaCheckpoint:
            raise TypeError("checkpoint must be a MediaCheckpoint")
        object.__setattr__(self, "decision_time", decision)
        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(
            self,
            "request_fingerprint",
            _fingerprint(
                {
                    "decisionTime": _timestamp(decision),
                    "eventTime": None if event is None else _timestamp(event),
                    "ingestTime": _timestamp(ingest),
                    "manifest": self.manifest.payload(),
                    "processorKind": self.processor_kind.value,
                    "profileFingerprint": self.resolved_profile.configuration_fingerprint,
                    "processingTime": _timestamp(processing),
                    "publishTime": _timestamp(publish),
                    "requestId": self.request_id,
                }
            ),
        )

    def idempotency_fingerprint(self, policy: MediaPipelinePolicy) -> str:
        return _fingerprint(
            {
                "configurationFingerprint": self.resolved_profile.configuration_fingerprint,
                "policyFingerprint": policy.fingerprint,
                "requestFingerprint": self.request_fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class MediaProcessResult:
    status: MediaProcessStatus
    evidence: MediaTextEvidence | None = None
    failure_reason: MediaFailureReason | None = None
    checkpoint: MediaCheckpoint | None = None
    audit_id: str | None = None
    retry_after_seconds: int | None = None


__all__ = [
    "MEDIA_PIPELINE_VERSION",
    "MEDIA_TEXT_EVIDENCE_SCHEMA_VERSION",
    "MediaAuditReason",
    "MediaAuditRecord",
    "MediaAuditStatus",
    "MediaBoundingBox",
    "MediaClaimStatus",
    "MediaCheckpoint",
    "MediaCheckpointPhase",
    "MediaChecksumMismatchError",
    "MediaChunk",
    "MediaDecodeError",
    "MediaEvidenceProvenance",
    "MediaFailureReason",
    "MediaKind",
    "MediaManifest",
    "MediaPipelineError",
    "MediaPipelinePolicy",
    "MediaProcessResult",
    "MediaProcessStatus",
    "MediaProcessorKind",
    "MediaRateLimitError",
    "MediaSilenceError",
    "MediaStoreTransientError",
    "MediaTemporaryUnavailableError",
    "MediaTextEvidence",
    "MediaTextSegment",
    "MediaStreamMetadata",
    "MediaStoreClaim",
    "MediaTimeoutError",
    "MediaTooLongError",
    "MediaProcessingRequest",
]
