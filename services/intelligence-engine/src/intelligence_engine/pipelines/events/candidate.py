"""Strict parser for untrusted model event candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from event_core.models import MarketEventType

EVENT_CANDIDATE_SCHEMA_VERSION = "event-candidate-v1"

_CANDIDATE_KEYS = {
    "confidenceBps",
    "eventType",
    "evidenceSpans",
    "headline",
    "instrumentIds",
    "occurTime",
    "schemaVersion",
    "sectorIds",
    "summary",
}
_EVIDENCE_KEYS = {"endOffset", "excerpt", "startOffset"}


class CandidateValidationError(ValueError):
    """The provider payload does not satisfy the candidate boundary."""


class CandidateJsonError(CandidateValidationError):
    """The provider payload is not valid JSON."""


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise CandidateValidationError(f"{field_name} must be an object")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise CandidateValidationError(f"{field_name} keys must be strings")
    return cast(dict[str, object], mapping)


def _text(value: object, field_name: str, *, maximum: int) -> str:
    if type(value) is not str:
        raise CandidateValidationError(f"{field_name} must be a string")
    if not value.strip():
        raise CandidateValidationError(f"{field_name} must not be empty")
    if len(value) > maximum:
        raise CandidateValidationError(f"{field_name} exceeds its maximum length")
    return value


def _strict_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise CandidateValidationError(f"{field_name} must be a strict integer")
    return value


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise CandidateValidationError(f"{field_name} must be an array")
    items = cast(list[object], value)
    result: list[str] = []
    for item in items:
        result.append(_text(item, field_name, maximum=128))
    if len(set(result)) != len(result):
        raise CandidateValidationError(f"{field_name} must not contain duplicates")
    return tuple(result)


def _aware_time(value: object, field_name: str) -> datetime:
    text = _text(value, field_name, maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CandidateValidationError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateValidationError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CandidateEvidenceSpan:
    """Evidence offsets into the exact trusted source text sent to the model."""

    start_offset: int
    end_offset: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class EventCandidate:
    """Untrusted but structurally validated candidate, not a fact-layer event."""

    event_type: MarketEventType
    headline: str
    summary: str
    occur_time: datetime
    instrument_ids: tuple[str, ...]
    sector_ids: tuple[str, ...]
    evidence_spans: tuple[CandidateEvidenceSpan, ...]
    confidence_bps: int


def parse_event_candidate(raw_output: object) -> EventCandidate:
    """Parse exact JSON with no coercion, extra fields, or implicit defaults."""
    if type(raw_output) is not str:
        raise CandidateValidationError("provider output must be a string")
    try:
        decoded = cast(object, json.loads(raw_output))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise CandidateJsonError("provider output is not valid JSON") from error
    payload = _mapping(decoded, "candidate")
    if set(payload) != _CANDIDATE_KEYS:
        raise CandidateValidationError("candidate fields do not match event-candidate-v1")
    if payload["schemaVersion"] != EVENT_CANDIDATE_SCHEMA_VERSION:
        raise CandidateValidationError("unsupported candidate schema version")
    try:
        event_type = MarketEventType(_text(payload["eventType"], "eventType", maximum=64))
    except ValueError as error:
        raise CandidateValidationError("unsupported eventType") from error

    evidence_value = payload["evidenceSpans"]
    if type(evidence_value) is not list:
        raise CandidateValidationError("evidenceSpans must be an array")
    evidence_items = cast(list[object], evidence_value)
    if not evidence_items:
        raise CandidateValidationError("evidenceSpans must not be empty")
    evidence: list[CandidateEvidenceSpan] = []
    identities: set[tuple[int, int, str]] = set()
    for item in evidence_items:
        span = _mapping(item, "evidenceSpan")
        if set(span) != _EVIDENCE_KEYS:
            raise CandidateValidationError("evidence span fields are invalid")
        start = _strict_integer(span["startOffset"], "startOffset")
        end = _strict_integer(span["endOffset"], "endOffset")
        excerpt = _text(span["excerpt"], "excerpt", maximum=50_000)
        if start < 0 or end <= start:
            raise CandidateValidationError("evidence span must be a non-empty half-open range")
        identity = (start, end, excerpt)
        if identity in identities:
            raise CandidateValidationError("evidence spans must not contain duplicates")
        identities.add(identity)
        evidence.append(CandidateEvidenceSpan(start, end, excerpt))

    confidence = _strict_integer(payload["confidenceBps"], "confidenceBps")
    if not 0 <= confidence <= 10_000:
        raise CandidateValidationError("confidenceBps must be between 0 and 10000")
    return EventCandidate(
        event_type=event_type,
        headline=_text(payload["headline"], "headline", maximum=500),
        summary=_text(payload["summary"], "summary", maximum=5_000),
        occur_time=_aware_time(payload["occurTime"], "occurTime"),
        instrument_ids=_string_tuple(payload["instrumentIds"], "instrumentIds"),
        sector_ids=_string_tuple(payload["sectorIds"], "sectorIds"),
        evidence_spans=tuple(evidence),
        confidence_bps=confidence,
    )


__all__ = [
    "CandidateEvidenceSpan",
    "CandidateJsonError",
    "CandidateValidationError",
    "EVENT_CANDIDATE_SCHEMA_VERSION",
    "EventCandidate",
    "parse_event_candidate",
]
