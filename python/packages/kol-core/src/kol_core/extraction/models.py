"""Immutable claim-extraction candidate and review domain objects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Final

from market_core import parse_instrument_code

CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION: Final = "claim-extraction-candidate-v1"
CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION: Final = "claim-review-submission-v1"
CLAIM_REVIEW_SCHEMA_VERSION: Final = "claim-review-v1"
CLAIM_EXTRACTION_ALGORITHM_VERSION: Final = "kol-claim-extraction-v1"
KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION: Final = "kol-claim-candidate-id-v1"
KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION: Final = "kol-claim-revision-id-v1"
PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION: Final = (
    "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION"
)
PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION: Final = (
    "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION"
)
EVIDENCE_GRADE_VERSION: Final = "evidence-grade-v1"


class ClaimAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLDING = "HOLDING"
    WATCH = "WATCH"


class ClaimPolarity(StrEnum):
    AFFIRMED = "AFFIRMED"
    NEGATED = "NEGATED"


class ClaimConditionality(StrEnum):
    UNCONDITIONAL = "UNCONDITIONAL"
    CONDITIONAL = "CONDITIONAL"


class ClaimStatementKind(StrEnum):
    DIRECT = "DIRECT"
    QUOTE = "QUOTE"
    PARAPHRASE = "PARAPHRASE"
    AMBIGUOUS = "AMBIGUOUS"


class ClaimAttribution(StrEnum):
    SELF = "SELF"
    QUOTED = "QUOTED"
    REPORTED = "REPORTED"
    UNKNOWN = "UNKNOWN"


class EventTimeStatus(StrEnum):
    EXACT = "EXACT"
    DATE_ONLY = "DATE_ONLY"
    UNKNOWN = "UNKNOWN"


class ClaimReviewDecision(StrEnum):
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EvidenceGrade(StrEnum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    TERTIARY_SOURCE = "TERTIARY_SOURCE"
    UNCLASSIFIED = "UNCLASSIFIED"


def _text(value: object, name: str, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value


def _id(value: object, name: str) -> str:
    text = _text(value, name)
    if any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:/-"
        for char in text
    ):
        raise ValueError(f"{name} contains an unsafe character")
    return text


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _date(value: object, name: str) -> date:
    if type(value) is not date or type(value) is datetime:
        raise ValueError(f"{name} must be a calendar date")
    return value


def _strict_int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a strict bounded integer")
    return value


def _revision(revision_id: object, previous_revision_id: object) -> tuple[str, str | None]:
    revision = _id(revision_id, "revision_id")
    previous = (
        None if previous_revision_id is None else _id(previous_revision_id, "previous_revision_id")
    )
    if previous == revision:
        raise ValueError("previous_revision_id must differ from revision_id")
    return revision, previous


def _instrument(value: object) -> str:
    text = _text(value, "instrument_id", 9)
    if len(text) != 9 or text[6] != ".":
        raise ValueError("instrument_id must use canonical unified code")
    parsed = parse_instrument_code(text[:6])
    if parsed is None or parsed.unified_code != text:
        raise ValueError("instrument_id does not match the shared instrument parser")
    return text


def _enum(value: object, enum_type: type[StrEnum], name: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {name}") from error


def _time_chain(
    publish_time: object,
    ingest_time: object,
    processing_time: object,
    available_time: object,
) -> tuple[datetime, datetime, datetime, datetime]:
    publish = _aware(publish_time, "publish_time")
    ingest = _aware(ingest_time, "ingest_time")
    processing = _aware(processing_time, "processing_time")
    available = _aware(available_time, "available_time")
    if publish > ingest or ingest > processing or processing > available:
        raise ValueError(
            "publish_time <= ingest_time <= processing_time <= available_time is required"
        )
    return publish, ingest, processing, available


def _deletion(
    deleted: object,
    deleted_at: object,
    deletion_reason: object,
    available_time: datetime,
) -> tuple[bool, datetime | None, str | None]:
    if type(deleted) is not bool:
        raise TypeError("deleted must be a strict bool")
    if deleted:
        when = _aware(deleted_at, "deleted_at")
        if when < available_time:
            raise ValueError("deleted_at must be >= available_time")
        return True, when, _text(deletion_reason, "deletion_reason", 1000)
    if deleted_at is not None or deletion_reason is not None:
        raise ValueError("non-deleted candidate cannot carry deletion metadata")
    return False, None, None


@dataclass(frozen=True, slots=True)
class ContentExactAnchor:
    source_index: int
    content_id: str
    content_version: str
    content_revision_id: str
    content_available_time: datetime
    source: str
    source_version: str
    start_offset: int
    end_offset: int
    excerpt: str
    evidence_grade: EvidenceGrade
    evidence_grade_version: str = EVIDENCE_GRADE_VERSION
    anchor_type: str = field(init=False, default="CONTENT")

    def __post_init__(self) -> None:
        _strict_int(self.source_index, "source_index", 0, 100_000)
        _id(self.content_id, "content_id")
        _id(self.content_version, "content_version")
        _id(self.content_revision_id, "content_revision_id")
        object.__setattr__(
            self,
            "content_available_time",
            _aware(self.content_available_time, "content_available_time"),
        )
        _text(self.source, "source")
        _text(self.source_version, "source_version")
        start = _strict_int(self.start_offset, "start_offset", 0, 10_000_000)
        end = _strict_int(self.end_offset, "end_offset", 1, 10_000_000)
        if end <= start:
            raise ValueError("end_offset must exceed start_offset")
        _text(self.excerpt, "excerpt", 10_000)
        object.__setattr__(
            self, "evidence_grade", _enum(self.evidence_grade, EvidenceGrade, "evidence_grade")
        )
        if self.evidence_grade_version != EVIDENCE_GRADE_VERSION:
            raise ValueError("unsupported evidence_grade_version")


@dataclass(frozen=True, slots=True)
class MediaExactAnchor(ContentExactAnchor):
    evidence_id: str = ""
    evidence_revision_id: str = ""
    evidence_available_time: datetime = datetime.min.replace(tzinfo=UTC)
    media_id: str = ""
    media_version: str = ""
    media_manifest_revision_id: str = ""
    segment_indexes: tuple[int, ...] = ()
    anchor_type: str = field(init=False, default="MEDIA")

    def __post_init__(self) -> None:
        ContentExactAnchor.__post_init__(self)
        _id(self.evidence_id, "evidence_id")
        _id(self.evidence_revision_id, "evidence_revision_id")
        evidence_available = _aware(self.evidence_available_time, "evidence_available_time")
        if self.content_available_time > evidence_available:
            raise ValueError("content availability exceeds evidence availability")
        object.__setattr__(self, "evidence_available_time", evidence_available)
        _id(self.media_id, "media_id")
        _id(self.media_version, "media_version")
        _id(self.media_manifest_revision_id, "media_manifest_revision_id")
        if type(self.segment_indexes) is not tuple or not self.segment_indexes:
            raise ValueError("segment_indexes must be a non-empty tuple")
        values = tuple(
            _strict_int(item, "segment_index", 0, 100_000) for item in self.segment_indexes
        )
        if len(set(values)) != len(values):
            raise ValueError("segment_indexes must be unique")
        object.__setattr__(self, "segment_indexes", values)


ClaimAnchor = ContentExactAnchor | MediaExactAnchor


@dataclass(frozen=True, slots=True)
class ClaimExtractionCandidate:
    candidate_id: str
    revision_id: str
    previous_revision_id: str | None
    statement: str
    action: ClaimAction
    polarity: ClaimPolarity
    conditionality: ClaimConditionality
    statement_kind: ClaimStatementKind
    attribution: ClaimAttribution
    event_time_status: EventTimeStatus
    event_time: datetime | None
    event_date: date | None
    instrument_id: str
    anchors: tuple[ClaimAnchor, ...]
    evidence_grade: EvidenceGrade
    confidence_bps: int
    source: str
    source_version: str
    prompt_version: str
    model_provider: str
    model_version: str
    configuration_fingerprint: str
    policy_fingerprint: str
    recognition_run_id: str
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    available_time: datetime
    deleted: bool = False
    deleted_at: datetime | None = None
    deletion_reason: str | None = None
    schema_version: str = CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION
    semantic_label: str = PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION
    evidence_grade_version: str = EVIDENCE_GRADE_VERSION
    algorithm_version: str = CLAIM_EXTRACTION_ALGORITHM_VERSION
    review_status: str = "UNREVIEWED"

    def __post_init__(self) -> None:
        _id(self.candidate_id, "candidate_id")
        revision, previous = _revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _text(self.statement, "statement", 10_000)
        object.__setattr__(self, "action", _enum(self.action, ClaimAction, "action"))
        object.__setattr__(self, "polarity", _enum(self.polarity, ClaimPolarity, "polarity"))
        object.__setattr__(
            self,
            "conditionality",
            _enum(self.conditionality, ClaimConditionality, "conditionality"),
        )
        object.__setattr__(
            self, "statement_kind", _enum(self.statement_kind, ClaimStatementKind, "statement_kind")
        )
        object.__setattr__(
            self, "attribution", _enum(self.attribution, ClaimAttribution, "attribution")
        )
        if self.statement_kind is ClaimStatementKind.QUOTE and self.attribution not in {
            ClaimAttribution.QUOTED,
            ClaimAttribution.REPORTED,
        }:
            raise ValueError("QUOTE requires quoted or reported attribution")
        if (
            self.statement_kind is ClaimStatementKind.PARAPHRASE
            and self.attribution is ClaimAttribution.UNKNOWN
        ):
            raise ValueError("PARAPHRASE requires known attribution")
        if (
            self.statement_kind is ClaimStatementKind.AMBIGUOUS
            and self.attribution is ClaimAttribution.SELF
        ):
            raise ValueError("AMBIGUOUS cannot be self attributed")
        object.__setattr__(
            self,
            "event_time_status",
            _enum(self.event_time_status, EventTimeStatus, "event_time_status"),
        )
        if self.event_time_status is EventTimeStatus.EXACT:
            if self.event_time is None or self.event_date is not None:
                raise ValueError("EXACT requires aware event_time and no event_date")
            object.__setattr__(self, "event_time", _aware(self.event_time, "event_time"))
        elif self.event_time_status is EventTimeStatus.DATE_ONLY:
            if self.event_time is not None or self.event_date is None:
                raise ValueError("DATE_ONLY requires event_date and no event_time")
            object.__setattr__(self, "event_date", _date(self.event_date, "event_date"))
        elif self.event_time is not None or self.event_date is not None:
            raise ValueError("UNKNOWN cannot invent event time")
        object.__setattr__(self, "instrument_id", _instrument(self.instrument_id))
        if type(self.anchors) is not tuple or not self.anchors:
            raise ValueError("anchors must be a non-empty tuple")
        if any(
            type(anchor) not in (ContentExactAnchor, MediaExactAnchor) for anchor in self.anchors
        ):
            raise TypeError("anchors must be typed exact anchors")
        object.__setattr__(
            self, "evidence_grade", _enum(self.evidence_grade, EvidenceGrade, "evidence_grade")
        )
        if self.evidence_grade_version != EVIDENCE_GRADE_VERSION:
            raise ValueError("unsupported evidence_grade_version")
        _strict_int(self.confidence_bps, "confidence_bps", 0, 10_000)
        _text(self.source, "source")
        _text(self.source_version, "source_version")
        _text(self.prompt_version, "prompt_version")
        _text(self.model_provider, "model_provider")
        _text(self.model_version, "model_version")
        _id(self.recognition_run_id, "recognition_run_id")
        for value, name in (
            (self.configuration_fingerprint, "configuration_fingerprint"),
            (self.policy_fingerprint, "policy_fingerprint"),
        ):
            text = _text(value, name, 64)
            if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
                raise ValueError(f"{name} must be lowercase SHA-256")
        publish, ingest, processing, available = _time_chain(
            self.publish_time, self.ingest_time, self.processing_time, self.available_time
        )
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(self, "available_time", available)
        for anchor in self.anchors:
            if anchor.content_available_time > available:
                raise ValueError("candidate available_time precedes content evidence")
            if isinstance(anchor, MediaExactAnchor) and anchor.evidence_available_time > available:
                raise ValueError("candidate available_time precedes media evidence")
        if (
            self.schema_version != CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION
            or self.semantic_label != PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION
            or self.algorithm_version != CLAIM_EXTRACTION_ALGORITHM_VERSION
            or self.review_status != "UNREVIEWED"
        ):
            raise ValueError("unsupported candidate contract version or status")
        deleted, deleted_at, reason = _deletion(
            self.deleted, self.deleted_at, self.deletion_reason, available
        )
        object.__setattr__(self, "deleted", deleted)
        object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(self, "deletion_reason", reason)

    def visible_at(self, decision_time: datetime) -> bool:
        return not self.deleted and self.effective_time <= _aware(decision_time, "decision_time")

    @property
    def effective_time(self) -> datetime:
        if not self.deleted:
            return self.available_time
        if self.deleted_at is None:
            raise ValueError("deleted candidate must have deleted_at")
        return self.deleted_at


@dataclass(frozen=True, slots=True)
class ClaimReviewSubmission:
    client_request_id: str
    candidate_id: str
    candidate_revision_id: str
    decision: ClaimReviewDecision
    reason: str
    comment: str | None = None
    expected_previous_review_id: str | None = None
    schema_version: str = CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _id(self.client_request_id, "client_request_id")
        _id(self.candidate_id, "candidate_id")
        _id(self.candidate_revision_id, "candidate_revision_id")
        object.__setattr__(self, "decision", _enum(self.decision, ClaimReviewDecision, "decision"))
        _text(self.reason, "reason", 1000)
        if self.comment is not None:
            _text(self.comment, "comment", 4000)
        if self.expected_previous_review_id is not None:
            _id(self.expected_previous_review_id, "expected_previous_review_id")
        if self.schema_version != CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported review submission schema")


@dataclass(frozen=True, slots=True)
class ClaimReview:
    review_id: str
    candidate_id: str
    candidate_revision_id: str
    decision: ClaimReviewDecision
    reason: str
    comment: str | None
    reviewer_ref: str
    created_at: datetime
    available_at: datetime
    submission_fingerprint: str
    previous_review_id: str | None
    schema_version: str = CLAIM_REVIEW_SCHEMA_VERSION
    review_meaning: str = PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION

    def __post_init__(self) -> None:
        _id(self.review_id, "review_id")
        _id(self.candidate_id, "candidate_id")
        _id(self.candidate_revision_id, "candidate_revision_id")
        object.__setattr__(self, "decision", _enum(self.decision, ClaimReviewDecision, "decision"))
        _text(self.reason, "reason", 1000)
        if self.comment is not None:
            _text(self.comment, "comment", 4000)
        _id(self.reviewer_ref, "reviewer_ref")
        created = _aware(self.created_at, "created_at")
        available = _aware(self.available_at, "available_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "available_at", available)
        if created > available:
            raise ValueError("created_at must be <= available_at")
        fingerprint = _text(self.submission_fingerprint, "submission_fingerprint", 64)
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("submission_fingerprint must be lowercase SHA-256")
        if self.previous_review_id is not None:
            _id(self.previous_review_id, "previous_review_id")
        if (
            self.schema_version != CLAIM_REVIEW_SCHEMA_VERSION
            or self.review_meaning != PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION
        ):
            raise ValueError("unsupported review contract")


def deterministic_fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CLAIM_EXTRACTION_ALGORITHM_VERSION",
    "KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION",
    "KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION",
    "CLAIM_EXTRACTION_CANDIDATE_SCHEMA_VERSION",
    "CLAIM_REVIEW_SCHEMA_VERSION",
    "CLAIM_REVIEW_SUBMISSION_SCHEMA_VERSION",
    "EVIDENCE_GRADE_VERSION",
    "PUBLIC_SPEECH_CANDIDATE_NOT_FACT_OR_EXECUTION",
    "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION",
    "ClaimAction",
    "ClaimAnchor",
    "ClaimAttribution",
    "ClaimConditionality",
    "ClaimExtractionCandidate",
    "ClaimPolarity",
    "ClaimReview",
    "ClaimReviewDecision",
    "ClaimReviewSubmission",
    "ClaimStatementKind",
    "ContentExactAnchor",
    "EventTimeStatus",
    "EvidenceGrade",
    "MediaExactAnchor",
    "deterministic_fingerprint",
]
