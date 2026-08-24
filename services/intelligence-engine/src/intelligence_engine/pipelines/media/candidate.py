"""Closed, deterministic boundary for fake ASR/OCR recognition output."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from .models import (
    MediaBoundingBox,
    MediaChunk,
    MediaKind,
    MediaManifest,
    MediaProcessorKind,
    MediaTextSegment,
    strict_int,
)

MEDIA_CANDIDATE_SCHEMA_VERSION = "media-recognition-candidate-v1"
_FRAME_IDENTITY = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


@dataclass(frozen=True, slots=True)
class MediaRecognitionCandidate:
    schema_version: str
    text: str
    language: str
    confidence_bps: int
    quality_bps: int
    segments: tuple[MediaTextSegment, ...]
    frame_identity: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != MEDIA_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported recognition candidate schema version")
        if type(self.text) is not str or not self.text or len(self.text) > 2_000_000:
            raise ValueError("text must be a non-empty string within the candidate limit")
        if type(self.language) is not str or _LANGUAGE.fullmatch(self.language) is None:
            raise ValueError("language must be a BCP-47 language tag")
        for value, name in (
            (self.confidence_bps, "confidence_bps"),
            (self.quality_bps, "quality_bps"),
        ):
            parsed = strict_int(value, name)
            if not 0 <= parsed <= 10_000:
                raise ValueError(f"{name} must be between 0 and 10000")
        if type(self.segments) is not tuple or not self.segments:
            raise TypeError("segments must be a non-empty tuple")
        for segment in self.segments:
            if type(segment) is not MediaTextSegment:
                raise TypeError("segments must contain MediaTextSegment values")
            if self.text[segment.start_offset : segment.end_offset] != segment.text:
                raise ValueError("segment offsets do not match candidate text")
        if self.frame_identity is not None and (
            type(self.frame_identity) is not str
            or _FRAME_IDENTITY.fullmatch(self.frame_identity) is None
        ):
            raise ValueError("frame_identity must be lowercase SHA-256 hex or None")

    @property
    def identity(self) -> str:
        payload = {
            "segments": [segment.payload() for segment in self.segments],
            "text": self.text,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()


def media_recognition_candidate_payload(
    candidate: MediaRecognitionCandidate,
) -> dict[str, object]:
    """Serialize a candidate to the only payload accepted by the parser."""
    return {
        "confidenceBps": candidate.confidence_bps,
        "frameIdentity": candidate.frame_identity,
        "language": candidate.language,
        "qualityBps": candidate.quality_bps,
        "schemaVersion": candidate.schema_version,
        "segments": [segment.payload() for segment in candidate.segments],
        "text": candidate.text,
    }


def _required_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds maximum length {maximum}")
    return value


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    mapping = cast(Mapping[object, object], value)
    converted: dict[str, object] = {}
    for key in mapping:
        if type(key) is not str:
            raise ValueError(f"{name} has a non-string field")
        converted[key] = mapping[key]
    return converted


def _bps(value: object, name: str) -> int:
    result = strict_int(value, name)
    if not 0 <= result <= 10_000:
        raise ValueError(f"{name} must be between 0 and 10000")
    return result


def _bbox(value: object) -> MediaBoundingBox | None:
    if value is None:
        return None
    payload = _object(value, "bbox")
    if set(payload) != {"x", "y", "width", "height"}:
        raise ValueError("bbox has unknown or missing fields")
    return MediaBoundingBox(
        strict_int(payload["x"], "bbox.x"),
        strict_int(payload["y"], "bbox.y"),
        strict_int(payload["width"], "bbox.width"),
        strict_int(payload["height"], "bbox.height"),
    )


def parse_media_recognition_candidate(
    raw: object,
    *,
    manifest: MediaManifest,
    processor_kind: MediaProcessorKind,
    chunk: MediaChunk | None = None,
) -> MediaRecognitionCandidate:
    # Candidate objects are deliberately serialized back through the closed
    # payload boundary. They never bypass the same unknown-field/type checks.
    if isinstance(raw, MediaRecognitionCandidate):
        raw = media_recognition_candidate_payload(raw)
    payload = _object(raw, "recognition candidate")
    expected = {
        "schemaVersion",
        "text",
        "language",
        "confidenceBps",
        "qualityBps",
        "frameIdentity",
        "segments",
    }
    if set(payload) != expected:
        raise ValueError("recognition candidate has unknown or missing fields")
    if payload["schemaVersion"] != MEDIA_CANDIDATE_SCHEMA_VERSION:
        raise ValueError("unsupported recognition candidate schema version")
    text = _required_text(payload["text"], "text", 2_000_000)
    language = _required_text(payload["language"], "language", 35)
    if _LANGUAGE.fullmatch(language) is None:
        raise ValueError("language must be a BCP-47 language tag")
    confidence = _bps(payload["confidenceBps"], "confidenceBps")
    quality = _bps(payload["qualityBps"], "qualityBps")
    raw_frame_identity = payload["frameIdentity"]
    frame_identity: str | None = None
    if raw_frame_identity is not None:
        if (
            type(raw_frame_identity) is not str
            or _FRAME_IDENTITY.fullmatch(raw_frame_identity) is None
        ):
            raise ValueError("frameIdentity must be lowercase SHA-256 hex or null")
        frame_identity = raw_frame_identity
    raw_segments = payload["segments"]
    if not isinstance(raw_segments, (list, tuple)) or not raw_segments:
        raise ValueError("segments must be a non-empty array")
    segments: list[MediaTextSegment] = []
    for raw_segment in cast(list[object] | tuple[object, ...], raw_segments):
        segment_payload = _object(raw_segment, "segment")
        required_segment = {
            "text",
            "startOffset",
            "endOffset",
            "startMs",
            "endMs",
            "bbox",
            "confidenceBps",
            "qualityBps",
        }
        if set(segment_payload) - required_segment - {
            "frameIdentity"
        } or not required_segment.issubset(segment_payload):
            raise ValueError("segment has unknown or missing fields")
        segment_text = _required_text(segment_payload["text"], "segment.text", 200_000)
        start_offset = strict_int(segment_payload["startOffset"], "startOffset")
        end_offset = strict_int(segment_payload["endOffset"], "endOffset")
        if start_offset < 0 or end_offset <= start_offset or end_offset > len(text):
            raise ValueError("segment offsets are outside candidate text")
        if text[start_offset:end_offset] != segment_text:
            raise ValueError("segment offsets do not match candidate text")
        start_ms = segment_payload["startMs"]
        end_ms = segment_payload["endMs"]
        if start_ms is not None:
            start_ms = strict_int(start_ms, "startMs")
        if end_ms is not None:
            end_ms = strict_int(end_ms, "endMs")
        bbox = _bbox(segment_payload["bbox"])
        raw_segment_frame_identity = segment_payload.get("frameIdentity")
        segment_frame_identity: str | None = None
        if raw_segment_frame_identity is not None:
            if (
                type(raw_segment_frame_identity) is not str
                or _FRAME_IDENTITY.fullmatch(raw_segment_frame_identity) is None
            ):
                raise ValueError("segment.frameIdentity must be lowercase SHA-256 hex or null")
            segment_frame_identity = raw_segment_frame_identity
        if chunk is not None and chunk.frame_identity is not None:
            if segment_frame_identity not in (None, chunk.frame_identity):
                raise ValueError("segment frame identity does not match chunk")
            if frame_identity not in (None, chunk.frame_identity):
                raise ValueError("candidate frame identity does not match chunk")
        if bbox is not None and chunk is not None and chunk.bbox_context is not None:
            context = chunk.bbox_context
            if (
                bbox.x < 0
                or bbox.y < 0
                or bbox.x + bbox.width > context.width
                or bbox.y + bbox.height > context.height
            ):
                raise ValueError("bbox is outside crop context")
            bbox = MediaBoundingBox(
                context.x + bbox.x,
                context.y + bbox.y,
                bbox.width,
                bbox.height,
            )
        dimensions = (
            (chunk.width, chunk.height)
            if chunk is not None and chunk.width is not None and chunk.height is not None
            else (manifest.width, manifest.height)
        )
        if (
            bbox is not None
            and dimensions[0] is not None
            and dimensions[1] is not None
            and (bbox.x + bbox.width > dimensions[0] or bbox.y + bbox.height > dimensions[1])
        ):
            raise ValueError("bbox is outside media dimensions")
        if (
            chunk is not None
            and chunk.frame_identity is None
            and segment_frame_identity is not None
            and frame_identity not in (None, segment_frame_identity)
        ):
            raise ValueError("segment frame identity does not match candidate")
        if chunk is not None and start_ms is not None and end_ms is not None:
            if chunk.start_ms is None or chunk.end_ms is None:
                raise ValueError("candidate timecode has no authoritative chunk range")
            if start_ms < chunk.start_ms or end_ms > chunk.end_ms:
                raise ValueError("candidate timecode is outside chunk range")
        if (
            manifest.duration_ms is not None
            and end_ms is not None
            and end_ms > manifest.duration_ms
        ):
            raise ValueError("candidate timecode is outside manifest duration")
        segments.append(
            MediaTextSegment(
                segment_text,
                start_offset,
                end_offset,
                start_ms,
                end_ms,
                bbox,
                _bps(segment_payload["confidenceBps"], "segment.confidenceBps"),
                _bps(segment_payload["qualityBps"], "segment.qualityBps"),
                frame_identity=(
                    chunk.frame_identity
                    if chunk is not None and chunk.frame_identity is not None
                    else segment_frame_identity or frame_identity
                ),
            )
        )
    if type(processor_kind) is not MediaProcessorKind:
        raise TypeError("processor_kind must be a MediaProcessorKind")
    if processor_kind is MediaProcessorKind.ASR:
        if manifest.media_kind not in (MediaKind.AUDIO, MediaKind.VIDEO):
            raise ValueError("ASR requires audio or video media")
        if any(segment.start_ms is None or segment.end_ms is None for segment in segments):
            raise ValueError("ASR segments require timecodes")
    elif manifest.media_kind is MediaKind.IMAGE:
        if any(segment.bbox is None for segment in segments):
            raise ValueError("image OCR segments require a bbox")
    elif manifest.media_kind is MediaKind.VIDEO:
        if any(segment.start_ms is None and segment.bbox is None for segment in segments):
            raise ValueError("video OCR segments require time or bbox")
    else:
        raise ValueError("OCR requires image or video media")
    return MediaRecognitionCandidate(
        schema_version=MEDIA_CANDIDATE_SCHEMA_VERSION,
        text=text,
        language=language,
        confidence_bps=confidence,
        quality_bps=quality,
        segments=tuple(segments),
        frame_identity=frame_identity,
    )


__all__ = [
    "MEDIA_CANDIDATE_SCHEMA_VERSION",
    "MediaRecognitionCandidate",
    "media_recognition_candidate_payload",
    "parse_media_recognition_candidate",
]
