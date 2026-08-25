"""Strict payload conversion and point-in-time helpers for extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import cast

from ashare_contracts import (
    KolClaimExtractionCandidate as CandidateDTO,
)
from ashare_contracts import (
    KolClaimReview as ReviewDTO,
)
from ashare_contracts import (
    KolClaimReviewSubmission as SubmissionDTO,
)

from .models import (
    KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION,
    KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION,
    ClaimAction,
    ClaimAttribution,
    ClaimConditionality,
    ClaimExtractionCandidate,
    ClaimPolarity,
    ClaimReview,
    ClaimReviewDecision,
    ClaimReviewSubmission,
    ClaimStatementKind,
    ContentExactAnchor,
    EventTimeStatus,
    EvidenceGrade,
    MediaExactAnchor,
    deterministic_fingerprint,
)

JsonObject = dict[str, object]
_STRICT_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})"
)


def parse_strict_rfc3339(value: object, name: str) -> datetime:
    if type(value) is not str or _STRICT_RFC3339.fullmatch(value) is None:
        raise ValueError(f"{name} must be a strict RFC3339 string")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{name} is not a valid RFC3339 instant") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed


def _mapping(value: object, name: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    mapping = cast(Mapping[object, object], value)
    result: JsonObject = {}
    for key, item in mapping.items():
        if type(key) is not str:
            raise TypeError(f"{name} keys must be strings")
        result[key] = item
    return result


def _text(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    return value


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    return value


def _optional_datetime(value: object, name: str) -> datetime | None:
    return None if value is None else _datetime(value, name)


def _optional_date(value: object, name: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{name} must be a date")
    return value


def _enum_text(value: object, name: str) -> str:
    return _text(getattr(value, "value", value), name)


def _object_list(value: object, name: str) -> list[JsonObject]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    values = cast(list[object], value)
    return [_mapping(item, name) for item in values]


def _integer_list(value: object, name: str) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    values = cast(list[object], value)
    return tuple(_integer(item, name) for item in values)


def _anchor(value: object) -> ContentExactAnchor | MediaExactAnchor:
    item = _mapping(value, "anchor")
    source_index = _integer(item.get("sourceIndex"), "sourceIndex")
    content_id = _text(item.get("contentId"), "contentId")
    content_version = _text(item.get("contentVersion"), "contentVersion")
    content_revision_id = _text(item.get("contentRevisionId"), "contentRevisionId")
    content_available_time = _datetime(item.get("contentAvailableTime"), "contentAvailableTime")
    source = _text(item.get("source"), "source")
    source_version = _text(item.get("sourceVersion"), "sourceVersion")
    start_offset = _integer(item.get("startOffset"), "startOffset")
    end_offset = _integer(item.get("endOffset"), "endOffset")
    excerpt = _text(item.get("excerpt"), "excerpt")
    evidence_grade = EvidenceGrade(_enum_text(item.get("evidenceGrade"), "evidenceGrade"))
    evidence_grade_version = _enum_text(item.get("evidenceGradeVersion"), "evidenceGradeVersion")
    if item.get("anchorType") == "MEDIA":
        return MediaExactAnchor(
            source_index=source_index,
            content_id=content_id,
            content_version=content_version,
            content_revision_id=content_revision_id,
            content_available_time=content_available_time,
            source=source,
            source_version=source_version,
            start_offset=start_offset,
            end_offset=end_offset,
            excerpt=excerpt,
            evidence_grade=evidence_grade,
            evidence_grade_version=evidence_grade_version,
            evidence_id=_text(item.get("evidenceId"), "evidenceId"),
            evidence_revision_id=_text(item.get("evidenceRevisionId"), "evidenceRevisionId"),
            evidence_available_time=_datetime(
                item.get("evidenceAvailableTime"), "evidenceAvailableTime"
            ),
            media_id=_text(item.get("mediaId"), "mediaId"),
            media_version=_text(item.get("mediaVersion"), "mediaVersion"),
            media_manifest_revision_id=_text(
                item.get("mediaManifestRevisionId"), "mediaManifestRevisionId"
            ),
            segment_indexes=_integer_list(item.get("segmentIndexes"), "segmentIndexes"),
        )
    if item.get("anchorType") != "CONTENT":
        raise ValueError("unsupported anchorType")
    if any(
        item.get(name) is not None
        for name in (
            "evidenceId",
            "evidenceRevisionId",
            "evidenceAvailableTime",
            "mediaId",
            "mediaVersion",
            "mediaManifestRevisionId",
            "segmentIndexes",
        )
    ):
        raise ValueError("content anchors cannot carry media provenance")
    return ContentExactAnchor(
        source_index=source_index,
        content_id=content_id,
        content_version=content_version,
        content_revision_id=content_revision_id,
        content_available_time=content_available_time,
        source=source,
        source_version=source_version,
        start_offset=start_offset,
        end_offset=end_offset,
        excerpt=excerpt,
        evidence_grade=evidence_grade,
        evidence_grade_version=evidence_grade_version,
    )


def parse_claim_extraction_candidate_payload(
    payload: Mapping[str, object],
) -> ClaimExtractionCandidate:
    dto = CandidateDTO.model_validate(dict(payload))
    value = _mapping(dto.model_dump(by_alias=True, mode="python"), "candidate DTO")
    candidate = ClaimExtractionCandidate(
        candidate_id=_text(value.get("candidateId"), "candidateId"),
        revision_id=_text(value.get("revisionId"), "revisionId"),
        previous_revision_id=_optional_text(value.get("previousRevisionId"), "previousRevisionId"),
        statement=_text(value.get("statement"), "statement"),
        action=ClaimAction(_enum_text(value.get("action"), "action")),
        polarity=ClaimPolarity(_enum_text(value.get("polarity"), "polarity")),
        conditionality=ClaimConditionality(
            _enum_text(value.get("conditionality"), "conditionality")
        ),
        statement_kind=ClaimStatementKind(_enum_text(value.get("statementKind"), "statementKind")),
        attribution=ClaimAttribution(_enum_text(value.get("attribution"), "attribution")),
        event_time_status=EventTimeStatus(
            _enum_text(value.get("eventTimeStatus"), "eventTimeStatus")
        ),
        event_time=_optional_datetime(value.get("eventTime"), "eventTime"),
        event_date=_optional_date(value.get("eventDate"), "eventDate"),
        instrument_id=_text(value.get("instrumentId"), "instrumentId"),
        anchors=tuple(_anchor(item) for item in _object_list(value.get("anchors"), "anchors")),
        evidence_grade=EvidenceGrade(_enum_text(value.get("evidenceGrade"), "evidenceGrade")),
        confidence_bps=_integer(value.get("confidenceBps"), "confidenceBps"),
        source=_text(value.get("source"), "source"),
        source_version=_text(value.get("sourceVersion"), "sourceVersion"),
        prompt_version=_text(value.get("promptVersion"), "promptVersion"),
        model_provider=_text(value.get("modelProvider"), "modelProvider"),
        model_version=_text(value.get("modelVersion"), "modelVersion"),
        configuration_fingerprint=_text(
            value.get("configurationFingerprint"), "configurationFingerprint"
        ),
        policy_fingerprint=_text(value.get("policyFingerprint"), "policyFingerprint"),
        recognition_run_id=_text(value.get("recognitionRunId"), "recognitionRunId"),
        publish_time=_datetime(value.get("publishTime"), "publishTime"),
        ingest_time=_datetime(value.get("ingestTime"), "ingestTime"),
        processing_time=_datetime(value.get("processingTime"), "processingTime"),
        available_time=_datetime(value.get("availableTime"), "availableTime"),
        deleted=_boolean(value.get("deleted"), "deleted"),
        deleted_at=_optional_datetime(value.get("deletedAt"), "deletedAt"),
        deletion_reason=_optional_text(value.get("deletionReason"), "deletionReason"),
        schema_version=_enum_text(value.get("schemaVersion"), "schemaVersion"),
        semantic_label=_enum_text(value.get("semanticLabel"), "semanticLabel"),
        evidence_grade_version=_enum_text(
            value.get("evidenceGradeVersion"), "evidenceGradeVersion"
        ),
        algorithm_version=_enum_text(value.get("algorithmVersion"), "algorithmVersion"),
        review_status=_enum_text(value.get("reviewStatus"), "reviewStatus"),
    )
    contract = claim_extraction_candidate_payload(candidate)
    if compute_candidate_id_from_payload(contract) != candidate.candidate_id:
        raise ValueError("candidate_id does not match canonical candidate identity")
    if compute_candidate_revision_id_from_payload(contract) != candidate.revision_id:
        raise ValueError("revision_id does not match canonical revision identity")
    return candidate


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def claim_extraction_candidate_payload(candidate: ClaimExtractionCandidate) -> dict[str, object]:
    anchors: list[dict[str, object]] = []
    for item in candidate.anchors:
        payload: dict[str, object] = {
            "anchorType": item.anchor_type,
            "sourceIndex": item.source_index,
            "contentId": item.content_id,
            "contentVersion": item.content_version,
            "contentRevisionId": item.content_revision_id,
            "contentAvailableTime": _timestamp(item.content_available_time),
            "source": item.source,
            "sourceVersion": item.source_version,
            "startOffset": item.start_offset,
            "endOffset": item.end_offset,
            "excerpt": item.excerpt,
            "evidenceGrade": item.evidence_grade.value,
            "evidenceGradeVersion": item.evidence_grade_version,
        }
        if isinstance(item, MediaExactAnchor):
            payload.update(
                {
                    "evidenceId": item.evidence_id,
                    "evidenceRevisionId": item.evidence_revision_id,
                    "evidenceAvailableTime": _timestamp(item.evidence_available_time),
                    "mediaId": item.media_id,
                    "mediaVersion": item.media_version,
                    "mediaManifestRevisionId": item.media_manifest_revision_id,
                    "segmentIndexes": list(item.segment_indexes),
                }
            )
        anchors.append(payload)
    return {
        "schemaVersion": candidate.schema_version,
        "candidateId": candidate.candidate_id,
        "revisionId": candidate.revision_id,
        "previousRevisionId": candidate.previous_revision_id,
        "semanticLabel": candidate.semantic_label,
        "statement": candidate.statement,
        "action": candidate.action.value,
        "polarity": candidate.polarity.value,
        "conditionality": candidate.conditionality.value,
        "statementKind": candidate.statement_kind.value,
        "attribution": candidate.attribution.value,
        "eventTimeStatus": candidate.event_time_status.value,
        "eventTime": None if candidate.event_time is None else _timestamp(candidate.event_time),
        "eventDate": None if candidate.event_date is None else candidate.event_date.isoformat(),
        "instrumentId": candidate.instrument_id,
        "anchors": anchors,
        "evidenceGrade": candidate.evidence_grade.value,
        "evidenceGradeVersion": candidate.evidence_grade_version,
        "confidenceBps": candidate.confidence_bps,
        "source": candidate.source,
        "sourceVersion": candidate.source_version,
        "algorithmVersion": candidate.algorithm_version,
        "promptVersion": candidate.prompt_version,
        "modelProvider": candidate.model_provider,
        "modelVersion": candidate.model_version,
        "configurationFingerprint": candidate.configuration_fingerprint,
        "policyFingerprint": candidate.policy_fingerprint,
        "recognitionRunId": candidate.recognition_run_id,
        "publishTime": _timestamp(candidate.publish_time),
        "ingestTime": _timestamp(candidate.ingest_time),
        "processingTime": _timestamp(candidate.processing_time),
        "availableTime": _timestamp(candidate.available_time),
        "reviewStatus": candidate.review_status,
        "deleted": candidate.deleted,
        "deletedAt": None if candidate.deleted_at is None else _timestamp(candidate.deleted_at),
        "deletionReason": candidate.deletion_reason,
    }


def to_claim_extraction_candidate_contract(candidate: ClaimExtractionCandidate) -> CandidateDTO:
    payload = claim_extraction_candidate_payload(candidate)
    if compute_candidate_id_from_payload(payload) != candidate.candidate_id:
        raise ValueError("candidate_id does not match canonical candidate identity")
    if compute_candidate_revision_id_from_payload(payload) != candidate.revision_id:
        raise ValueError("revision_id does not match canonical revision identity")
    return CandidateDTO.model_validate(payload)


_IDENTITY_KEYS = (
    "statement",
    "action",
    "polarity",
    "conditionality",
    "statementKind",
    "attribution",
    "eventTimeStatus",
    "eventTime",
    "eventDate",
    "instrumentId",
    "anchors",
    "evidenceGrade",
    "evidenceGradeVersion",
)
_TIME_KEYS = {
    "eventTime",
    "contentAvailableTime",
    "evidenceAvailableTime",
    "publishTime",
    "ingestTime",
    "processingTime",
    "availableTime",
    "deletedAt",
}


def _canonical_identity_value(value: object, key: str | None = None) -> object:
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(name): _canonical_identity_value(item, str(name))
            for name, item in sorted(mapping.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_canonical_identity_value(item) for item in items]
    if key in _TIME_KEYS and isinstance(value, str):
        try:
            return _timestamp(parse_strict_rfc3339(value, key))
        except ValueError:
            return value
    return value


def _candidate_identity_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: _canonical_identity_value(payload.get(key), key) for key in _IDENTITY_KEYS}


def compute_candidate_id_from_payload(payload: Mapping[str, object]) -> str:
    return deterministic_fingerprint(
        {
            "algorithmVersion": KOL_CLAIM_CANDIDATE_ID_ALGORITHM_VERSION,
            "identity": _candidate_identity_payload(payload),
        }
    )


def compute_candidate_revision_id_from_payload(payload: Mapping[str, object]) -> str:
    revision = {
        key: _canonical_identity_value(value, key)
        for key, value in payload.items()
        if key not in {"revisionId", "previousRevisionId"}
    }
    return deterministic_fingerprint(
        {
            "algorithmVersion": KOL_CLAIM_REVISION_ID_ALGORITHM_VERSION,
            "candidateId": payload.get("candidateId"),
            "revision": revision,
        }
    )


def compute_candidate_id(candidate: ClaimExtractionCandidate) -> str:
    return compute_candidate_id_from_payload(claim_extraction_candidate_payload(candidate))


def compute_candidate_revision_id(candidate: ClaimExtractionCandidate) -> str:
    return compute_candidate_revision_id_from_payload(claim_extraction_candidate_payload(candidate))


def parse_claim_review_submission_payload(payload: Mapping[str, object]) -> ClaimReviewSubmission:
    value = _mapping(
        SubmissionDTO.model_validate(dict(payload)).model_dump(by_alias=True, mode="python"),
        "review submission DTO",
    )
    return ClaimReviewSubmission(
        client_request_id=_text(value.get("clientRequestId"), "clientRequestId"),
        candidate_id=_text(value.get("candidateId"), "candidateId"),
        candidate_revision_id=_text(value.get("candidateRevisionId"), "candidateRevisionId"),
        decision=ClaimReviewDecision(_enum_text(value.get("decision"), "decision")),
        reason=_text(value.get("reason"), "reason"),
        comment=_optional_text(value.get("comment"), "comment"),
        expected_previous_review_id=_optional_text(
            value.get("expectedPreviousReviewId"), "expectedPreviousReviewId"
        ),
        schema_version=_text(value.get("schemaVersion"), "schemaVersion"),
    )


def parse_claim_review_payload(payload: Mapping[str, object]) -> ClaimReview:
    value = _mapping(
        ReviewDTO.model_validate(dict(payload)).model_dump(by_alias=True, mode="python"),
        "review DTO",
    )
    return ClaimReview(
        review_id=_text(value.get("reviewId"), "reviewId"),
        candidate_id=_text(value.get("candidateId"), "candidateId"),
        candidate_revision_id=_text(value.get("candidateRevisionId"), "candidateRevisionId"),
        decision=ClaimReviewDecision(_enum_text(value.get("decision"), "decision")),
        reason=_text(value.get("reason"), "reason"),
        comment=_optional_text(value.get("comment"), "comment"),
        reviewer_ref=_text(value.get("reviewerRef"), "reviewerRef"),
        created_at=_datetime(value.get("createdAt"), "createdAt"),
        available_at=_datetime(value.get("availableAt"), "availableAt"),
        submission_fingerprint=_text(value.get("submissionFingerprint"), "submissionFingerprint"),
        previous_review_id=_optional_text(value.get("previousReviewId"), "previousReviewId"),
        schema_version=_text(value.get("schemaVersion"), "schemaVersion"),
        review_meaning=_text(value.get("reviewMeaning"), "reviewMeaning"),
    )


def validate_candidate_pit(candidate: ClaimExtractionCandidate, decision_time: datetime) -> None:
    if not candidate.visible_at(decision_time):
        raise ValueError("candidate is not visible at decision_time")


__all__ = [
    "claim_extraction_candidate_payload",
    "compute_candidate_id",
    "compute_candidate_id_from_payload",
    "compute_candidate_revision_id",
    "compute_candidate_revision_id_from_payload",
    "parse_claim_extraction_candidate_payload",
    "parse_claim_review_payload",
    "parse_claim_review_submission_payload",
    "to_claim_extraction_candidate_contract",
    "validate_candidate_pit",
]
