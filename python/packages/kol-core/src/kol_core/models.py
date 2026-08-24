"""Immutable, auditable KOL content and claim domain models.

Generated Pydantic DTOs are transport shapes only. Untrusted payloads must
enter through the ``parse_*_payload`` functions so the domain invariants below
are applied. A Claim or PositionClaim is descriptive public speech and is never
converted into a Trade, order, fill, account, or executable position.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import overload

from ashare_contracts.kol_claim import (
    KolClaim as KolClaimDTO,
)
from ashare_contracts.kol_claim import (
    KolClaimEvidenceReference as KolClaimEvidenceReferenceDTO,
)
from ashare_contracts.kol_content import KolContent as KolContentDTO
from ashare_contracts.kol_evidence import KolEvidence as KolEvidenceDTO
from ashare_contracts.kol_mention import KolMention as KolMentionDTO
from ashare_contracts.kol_position_claim import (
    KolPositionClaim as KolPositionClaimDTO,
)
from market_core import parse_instrument_code

KOL_ALGORITHM_VERSION = "kol-domain-v1"
KOL_CONTENT_SCHEMA_VERSION = "kol-content-v1"
KOL_MENTION_SCHEMA_VERSION = "kol-mention-v1"
KOL_EVIDENCE_SCHEMA_VERSION = "kol-evidence-v1"
KOL_CLAIM_SCHEMA_VERSION = "kol-claim-v1"
KOL_POSITION_CLAIM_SCHEMA_VERSION = "kol-position-claim-v1"
KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION = "sha256-kol-content-v1"
KOL_EVIDENCE_GRADE_VERSION = "evidence-grade-v1"
APPROVED_REVIEW_SEMANTICS = "PUBLIC_WORDING_REVIEWED_NOT_FACT_OR_EXECUTION"
NON_EXECUTABLE_POSITION_CLAIM = "NON_EXECUTABLE_POSITION_CLAIM"


class ContentType(StrEnum):
    POST = "POST"
    ARTICLE = "ARTICLE"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    COMMENT = "COMMENT"
    OTHER = "OTHER"


class MentionType(StrEnum):
    INSTRUMENT = "INSTRUMENT"
    PERSON = "PERSON"
    ORGANIZATION = "ORGANIZATION"
    TOPIC = "TOPIC"
    OTHER = "OTHER"


class LocatorType(StrEnum):
    URL = "URL"
    TEXT_RANGE = "TEXT_RANGE"
    TIME_RANGE = "TIME_RANGE"
    PAGE = "PAGE"


class EvidenceGrade(StrEnum):
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    SECONDARY_SOURCE = "SECONDARY_SOURCE"
    TERTIARY_SOURCE = "TERTIARY_SOURCE"
    UNCLASSIFIED = "UNCLASSIFIED"


class ClaimStatementKind(StrEnum):
    DIRECT = "DIRECT"
    QUOTE = "QUOTE"
    PARAPHRASE = "PARAPHRASE"
    AMBIGUOUS = "AMBIGUOUS"


class ClaimDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class ClaimAttribution(StrEnum):
    SELF = "SELF"
    QUOTED = "QUOTED"
    REPORTED = "REPORTED"
    UNKNOWN = "UNKNOWN"


class ClaimUncertainty(StrEnum):
    NONE = "NONE"
    AMBIGUOUS = "AMBIGUOUS"
    CONDITIONAL = "CONDITIONAL"
    UNVERIFIED = "UNVERIFIED"


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PositionDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class PositionTimeHorizon(StrEnum):
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    LONG_TERM = "LONG_TERM"
    UNSPECIFIED = "UNSPECIFIED"


class ExecutionSemantics(StrEnum):
    NON_EXECUTABLE_POSITION_CLAIM = NON_EXECUTABLE_POSITION_CLAIM


def _require_non_empty(value: object, name: str, max_length: int = 256) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds maximum length {max_length}")
    return value


def _require_aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _require_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _require_int(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _require_wire_bool(payload: Mapping[str, object], field: str) -> None:
    if type(payload.get(field)) is not bool:
        raise TypeError(f"{field} must be a bool")


def _require_wire_int(payload: Mapping[str, object], field: str) -> None:
    if type(payload.get(field)) is not int:
        raise TypeError(f"{field} must be an integer")


def _require_revision(revision_id: object, previous_revision_id: object) -> tuple[str, str | None]:
    revision = _require_non_empty(revision_id, "revision_id")
    previous = (
        None
        if previous_revision_id is None
        else _require_non_empty(previous_revision_id, "previous_revision_id")
    )
    if previous == revision:
        raise ValueError("previous_revision_id must differ from revision_id")
    return revision, previous


def _require_instrument(value: object) -> str:
    instrument = _require_non_empty(value, "instrument_id")
    parts = instrument.split(".")
    if len(parts) != 2 or len(parts[0]) != 6 or parts[1] not in {"SH", "SZ", "BJ"}:
        raise ValueError("instrument_id must use canonical unified code form")
    parsed = parse_instrument_code(parts[0])
    if parsed is None or parsed.unified_code != instrument:
        raise ValueError("instrument_id must use canonical unified code form")
    return instrument


def _enum_value(value: object, enum_type: type[StrEnum], name: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {name}: {value!r}") from error


def _require_time_chain(
    publish_time: datetime,
    ingest_time: datetime,
    processing_time: datetime,
    available_time: datetime,
) -> tuple[datetime, datetime, datetime, datetime]:
    publish = _require_aware(publish_time, "publish_time")
    ingest = _require_aware(ingest_time, "ingest_time")
    processing = _require_aware(processing_time, "processing_time")
    available = _require_aware(available_time, "available_time")
    if publish > ingest:
        raise ValueError("publish_time must be <= ingest_time")
    if ingest > processing:
        raise ValueError("ingest_time must be <= processing_time")
    if processing > available:
        raise ValueError("processing_time must be <= available_time")
    return publish, ingest, processing, available


def _validate_deletion(
    deleted: object,
    deleted_at: datetime | None,
    deletion_reason: str | None,
    available_time: datetime,
) -> tuple[bool, datetime | None, str | None]:
    is_deleted = _require_bool(deleted, "deleted")
    if is_deleted:
        if deleted_at is None:
            raise ValueError("deleted content must have deleted_at")
        deleted_time = _require_aware(deleted_at, "deleted_at")
        if deleted_time < available_time:
            raise ValueError("deleted_at must be >= available_time")
        return (
            is_deleted,
            deleted_time,
            _require_non_empty(deletion_reason, "deletion_reason", 1000),
        )
    if deleted_at is not None or deletion_reason is not None:
        raise ValueError("non-deleted content must not have deletion metadata")
    return is_deleted, None, None


def _content_fingerprint(title: str, body: str) -> str:
    material = title.encode("utf-8") + b"\x00" + body.encode("utf-8")
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class KolContent:
    content_id: str
    content_version: str
    revision_id: str
    previous_revision_id: str | None
    kol_id: str
    content_type: ContentType
    title: str
    body: str
    event_time: datetime | None
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    available_time: datetime
    source: str
    source_version: str
    deleted: bool
    deleted_at: datetime | None
    deletion_reason: str | None
    schema_version: str = KOL_CONTENT_SCHEMA_VERSION
    content_fingerprint: str = field(init=False)
    content_fingerprint_algorithm_version: str = field(
        init=False,
        default=KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION,
    )

    def __post_init__(self) -> None:
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.content_version, "content_version")
        revision, previous = _require_revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _require_non_empty(self.kol_id, "kol_id")
        content_type = _enum_value(self.content_type, ContentType, "content_type")
        object.__setattr__(self, "content_type", content_type)
        _require_non_empty(self.title, "title", 10000)
        _require_non_empty(self.body, "body", 1000000)
        if self.schema_version != KOL_CONTENT_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        event = None if self.event_time is None else _require_aware(self.event_time, "event_time")
        object.__setattr__(self, "event_time", event)
        publish, ingest, processing, available = _require_time_chain(
            self.publish_time,
            self.ingest_time,
            self.processing_time,
            self.available_time,
        )
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(self, "available_time", available)
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        deleted, deleted_at, deletion_reason = _validate_deletion(
            self.deleted,
            self.deleted_at,
            self.deletion_reason,
            available,
        )
        object.__setattr__(self, "deleted", deleted)
        object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(self, "deletion_reason", deletion_reason)
        object.__setattr__(self, "content_fingerprint", _content_fingerprint(self.title, self.body))

    def visible_at(self, decision_time: datetime) -> bool:
        decision = _require_aware(decision_time, "decision_time")
        return not self.deleted and self.available_time <= decision


@dataclass(frozen=True, slots=True)
class KolMention:
    mention_id: str
    revision_id: str
    previous_revision_id: str | None
    content_id: str
    content_version: str
    kol_id: str
    mention_type: MentionType
    surface_text: str
    start_offset: int
    end_offset: int
    available_time: datetime
    source: str
    source_version: str
    schema_version: str = KOL_MENTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.mention_id, "mention_id")
        revision, previous = _require_revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.content_version, "content_version")
        _require_non_empty(self.kol_id, "kol_id")
        object.__setattr__(
            self, "mention_type", _enum_value(self.mention_type, MentionType, "mention_type")
        )
        _require_non_empty(self.surface_text, "surface_text", 1000)
        start = _require_int(self.start_offset, "start_offset")
        end = _require_int(self.end_offset, "end_offset")
        if start < 0 or end <= start or start > 1000000 or end > 1000000:
            raise ValueError("end_offset must be greater than start_offset")
        object.__setattr__(
            self, "available_time", _require_aware(self.available_time, "available_time")
        )
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        if self.schema_version != KOL_MENTION_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")


@dataclass(frozen=True, slots=True)
class KolEvidence:
    evidence_id: str
    revision_id: str
    previous_revision_id: str | None
    content_id: str
    content_version: str
    content_available_time: datetime
    source: str
    source_version: str
    locator_type: LocatorType
    locator: str
    excerpt: str
    evidence_grade: EvidenceGrade
    evidence_grade_version: str
    available_time: datetime
    schema_version: str = KOL_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.evidence_id, "evidence_id")
        revision, previous = _require_revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.content_version, "content_version")
        content_available = _require_aware(self.content_available_time, "content_available_time")
        available = _require_aware(self.available_time, "available_time")
        if content_available > available:
            raise ValueError("content_available_time must be <= available_time")
        object.__setattr__(self, "content_available_time", content_available)
        object.__setattr__(self, "available_time", available)
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        object.__setattr__(
            self, "locator_type", _enum_value(self.locator_type, LocatorType, "locator_type")
        )
        locator = _require_non_empty(self.locator, "locator")
        excerpt = _require_non_empty(self.excerpt, "excerpt")
        object.__setattr__(
            self,
            "evidence_grade",
            _enum_value(self.evidence_grade, EvidenceGrade, "evidence_grade"),
        )
        if self.evidence_grade_version != KOL_EVIDENCE_GRADE_VERSION:
            raise ValueError("unsupported evidence_grade_version")
        if len(locator) > 2048:
            raise ValueError("locator exceeds maximum length")
        if len(excerpt) > 4000:
            raise ValueError("excerpt exceeds maximum length")
        if self.schema_version != KOL_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")


@dataclass(frozen=True, slots=True)
class ClaimEvidenceReference:
    evidence_id: str
    evidence_revision_id: str
    content_id: str
    content_version: str
    content_available_time: datetime
    evidence_available_time: datetime
    source: str
    source_version: str

    def __post_init__(self) -> None:
        _require_non_empty(self.evidence_id, "evidence_id")
        _require_non_empty(self.evidence_revision_id, "evidence_revision_id")
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.content_version, "content_version")
        content_available = _require_aware(self.content_available_time, "content_available_time")
        evidence_available = _require_aware(self.evidence_available_time, "evidence_available_time")
        if content_available > evidence_available:
            raise ValueError("content_available_time must be <= evidence_available_time")
        object.__setattr__(self, "content_available_time", content_available)
        object.__setattr__(self, "evidence_available_time", evidence_available)
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")


@dataclass(frozen=True, slots=True)
class KolClaim:
    claim_id: str
    revision_id: str
    previous_revision_id: str | None
    content_id: str
    content_version: str
    content_available_time: datetime
    kol_id: str
    statement: str
    statement_kind: ClaimStatementKind
    instrument_id: str
    direction: ClaimDirection
    attribution: ClaimAttribution
    uncertainty: ClaimUncertainty
    confidence_bps: int
    review_status: ReviewStatus
    event_time: datetime
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    available_time: datetime
    source: str
    source_version: str
    evidence: tuple[ClaimEvidenceReference, ...]
    deleted: bool
    deleted_at: datetime | None
    deletion_reason: str | None
    schema_version: str = KOL_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.claim_id, "claim_id")
        revision, previous = _require_revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _require_non_empty(self.content_id, "content_id")
        _require_non_empty(self.content_version, "content_version")
        content_available = _require_aware(self.content_available_time, "content_available_time")
        object.__setattr__(self, "content_available_time", content_available)
        _require_non_empty(self.kol_id, "kol_id")
        _require_non_empty(self.statement, "statement", 10000)
        object.__setattr__(
            self,
            "statement_kind",
            _enum_value(self.statement_kind, ClaimStatementKind, "statement_kind"),
        )
        object.__setattr__(self, "instrument_id", _require_instrument(self.instrument_id))
        object.__setattr__(
            self, "direction", _enum_value(self.direction, ClaimDirection, "direction")
        )
        object.__setattr__(
            self,
            "attribution",
            _enum_value(self.attribution, ClaimAttribution, "attribution"),
        )
        object.__setattr__(
            self,
            "uncertainty",
            _enum_value(self.uncertainty, ClaimUncertainty, "uncertainty"),
        )
        if self.statement_kind is ClaimStatementKind.QUOTE and self.attribution not in {
            ClaimAttribution.QUOTED,
            ClaimAttribution.REPORTED,
        }:
            raise ValueError("QUOTE claims require QUOTED or REPORTED attribution")
        if (
            self.statement_kind is ClaimStatementKind.AMBIGUOUS
            and self.uncertainty is ClaimUncertainty.NONE
        ):
            raise ValueError("AMBIGUOUS claims require non-NONE uncertainty")
        confidence = _require_int(self.confidence_bps, "confidence_bps")
        if not 0 <= confidence <= 10000:
            raise ValueError("confidence_bps must be between 0 and 10000")
        object.__setattr__(
            self, "review_status", _enum_value(self.review_status, ReviewStatus, "review_status")
        )
        event = _require_aware(self.event_time, "event_time")
        publish, ingest, processing, available = _require_time_chain(
            self.publish_time,
            self.ingest_time,
            self.processing_time,
            self.available_time,
        )
        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(self, "available_time", available)
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        if type(self.evidence) is not tuple or not self.evidence:
            raise ValueError("claim must have at least one evidence reference")
        identities = {(item.evidence_id, item.evidence_revision_id) for item in self.evidence}
        if len(identities) != len(self.evidence):
            raise ValueError("claim evidence references must be unique")
        deleted, deleted_at, deletion_reason = _validate_deletion(
            self.deleted,
            self.deleted_at,
            self.deletion_reason,
            available,
        )
        object.__setattr__(self, "deleted", deleted)
        object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(self, "deletion_reason", deletion_reason)
        if self.schema_version != KOL_CLAIM_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        self.validate_evidence_references()

    def validate_evidence_references(self) -> None:
        for reference in self.evidence:
            if reference.content_id != self.content_id:
                raise ValueError("claim evidence content id mismatch")
            if reference.content_version != self.content_version:
                raise ValueError("claim evidence content version mismatch")
            if reference.content_available_time > self.available_time:
                raise ValueError("claim available_time must include content availability")
            if reference.evidence_available_time > self.available_time:
                raise ValueError("claim available_time must include evidence availability")

    def visible_at(self, decision_time: datetime) -> bool:
        decision = _require_aware(decision_time, "decision_time")
        return not self.deleted and self.available_time <= decision


@dataclass(frozen=True, slots=True)
class KolPositionClaim:
    position_claim_id: str
    revision_id: str
    previous_revision_id: str | None
    claim_id: str
    claim_revision_id: str
    kol_id: str
    instrument_id: str
    position: PositionDirection
    time_horizon: PositionTimeHorizon
    execution_semantics: ExecutionSemantics
    confidence_bps: int
    review_status: ReviewStatus
    event_time: datetime
    publish_time: datetime
    ingest_time: datetime
    processing_time: datetime
    available_time: datetime
    source: str
    source_version: str
    deleted: bool
    deleted_at: datetime | None
    deletion_reason: str | None
    schema_version: str = KOL_POSITION_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_non_empty(self.position_claim_id, "position_claim_id")
        revision, previous = _require_revision(self.revision_id, self.previous_revision_id)
        object.__setattr__(self, "revision_id", revision)
        object.__setattr__(self, "previous_revision_id", previous)
        _require_non_empty(self.claim_id, "claim_id")
        _require_non_empty(self.claim_revision_id, "claim_revision_id")
        _require_non_empty(self.kol_id, "kol_id")
        object.__setattr__(self, "instrument_id", _require_instrument(self.instrument_id))
        object.__setattr__(
            self, "position", _enum_value(self.position, PositionDirection, "position")
        )
        object.__setattr__(
            self,
            "time_horizon",
            _enum_value(self.time_horizon, PositionTimeHorizon, "time_horizon"),
        )
        object.__setattr__(
            self,
            "execution_semantics",
            _enum_value(self.execution_semantics, ExecutionSemantics, "execution_semantics"),
        )
        confidence = _require_int(self.confidence_bps, "confidence_bps")
        if not 0 <= confidence <= 10000:
            raise ValueError("confidence_bps must be between 0 and 10000")
        object.__setattr__(
            self, "review_status", _enum_value(self.review_status, ReviewStatus, "review_status")
        )
        event = _require_aware(self.event_time, "event_time")
        publish, ingest, processing, available = _require_time_chain(
            self.publish_time,
            self.ingest_time,
            self.processing_time,
            self.available_time,
        )
        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "publish_time", publish)
        object.__setattr__(self, "ingest_time", ingest)
        object.__setattr__(self, "processing_time", processing)
        object.__setattr__(self, "available_time", available)
        _require_non_empty(self.source, "source")
        _require_non_empty(self.source_version, "source_version")
        deleted, deleted_at, deletion_reason = _validate_deletion(
            self.deleted,
            self.deleted_at,
            self.deletion_reason,
            available,
        )
        object.__setattr__(self, "deleted", deleted)
        object.__setattr__(self, "deleted_at", deleted_at)
        object.__setattr__(self, "deletion_reason", deletion_reason)
        if self.schema_version != KOL_POSITION_CLAIM_SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")

    def visible_at(self, decision_time: datetime) -> bool:
        decision = _require_aware(decision_time, "decision_time")
        return not self.deleted and self.available_time <= decision


def validate_evidence_binding(content: KolContent, evidence: KolEvidence) -> None:
    if type(content) is not KolContent or type(evidence) is not KolEvidence:
        raise TypeError("content and evidence must be KOL domain models")
    if evidence.content_id != content.content_id:
        raise ValueError("evidence content id mismatch")
    if evidence.content_version != content.content_version:
        raise ValueError("evidence content version mismatch")
    if evidence.content_available_time != content.available_time:
        raise ValueError("evidence content available time mismatch")
    if evidence.source != content.source:
        raise ValueError("evidence source mismatch")
    if evidence.source_version != content.source_version:
        raise ValueError("evidence source version mismatch")
    if evidence.available_time < content.available_time:
        raise ValueError("evidence available time must include content availability")


def validate_position_claim_link(position: KolPositionClaim, claim: KolClaim) -> None:
    if type(position) is not KolPositionClaim or type(claim) is not KolClaim:
        raise TypeError("position and claim must be KOL domain models")
    if position.claim_id != claim.claim_id:
        raise ValueError("position claim id mismatch")
    if position.claim_revision_id != claim.revision_id:
        raise ValueError("position claim revision mismatch")
    if position.kol_id != claim.kol_id or position.instrument_id != claim.instrument_id:
        raise ValueError("position claim identity mismatch")
    if position.source != claim.source or position.source_version != claim.source_version:
        raise ValueError("position claim source metadata mismatch")
    if (
        position.confidence_bps != claim.confidence_bps
        or position.review_status != claim.review_status
        or position.event_time != claim.event_time
        or position.publish_time != claim.publish_time
        or position.ingest_time != claim.ingest_time
        or position.processing_time != claim.processing_time
    ):
        raise ValueError("position claim metadata mismatch")
    if position.available_time < claim.available_time:
        raise ValueError("position claim available_time must include claim availability")


def _content_payload(model: KolContent) -> dict[str, object]:
    return {
        "schemaVersion": model.schema_version,
        "contentId": model.content_id,
        "contentVersion": model.content_version,
        "revisionId": model.revision_id,
        "previousRevisionId": model.previous_revision_id,
        "kolId": model.kol_id,
        "contentType": model.content_type.value,
        "title": model.title,
        "body": model.body,
        "contentFingerprint": model.content_fingerprint,
        "contentFingerprintAlgorithmVersion": model.content_fingerprint_algorithm_version,
        "eventTime": None if model.event_time is None else model.event_time,
        "publishTime": model.publish_time,
        "ingestTime": model.ingest_time,
        "processingTime": model.processing_time,
        "availableTime": model.available_time,
        "source": model.source,
        "sourceVersion": model.source_version,
        "deleted": model.deleted,
        "deletedAt": model.deleted_at,
        "deletionReason": model.deletion_reason,
    }


def _mention_payload(model: KolMention) -> dict[str, object]:
    return {
        "schemaVersion": model.schema_version,
        "mentionId": model.mention_id,
        "revisionId": model.revision_id,
        "previousRevisionId": model.previous_revision_id,
        "contentId": model.content_id,
        "contentVersion": model.content_version,
        "kolId": model.kol_id,
        "mentionType": model.mention_type.value,
        "surfaceText": model.surface_text,
        "startOffset": model.start_offset,
        "endOffset": model.end_offset,
        "availableTime": model.available_time,
        "source": model.source,
        "sourceVersion": model.source_version,
    }


def _evidence_payload(model: KolEvidence) -> dict[str, object]:
    return {
        "schemaVersion": model.schema_version,
        "evidenceId": model.evidence_id,
        "revisionId": model.revision_id,
        "previousRevisionId": model.previous_revision_id,
        "contentId": model.content_id,
        "contentVersion": model.content_version,
        "contentAvailableTime": model.content_available_time,
        "source": model.source,
        "sourceVersion": model.source_version,
        "locatorType": model.locator_type.value,
        "locator": model.locator,
        "excerpt": model.excerpt,
        "evidenceGrade": model.evidence_grade.value,
        "evidenceGradeVersion": model.evidence_grade_version,
        "availableTime": model.available_time,
    }


def _claim_evidence_payload(reference: ClaimEvidenceReference) -> dict[str, object]:
    return {
        "evidenceId": reference.evidence_id,
        "evidenceRevisionId": reference.evidence_revision_id,
        "contentId": reference.content_id,
        "contentVersion": reference.content_version,
        "contentAvailableTime": reference.content_available_time,
        "evidenceAvailableTime": reference.evidence_available_time,
        "source": reference.source,
        "sourceVersion": reference.source_version,
    }


def _claim_payload(model: KolClaim) -> dict[str, object]:
    return {
        "schemaVersion": model.schema_version,
        "claimId": model.claim_id,
        "revisionId": model.revision_id,
        "previousRevisionId": model.previous_revision_id,
        "contentId": model.content_id,
        "contentVersion": model.content_version,
        "contentAvailableTime": model.content_available_time,
        "kolId": model.kol_id,
        "statement": model.statement,
        "statementKind": model.statement_kind.value,
        "instrumentId": model.instrument_id,
        "direction": model.direction.value,
        "attribution": model.attribution.value,
        "uncertainty": model.uncertainty.value,
        "confidenceBps": model.confidence_bps,
        "reviewStatus": model.review_status.value,
        "eventTime": model.event_time,
        "publishTime": model.publish_time,
        "ingestTime": model.ingest_time,
        "processingTime": model.processing_time,
        "availableTime": model.available_time,
        "source": model.source,
        "sourceVersion": model.source_version,
        "evidence": [_claim_evidence_payload(reference) for reference in model.evidence],
        "deleted": model.deleted,
        "deletedAt": model.deleted_at,
        "deletionReason": model.deletion_reason,
    }


def _position_payload(model: KolPositionClaim) -> dict[str, object]:
    return {
        "schemaVersion": model.schema_version,
        "positionClaimId": model.position_claim_id,
        "revisionId": model.revision_id,
        "previousRevisionId": model.previous_revision_id,
        "claimId": model.claim_id,
        "claimRevisionId": model.claim_revision_id,
        "kolId": model.kol_id,
        "instrumentId": model.instrument_id,
        "position": model.position.value,
        "timeHorizon": model.time_horizon.value,
        "executionSemantics": model.execution_semantics.value,
        "confidenceBps": model.confidence_bps,
        "reviewStatus": model.review_status.value,
        "eventTime": model.event_time,
        "publishTime": model.publish_time,
        "ingestTime": model.ingest_time,
        "processingTime": model.processing_time,
        "availableTime": model.available_time,
        "source": model.source,
        "sourceVersion": model.source_version,
        "deleted": model.deleted,
        "deletedAt": model.deleted_at,
        "deletionReason": model.deletion_reason,
    }


def _content_from_dto(dto: KolContentDTO) -> KolContent:
    model = KolContent(
        content_id=dto.content_id,
        content_version=dto.content_version,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        kol_id=dto.kol_id,
        content_type=ContentType(dto.content_type.value),
        title=dto.title,
        body=dto.body,
        event_time=dto.event_time,
        publish_time=dto.publish_time,
        ingest_time=dto.ingest_time,
        processing_time=dto.processing_time,
        available_time=dto.available_time,
        source=dto.source,
        source_version=dto.source_version,
        deleted=dto.deleted,
        deleted_at=dto.deleted_at,
        deletion_reason=dto.deletion_reason,
        schema_version=dto.schema_version.value,
    )
    if dto.content_fingerprint != model.content_fingerprint:
        raise ValueError("content_fingerprint does not match content")
    if dto.content_fingerprint_algorithm_version.value != KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION:
        raise ValueError("unsupported content fingerprint algorithm")
    return model


def _mention_from_dto(dto: KolMentionDTO) -> KolMention:
    return KolMention(
        mention_id=dto.mention_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        content_id=dto.content_id,
        content_version=dto.content_version,
        kol_id=dto.kol_id,
        mention_type=MentionType(dto.mention_type.value),
        surface_text=dto.surface_text,
        start_offset=dto.start_offset,
        end_offset=dto.end_offset,
        available_time=dto.available_time,
        source=dto.source,
        source_version=dto.source_version,
        schema_version=dto.schema_version.value,
    )


def _evidence_from_dto(dto: KolEvidenceDTO) -> KolEvidence:
    return KolEvidence(
        evidence_id=dto.evidence_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        content_id=dto.content_id,
        content_version=dto.content_version,
        content_available_time=dto.content_available_time,
        source=dto.source,
        source_version=dto.source_version,
        locator_type=LocatorType(dto.locator_type.value),
        locator=dto.locator,
        excerpt=dto.excerpt,
        evidence_grade=EvidenceGrade(dto.evidence_grade.value),
        evidence_grade_version=dto.evidence_grade_version.value,
        available_time=dto.available_time,
        schema_version=dto.schema_version.value,
    )


def _claim_reference_from_dto(dto: KolClaimEvidenceReferenceDTO) -> ClaimEvidenceReference:
    return ClaimEvidenceReference(
        evidence_id=dto.evidence_id,
        evidence_revision_id=dto.evidence_revision_id,
        content_id=dto.content_id,
        content_version=dto.content_version,
        content_available_time=dto.content_available_time,
        evidence_available_time=dto.evidence_available_time,
        source=dto.source,
        source_version=dto.source_version,
    )


def _claim_from_dto(dto: KolClaimDTO) -> KolClaim:
    return KolClaim(
        claim_id=dto.claim_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        content_id=dto.content_id,
        content_version=dto.content_version,
        content_available_time=dto.content_available_time,
        kol_id=dto.kol_id,
        statement=dto.statement,
        statement_kind=ClaimStatementKind(dto.statement_kind.value),
        instrument_id=dto.instrument_id,
        direction=ClaimDirection(dto.direction.value),
        attribution=ClaimAttribution(dto.attribution.value),
        uncertainty=ClaimUncertainty(dto.uncertainty.value),
        confidence_bps=dto.confidence_bps,
        review_status=ReviewStatus(dto.review_status.value),
        event_time=dto.event_time,
        publish_time=dto.publish_time,
        ingest_time=dto.ingest_time,
        processing_time=dto.processing_time,
        available_time=dto.available_time,
        source=dto.source,
        source_version=dto.source_version,
        evidence=tuple(_claim_reference_from_dto(item) for item in dto.evidence),
        deleted=dto.deleted,
        deleted_at=dto.deleted_at,
        deletion_reason=dto.deletion_reason,
        schema_version=dto.schema_version.value,
    )


def _position_from_dto(dto: KolPositionClaimDTO) -> KolPositionClaim:
    return KolPositionClaim(
        position_claim_id=dto.position_claim_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        claim_id=dto.claim_id,
        claim_revision_id=dto.claim_revision_id,
        kol_id=dto.kol_id,
        instrument_id=dto.instrument_id,
        position=PositionDirection(dto.position.value),
        time_horizon=PositionTimeHorizon(dto.time_horizon.value),
        execution_semantics=ExecutionSemantics(dto.execution_semantics.value),
        confidence_bps=dto.confidence_bps,
        review_status=ReviewStatus(dto.review_status.value),
        event_time=dto.event_time,
        publish_time=dto.publish_time,
        ingest_time=dto.ingest_time,
        processing_time=dto.processing_time,
        available_time=dto.available_time,
        source=dto.source,
        source_version=dto.source_version,
        deleted=dto.deleted,
        deleted_at=dto.deleted_at,
        deletion_reason=dto.deletion_reason,
        schema_version=dto.schema_version.value,
    )


@overload
def to_contract(model: KolContent) -> KolContentDTO: ...


@overload
def to_contract(model: KolMention) -> KolMentionDTO: ...


@overload
def to_contract(model: KolEvidence) -> KolEvidenceDTO: ...


@overload
def to_contract(model: KolClaim) -> KolClaimDTO: ...


@overload
def to_contract(model: KolPositionClaim) -> KolPositionClaimDTO: ...


def to_contract(
    model: KolContent | KolMention | KolEvidence | KolClaim | KolPositionClaim,
) -> KolContentDTO | KolMentionDTO | KolEvidenceDTO | KolClaimDTO | KolPositionClaimDTO:
    if type(model) is KolContent:
        return KolContentDTO.model_validate(_content_payload(model))
    if type(model) is KolMention:
        return KolMentionDTO.model_validate(_mention_payload(model))
    if type(model) is KolEvidence:
        return KolEvidenceDTO.model_validate(_evidence_payload(model))
    if type(model) is KolClaim:
        return KolClaimDTO.model_validate(_claim_payload(model))
    if type(model) is KolPositionClaim:
        return KolPositionClaimDTO.model_validate(_position_payload(model))
    raise TypeError(f"unsupported KOL domain model: {type(model).__name__}")


@overload
def from_contract(value: KolContentDTO) -> KolContent: ...


@overload
def from_contract(value: KolMentionDTO) -> KolMention: ...


@overload
def from_contract(value: KolEvidenceDTO) -> KolEvidence: ...


@overload
def from_contract(value: KolClaimDTO) -> KolClaim: ...


@overload
def from_contract(value: KolPositionClaimDTO) -> KolPositionClaim: ...


def from_contract(
    value: KolContentDTO | KolMentionDTO | KolEvidenceDTO | KolClaimDTO | KolPositionClaimDTO,
) -> KolContent | KolMention | KolEvidence | KolClaim | KolPositionClaim:
    if type(value) is KolContentDTO:
        return _content_from_dto(value)
    if type(value) is KolMentionDTO:
        return _mention_from_dto(value)
    if type(value) is KolEvidenceDTO:
        return _evidence_from_dto(value)
    if type(value) is KolClaimDTO:
        return _claim_from_dto(value)
    if type(value) is KolPositionClaimDTO:
        return _position_from_dto(value)
    raise TypeError(f"unsupported KOL contract: {type(value).__name__}")


def parse_kol_content_payload(payload: Mapping[str, object]) -> KolContent:
    _require_wire_bool(payload, "deleted")
    return _content_from_dto(KolContentDTO.model_validate(payload))


def parse_kol_mention_payload(payload: Mapping[str, object]) -> KolMention:
    _require_wire_int(payload, "startOffset")
    _require_wire_int(payload, "endOffset")
    return _mention_from_dto(KolMentionDTO.model_validate(payload))


def parse_kol_evidence_payload(payload: Mapping[str, object]) -> KolEvidence:
    return _evidence_from_dto(KolEvidenceDTO.model_validate(payload))


def parse_kol_claim_payload(payload: Mapping[str, object]) -> KolClaim:
    _require_wire_int(payload, "confidenceBps")
    _require_wire_bool(payload, "deleted")
    return _claim_from_dto(KolClaimDTO.model_validate(payload))


def parse_kol_position_claim_payload(payload: Mapping[str, object]) -> KolPositionClaim:
    _require_wire_int(payload, "confidenceBps")
    _require_wire_bool(payload, "deleted")
    return _position_from_dto(KolPositionClaimDTO.model_validate(payload))


Content = KolContent
Mention = KolMention
Evidence = KolEvidence
Claim = KolClaim
PositionClaim = KolPositionClaim

__all__ = [
    "Claim",
    "ClaimAttribution",
    "ClaimDirection",
    "ClaimEvidenceReference",
    "ClaimStatementKind",
    "ClaimUncertainty",
    "Content",
    "ContentType",
    "Evidence",
    "ExecutionSemantics",
    "KOL_ALGORITHM_VERSION",
    "KOL_CLAIM_SCHEMA_VERSION",
    "KOL_CONTENT_FINGERPRINT_ALGORITHM_VERSION",
    "KOL_CONTENT_SCHEMA_VERSION",
    "KOL_EVIDENCE_SCHEMA_VERSION",
    "KOL_MENTION_SCHEMA_VERSION",
    "KOL_POSITION_CLAIM_SCHEMA_VERSION",
    "KolClaim",
    "KolContent",
    "KolEvidence",
    "KolMention",
    "KolPositionClaim",
    "LocatorType",
    "Mention",
    "MentionType",
    "NON_EXECUTABLE_POSITION_CLAIM",
    "PositionClaim",
    "PositionDirection",
    "PositionTimeHorizon",
    "ReviewStatus",
    "from_contract",
    "parse_kol_claim_payload",
    "parse_kol_content_payload",
    "parse_kol_evidence_payload",
    "parse_kol_mention_payload",
    "parse_kol_position_claim_payload",
    "to_contract",
    "validate_evidence_binding",
    "validate_position_claim_link",
]
