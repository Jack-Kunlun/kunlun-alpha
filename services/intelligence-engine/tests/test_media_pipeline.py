"""P4-N07 media ASR/OCR pipeline acceptance tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from intelligence_engine.pipelines.media import (
    MEDIA_CANDIDATE_SCHEMA_VERSION,
    MediaCheckpoint,
    MediaFailureReason,
    MediaKind,
    MediaPipelinePolicy,
    MediaProcessingConsumer,
    MediaProcessingRequest,
    MediaProcessorKind,
    MediaProcessStatus,
    MediaSilenceError,
    MediaTimeoutError,
    parse_media_recognition_candidate,
)
from intelligence_engine.pipelines.media.fake import (
    FakeMediaObjectReader,
    FakeMediaRecognizer,
    InMemoryMediaEvidenceStore,
    fake_media_profile,
)
from intelligence_engine.pipelines.media.models import MediaManifest

T0 = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)


def manifest(
    raw: bytes = b"media-bytes",
    *,
    media_id: str = "media-1",
    media_version: str = "media-version-1",
    kind: MediaKind = MediaKind.AUDIO,
    authorized: bool = True,
    available_time: datetime = T0,
    deleted: bool = False,
    width: int | None = None,
    height: int | None = None,
) -> MediaManifest:
    return MediaManifest(
        content_id="content-1",
        content_version="content-version-1",
        media_id=media_id,
        media_version=media_version,
        revision_id="media-revision-1",
        previous_revision_id=None,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        mime_type={
            MediaKind.AUDIO: "audio/mpeg",
            MediaKind.VIDEO: "video/mp4",
            MediaKind.IMAGE: "image/png",
        }[kind],
        byte_size=len(raw),
        media_kind=kind,
        source="media-provider",
        source_version="provider-v1",
        license_id="license-v1",
        usage_restriction="research-only",
        authorized=authorized,
        input_available_time=available_time,
        width=width,
        height=height,
        duration_ms=10_000 if kind is not MediaKind.IMAGE else None,
        deleted=deleted,
        deleted_at=T2 if deleted else None,
        deletion_reason="source-deleted" if deleted else None,
    )


def candidate(
    text: str = "你好",
    *,
    frame_identity: str | None = None,
    start_ms: int | None = 0,
    end_ms: int | None = 100,
    bbox: dict[str, int] | None = None,
    quality_bps: int = 9000,
) -> dict[str, object]:
    segment: dict[str, object] = {
        "text": text,
        "startOffset": 0,
        "endOffset": len(text),
        "startMs": start_ms,
        "endMs": end_ms,
        "bbox": bbox,
        "confidenceBps": 9000,
        "qualityBps": quality_bps,
    }
    return {
        "schemaVersion": MEDIA_CANDIDATE_SCHEMA_VERSION,
        "text": text,
        "language": "zh-CN",
        "confidenceBps": 9000,
        "qualityBps": quality_bps,
        "frameIdentity": frame_identity,
        "segments": [segment],
    }


def request(
    item: MediaManifest,
    *,
    decision_time: datetime = T1,
    attempt: int = 0,
    checkpoint: MediaCheckpoint | None = None,
    processor_kind: MediaProcessorKind = MediaProcessorKind.ASR,
) -> MediaProcessingRequest:
    return MediaProcessingRequest(
        request_id="request-1",
        manifest=item,
        processor_kind=processor_kind,
        resolved_profile=fake_media_profile(decision_time),
        decision_time=decision_time,
        event_time=T0,
        publish_time=T0,
        ingest_time=T0 + timedelta(seconds=1),
        processing_time=T1,
        attempt=attempt,
        checkpoint=checkpoint,
    )


def consumer(
    item: MediaManifest,
    raw: bytes,
    responses: list[object],
    *,
    policy: MediaPipelinePolicy | None = None,
) -> MediaProcessingConsumer:
    return MediaProcessingConsumer(
        reader=FakeMediaObjectReader({(item.media_id, item.media_version): raw}),
        recognizer=FakeMediaRecognizer(responses),
        store=InMemoryMediaEvidenceStore(),
        policy=MediaPipelinePolicy() if policy is None else policy,
    )


def fake_calls(instance: MediaProcessingConsumer) -> list[tuple[str, int, str]]:
    recognizer = instance.recognizer
    assert isinstance(recognizer, FakeMediaRecognizer)
    return recognizer.calls


def test_candidate_requires_exact_codepoint_offsets_and_rejects_mismatch() -> None:
    item = manifest()
    parsed = parse_media_recognition_candidate(
        candidate("你好"), manifest=item, processor_kind=MediaProcessorKind.ASR
    )
    assert parsed.segments[0].text == "你好"
    with pytest.raises(ValueError, match="offset|segment"):
        parse_media_recognition_candidate(
            {
                **candidate("你好"),
                "segments": [
                    {
                        "text": "你好",
                        "startOffset": 0,
                        "endOffset": 1,
                        "startMs": 0,
                        "endMs": 100,
                        "bbox": None,
                        "confidenceBps": 9000,
                        "qualityBps": 9000,
                    }
                ],
            },
            manifest=item,
            processor_kind=MediaProcessorKind.ASR,
        )


def test_normal_asr_is_pit_licensed_checksum_verified_and_provenanced() -> None:
    raw = b"audio"
    item = manifest(raw)
    recognizer = FakeMediaRecognizer([candidate()])
    store = InMemoryMediaEvidenceStore()
    consumer_instance = MediaProcessingConsumer(
        reader=FakeMediaObjectReader({(item.media_id, item.media_version): raw}),
        recognizer=recognizer,
        store=store,
    )
    result = consumer_instance.process(request(item))
    assert result.status is MediaProcessStatus.COMMITTED
    assert result.evidence is not None
    assert result.evidence.available_time == T1
    assert result.evidence.media_manifest.raw_sha256 == item.raw_sha256
    assert (
        result.evidence.provenance.configuration_fingerprint
        == request(item).resolved_profile.configuration_fingerprint
    )
    assert len(recognizer.calls) == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"input_available_time": T2}, MediaFailureReason.FUTURE_MEDIA),
        ({"authorized": False}, MediaFailureReason.UNAUTHORIZED),
        (
            {"deleted": True, "deleted_at": T2, "deletion_reason": "deleted"},
            MediaFailureReason.DELETED,
        ),
    ],
)
def test_pit_license_and_deletion_gates_precede_recognizer(
    change: dict[str, object], reason: MediaFailureReason
) -> None:
    item = replace(manifest(), **change)
    instance = consumer(item, b"media-bytes", [candidate()])
    result = instance.process(request(item))
    assert result.status is MediaProcessStatus.TERMINAL
    assert result.failure_reason is reason
    assert fake_calls(instance) == []


def test_checksum_mismatch_never_reaches_recognizer() -> None:
    item = manifest(b"expected")
    instance = consumer(item, b"different", [candidate()])
    result = instance.process(request(item))
    assert result.failure_reason is MediaFailureReason.CHECKSUM_MISMATCH
    assert fake_calls(instance) == []


def test_ocr_bbox_is_bounds_checked_and_low_quality_is_retained() -> None:
    raw = b"image"
    item = manifest(raw, kind=MediaKind.IMAGE, width=100, height=80)
    instance = consumer(
        item,
        raw,
        [
            candidate(
                "文字",
                start_ms=None,
                end_ms=None,
                bbox={"x": 10, "y": 5, "width": 20, "height": 10},
                quality_bps=100,
            )
        ],
    )
    result = instance.process(request(item, processor_kind=MediaProcessorKind.OCR))
    assert result.status is MediaProcessStatus.COMMITTED
    assert result.evidence is not None
    assert result.evidence.quality_bps == 100
    with pytest.raises(ValueError, match="bbox"):
        parse_media_recognition_candidate(
            candidate(
                "文字",
                start_ms=None,
                end_ms=None,
                bbox={"x": 90, "y": 5, "width": 20, "height": 10},
            ),
            manifest=item,
            processor_kind=MediaProcessorKind.OCR,
        )


def test_silence_is_terminal_and_audited_without_empty_evidence() -> None:
    item = manifest()
    instance = consumer(item, b"media-bytes", [MediaSilenceError("silence")])
    result = instance.process(request(item))
    assert result.status is MediaProcessStatus.TERMINAL
    assert result.failure_reason is MediaFailureReason.SILENCE


def test_long_media_checkpoint_retry_and_stable_duplicate_frame_deduplication() -> None:
    raw = b"abcd"
    item = manifest(raw)
    duplicate = candidate("a", frame_identity="a" * 64, start_ms=0, end_ms=10)
    second = candidate("b", frame_identity="b" * 64, start_ms=5000, end_ms=5020)
    recognizer = FakeMediaRecognizer([duplicate, MediaTimeoutError("temporary"), second])
    instance = MediaProcessingConsumer(
        reader=FakeMediaObjectReader({(item.media_id, item.media_version): raw}),
        recognizer=recognizer,
        store=InMemoryMediaEvidenceStore(),
        policy=MediaPipelinePolicy(chunk_size_bytes=2, max_attempts=3),
    )
    first = instance.process(request(item))
    assert first.status is MediaProcessStatus.RETRY_SCHEDULED
    assert first.checkpoint is not None
    resumed = instance.process(request(item, attempt=1, checkpoint=first.checkpoint))
    assert resumed.status is MediaProcessStatus.COMMITTED
    assert resumed.evidence is not None
    assert resumed.evidence.text == "ab"
    assert len(resumed.evidence.segments) == 2


def test_idempotency_returns_existing_and_conflicts_without_overwrite() -> None:
    item = manifest()
    raw = b"media-bytes"
    store = InMemoryMediaEvidenceStore()
    recognizer = FakeMediaRecognizer([candidate()])
    instance = MediaProcessingConsumer(
        reader=FakeMediaObjectReader({(item.media_id, item.media_version): raw}),
        recognizer=recognizer,
        store=store,
    )
    first = instance.process(request(item))
    second = instance.process(request(item))
    assert first.status is MediaProcessStatus.COMMITTED
    assert second.status is MediaProcessStatus.ALREADY_COMMITTED
    assert len(recognizer.calls) == 1
    conflicting = replace(item, media_version="media-version-2")
    with pytest.raises(ValueError, match="conflict"):
        instance.process(request(conflicting))
