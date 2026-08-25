"""Closed model-response parser and trusted source binding."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime
from typing import cast

from kol_core.extraction import (
    ClaimAction,
    ClaimAttribution,
    ClaimConditionality,
    ClaimExtractionCandidate,
    ClaimPolarity,
    ClaimStatementKind,
    ContentExactAnchor,
    EventTimeStatus,
    EvidenceGrade,
    MediaExactAnchor,
    claim_extraction_candidate_payload,
    compute_candidate_id_from_payload,
    compute_candidate_revision_id_from_payload,
    parse_strict_rfc3339,
)

from .models import (
    RAW_CANDIDATE_SCHEMA_VERSION,
    ClaimExtractionPolicy,
    ClaimExtractionRequest,
    ClaimMediaSegment,
    ClaimMediaSource,
)

RAW_KEYS = {
    "schemaVersion",
    "sourceIndex",
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
    "instrumentIndex",
    "confidenceBps",
    "anchors",
}
ANCHOR_KEYS = {"sourceIndex", "startOffset", "endOffset", "excerpt", "segmentIndexes"}


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    mapping = cast(Mapping[object, object], value)
    result: dict[str, object] = {}
    for key, item in mapping.items():
        if type(key) is not str:
            raise ValueError(f"{name} keys must be strings")
        result[key] = item
    if any(key not in RAW_KEYS for key in result) and name == "raw candidate":
        raise ValueError("raw candidate contains unknown fields")
    return result


def _int(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be a strict integer")
    return value


def _string(value: object, name: str, maximum: int = 256) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError(f"{name} is invalid")
    return value


def _instant(value: object | None, name: str) -> datetime | None:
    if value is None:
        return None
    return parse_strict_rfc3339(value, name)


def _calendar_date(value: object | None) -> date | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("eventDate is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("eventDate is invalid") from error


def _source(request: ClaimExtractionRequest, index: int):
    if index < 0 or index >= len(request.sources):
        raise ValueError("sourceIndex is not in the request")
    source = request.sources[index]
    if (
        source.source_index != index
        or source.deleted
        or not source.authorized
        or source.available_time > request.decision_time
    ):
        raise ValueError("source is unavailable at decision_time")
    return source


def _raw_payload(value: object) -> dict[str, object]:
    payload_member = getattr(value, "payload", None)
    if payload_member is not None:
        if not callable(payload_member):
            raise ValueError("candidate payload member must be callable")
        value = cast(Callable[[], object], payload_member)()
    payload = _object(value, "raw candidate")
    if set(payload) != RAW_KEYS and not (
        set(payload) == RAW_KEYS - {"instrumentId"}
        or set(payload) == RAW_KEYS - {"instrumentIndex"}
    ):
        raise ValueError("raw candidate has missing or unknown fields")
    if payload.get("schemaVersion") != RAW_CANDIDATE_SCHEMA_VERSION:
        raise ValueError("unsupported raw candidate version")
    has_instrument_id = "instrumentId" in payload
    has_instrument_index = "instrumentIndex" in payload
    if has_instrument_id == has_instrument_index:
        raise ValueError("raw candidate must provide exactly one instrument selector")
    return payload


def parse_claim_extraction_response(
    raw: object, request: ClaimExtractionRequest, policy: ClaimExtractionPolicy
) -> ClaimExtractionCandidate:
    payload = _raw_payload(raw)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > policy.max_response_bytes:
        raise ValueError("response exceeds budget")
    statement = _string(payload["statement"], "statement", policy.max_statement_codepoints)
    source_index = _int(payload["sourceIndex"], "sourceIndex", 0, 100_000)
    _source(request, source_index)
    used_source_indexes = {source_index}
    anchors_value = payload["anchors"]
    if (
        not isinstance(anchors_value, list)
        or not 1 <= len(cast(list[object], anchors_value)) <= policy.max_anchor_count
    ):
        raise ValueError("anchors exceed policy")
    anchors_raw = cast(list[object], anchors_value)
    instrument = payload.get("instrumentId")
    if instrument is None:
        index = _int(
            payload.get("instrumentIndex"), "instrumentIndex", 0, len(request.instrument_index) - 1
        )
        instrument = request.instrument_index[index]
    instrument = _string(instrument, "instrumentId", 9)
    confidence = _int(payload["confidenceBps"], "confidenceBps", 0, 10_000)
    built: list[ContentExactAnchor | MediaExactAnchor] = []
    for number, raw_anchor in enumerate(anchors_raw):
        if not isinstance(raw_anchor, Mapping):
            raise ValueError(f"anchor {number} must be an object")
        raw_mapping = cast(Mapping[object, object], raw_anchor)
        anchor: dict[str, object] = {}
        for key, item in raw_mapping.items():
            if type(key) is not str:
                raise ValueError("raw anchor keys must be strings")
            anchor[key] = item
        if set(anchor) - ANCHOR_KEYS or set(anchor) < {
            "sourceIndex",
            "startOffset",
            "endOffset",
            "excerpt",
        }:
            raise ValueError("raw anchor has unknown or missing fields")
        anchor_index = _int(anchor["sourceIndex"], "anchor sourceIndex", 0, 100_000)
        anchor_source = _source(request, anchor_index)
        used_source_indexes.add(anchor_index)
        start = _int(anchor["startOffset"], "startOffset", 0, len(anchor_source.text))
        end = _int(anchor["endOffset"], "endOffset", 1, len(anchor_source.text))
        excerpt = _string(anchor["excerpt"], "excerpt", policy.max_anchor_codepoints)
        if end <= start or anchor_source.text[start:end] != excerpt:
            raise ValueError("anchor excerpt does not exactly slice the trusted source")
        if isinstance(anchor_source, ClaimMediaSource):
            indexes_value = anchor.get("segmentIndexes")
            if not isinstance(indexes_value, list) or not indexes_value:
                raise ValueError("media anchor requires segmentIndexes")
            indexes = cast(list[object], indexes_value)
            selected: list[ClaimMediaSegment] = []
            for item in indexes:
                segment_index = _int(item, "segmentIndex", 0, 100_000)
                matches = [
                    segment for segment in anchor_source.segments if segment.index == segment_index
                ]
                if len(matches) != 1:
                    raise ValueError("media segment index is not an exact source segment")
                selected.append(matches[0])
            if start < min(item.start_offset for item in selected) or end > max(
                item.end_offset for item in selected
            ):
                raise ValueError("media anchor is outside selected segment spans")
            if confidence > min(
                [
                    anchor_source.overall_confidence_bps,
                    anchor_source.overall_quality_bps,
                    *(item.confidence_bps for item in selected),
                    *(item.quality_bps for item in selected),
                ]
            ):
                raise ValueError(
                    "candidate confidence exceeds media evidence confidence or quality"
                )
            built.append(
                MediaExactAnchor(
                    source_index=anchor_index,
                    content_id=anchor_source.content_id,
                    content_version=anchor_source.content_version,
                    content_revision_id=anchor_source.content_revision_id,
                    content_available_time=anchor_source.content_available_time,
                    source=anchor_source.source,
                    source_version=anchor_source.source_version,
                    start_offset=start,
                    end_offset=end,
                    excerpt=excerpt,
                    evidence_grade=anchor_source.evidence_grade,
                    evidence_id=anchor_source.evidence_id,
                    evidence_revision_id=anchor_source.evidence_revision_id,
                    evidence_available_time=anchor_source.evidence_available_time,
                    media_id=anchor_source.media_id,
                    media_version=anchor_source.media_version,
                    media_manifest_revision_id=anchor_source.media_manifest_revision_id,
                    segment_indexes=tuple(
                        _int(item, "segmentIndex", 0, 100_000) for item in indexes
                    ),
                )
            )
        else:
            built.append(
                ContentExactAnchor(
                    source_index=anchor_index,
                    content_id=anchor_source.content_id,
                    content_version=anchor_source.content_version,
                    content_revision_id=anchor_source.content_revision_id,
                    content_available_time=anchor_source.available_time,
                    source=anchor_source.source,
                    source_version=anchor_source.source_version,
                    start_offset=start,
                    end_offset=end,
                    excerpt=excerpt,
                    evidence_grade=anchor_source.evidence_grade,
                )
            )
    event_status = payload["eventTimeStatus"]
    event_time = _instant(payload.get("eventTime"), "eventTime")
    event_date = _calendar_date(payload.get("eventDate"))
    if event_status == EventTimeStatus.EXACT.value and (
        event_time is None or event_date is not None
    ):
        raise ValueError("EXACT event time matrix is invalid")
    if event_status == EventTimeStatus.DATE_ONLY.value and (
        event_time is not None or event_date is None
    ):
        raise ValueError("DATE_ONLY event time matrix is invalid")
    if event_status == EventTimeStatus.UNKNOWN.value and (
        event_time is not None or event_date is not None
    ):
        raise ValueError("UNKNOWN event time matrix is invalid")
    profile = request.resolved_profile
    selected_sources = tuple(request.sources[index] for index in sorted(used_source_indexes))
    available = max([request.processing_time, *(item.available_time for item in selected_sources)])
    grades = [item.evidence_grade for item in built]
    grade = min(
        grades,
        key=lambda item: {
            EvidenceGrade.PRIMARY_SOURCE: 0,
            EvidenceGrade.SECONDARY_SOURCE: 1,
            EvidenceGrade.TERTIARY_SOURCE: 2,
            EvidenceGrade.UNCLASSIFIED: 3,
        }[item],
    )
    candidate = ClaimExtractionCandidate(
        candidate_id="pending-candidate",
        revision_id="pending-revision",
        previous_revision_id=None,
        statement=statement,
        action=ClaimAction(payload["action"]),
        polarity=ClaimPolarity(payload["polarity"]),
        conditionality=ClaimConditionality(payload["conditionality"]),
        statement_kind=ClaimStatementKind(payload["statementKind"]),
        attribution=ClaimAttribution(payload["attribution"]),
        event_time_status=EventTimeStatus(event_status),
        event_time=event_time,
        event_date=event_date,
        instrument_id=instrument,
        anchors=tuple(built),
        evidence_grade=grade,
        confidence_bps=confidence,
        source="kol-claim-extractor",
        source_version="claim-extraction-v1",
        prompt_version=profile.prompt.version,
        model_provider=profile.model.provider_id,
        model_version=profile.model.version,
        configuration_fingerprint=profile.configuration_fingerprint,
        policy_fingerprint=policy.fingerprint,
        recognition_run_id=request.extraction_run_id,
        publish_time=min(item.publish_time for item in selected_sources),
        ingest_time=min(item.ingest_time for item in selected_sources),
        processing_time=request.processing_time,
        available_time=available,
    )
    canonical_payload = claim_extraction_candidate_payload(candidate)
    candidate = replace(
        candidate,
        candidate_id=compute_candidate_id_from_payload(canonical_payload),
    )
    canonical_payload = claim_extraction_candidate_payload(candidate)
    return replace(
        candidate,
        revision_id=compute_candidate_revision_id_from_payload(canonical_payload),
    )


__all__ = ["parse_claim_extraction_response"]
