"""Final P4-N07 repair probes: checkpoint, PIT parity, identity, frame, and redaction."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashare_contracts.kol_media_text_evidence import KolMediaTextEvidence
from intelligence_engine.llm.models import ResolvedProfile
from intelligence_engine.pipelines.media import (
    MEDIA_CANDIDATE_SCHEMA_VERSION,
    MediaAuditReason,
    MediaAuditStatus,
    MediaBoundingBox,
    MediaCheckpoint,
    MediaFailureReason,
    MediaKind,
    MediaPipelinePolicy,
    MediaProcessingConsumer,
    MediaProcessingRequest,
    MediaProcessorKind,
    MediaProcessStatus,
    MediaStoreTransientError,
    MediaTextEvidence,
    MediaTimeoutError,
    parse_media_text_evidence_payload,
)
from intelligence_engine.pipelines.media.fake import (
    FakeMediaObjectReader,
    FakeMediaRecognizer,
    InMemoryMediaAuditSink,
    InMemoryMediaEvidenceStore,
    fake_media_profile,
)
from intelligence_engine.pipelines.media.models import (
    MediaChunk,
    MediaManifest,
    MediaTextSegment,
)

T0 = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)


def manifest(
    raw: bytes = b"abcdef",
    *,
    media_id: str = "media-1",
    media_version: str = "media-version-1",
    revision_id: str = "media-revision-1",
    previous_revision_id: str | None = None,
    available_time: datetime = T0,
    kind: MediaKind = MediaKind.AUDIO,
    width: int | None = None,
    height: int | None = None,
    duration_ms: int | None = 1000,
) -> MediaManifest:
    return MediaManifest(
        content_id="content-1",
        content_version="content-version-1",
        media_id=media_id,
        media_version=media_version,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        mime_type="video/mp4" if kind is MediaKind.VIDEO else "audio/mpeg",
        byte_size=len(raw),
        media_kind=kind,
        source="provider",
        source_version="v1",
        license_id="license",
        usage_restriction="research",
        authorized=True,
        input_available_time=available_time,
        width=width,
        height=height,
        duration_ms=duration_ms,
    )


def candidate(
    text: str,
    *,
    start_ms: int = 0,
    end_ms: int = 100,
    bbox: dict[str, int] | None = None,
    frame_identity: str | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": MEDIA_CANDIDATE_SCHEMA_VERSION,
        "text": text,
        "language": "en-US",
        "confidenceBps": 9000,
        "qualityBps": 9000,
        "frameIdentity": frame_identity,
        "segments": [
            {
                "text": text,
                "startOffset": 0,
                "endOffset": len(text),
                "startMs": start_ms,
                "endMs": end_ms,
                "bbox": bbox,
                "confidenceBps": 9000,
                "qualityBps": 9000,
            }
        ],
    }


def request(
    item: MediaManifest,
    *,
    request_id: str = "request-1",
    attempt: int = 0,
    checkpoint: MediaCheckpoint | None = None,
    decision_time: datetime = T1,
    processor_kind: MediaProcessorKind = MediaProcessorKind.ASR,
    profile: ResolvedProfile | None = None,
) -> MediaProcessingRequest:
    selected_profile = fake_media_profile(decision_time) if profile is None else profile
    return MediaProcessingRequest(
        request_id=request_id,
        manifest=item,
        processor_kind=processor_kind,
        resolved_profile=selected_profile,
        decision_time=decision_time,
        event_time=T0,
        publish_time=T0,
        ingest_time=T0 + timedelta(seconds=1),
        processing_time=decision_time,
        attempt=attempt,
        checkpoint=checkpoint,
    )


class FailsCommitOnce(InMemoryMediaEvidenceStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next = True

    def compare_and_append(
        self,
        request: MediaProcessingRequest,
        evidence: MediaTextEvidence,
        expected_previous_revision_id: str | None,
        idempotency_key: str,
    ) -> MediaTextEvidence:
        if self.fail_next:
            self.fail_next = False
            raise MediaStoreTransientError("secret=https://example.invalid/?token=hidden")
        return super().compare_and_append(
            request, evidence, expected_previous_revision_id, idempotency_key
        )


def test_checkpoint_state_machine_retries_new_failed_chunk_and_ready_commit_without_read() -> None:
    item = manifest()
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): b"abcdef"})
    recognizer = FakeMediaRecognizer(
        [
            candidate("a", start_ms=0, end_ms=100),
            MediaTimeoutError("chunk-1"),
            candidate("b", start_ms=333, end_ms=433),
            MediaTimeoutError("chunk-2"),
            candidate("c", start_ms=666, end_ms=766),
        ]
    )
    instance = MediaProcessingConsumer(
        reader=reader,
        recognizer=recognizer,
        store=InMemoryMediaEvidenceStore(),
        policy=MediaPipelinePolicy(chunk_size_bytes=2),
    )
    first = instance.process(request(item))
    assert first.status is MediaProcessStatus.RETRY_SCHEDULED
    assert first.checkpoint is not None
    assert first.checkpoint.phase.value == "RECOGNIZING"
    assert first.checkpoint.next_chunk_index == 1

    second = instance.process(request(item, attempt=1, checkpoint=first.checkpoint))
    assert second.status is MediaProcessStatus.RETRY_SCHEDULED
    assert second.checkpoint is not None
    assert second.checkpoint.phase.value == "RECOGNIZING"
    assert second.checkpoint.next_chunk_index == 2
    assert second.checkpoint.text == "ab"
    assert second.checkpoint.rolling_byte_count == 4

    third = instance.process(request(item, attempt=2, checkpoint=second.checkpoint))
    assert third.status is MediaProcessStatus.COMMITTED
    assert third.evidence is not None and third.evidence.text == "abc"
    assert [call[1] for call in recognizer.calls] == [0, 1, 1, 2, 2]
    assert reader.iteration_indexes == [0, 1, 1, 2, 2]


def test_ready_to_commit_checkpoint_retries_only_cas_and_tamper_fails_closed() -> None:
    item = manifest()
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): b"abcdef"})
    recognizer = FakeMediaRecognizer(
        [
            candidate("a"),
            candidate("b", start_ms=333, end_ms=433),
            candidate("c", start_ms=666, end_ms=766),
        ]
    )
    store = FailsCommitOnce()
    instance = MediaProcessingConsumer(
        reader=reader,
        recognizer=recognizer,
        store=store,
        policy=MediaPipelinePolicy(chunk_size_bytes=2),
    )
    first = instance.process(request(item))
    assert first.status is MediaProcessStatus.RETRY_SCHEDULED
    assert first.failure_reason is MediaFailureReason.STORE_TRANSIENT
    assert first.checkpoint is not None
    assert first.checkpoint.phase.value == "READY_TO_COMMIT"
    assert first.checkpoint.next_chunk_index == 3
    reads = list(reader.iteration_indexes)
    calls = list(recognizer.calls)

    second = instance.process(request(item, attempt=1, checkpoint=first.checkpoint))
    assert second.status is MediaProcessStatus.COMMITTED
    assert reader.iteration_indexes == reads
    assert recognizer.calls == calls

    tampered = replace(first.checkpoint, rolling_sha256="f" * 64)
    with pytest.raises(ValueError, match="checkpoint"):
        instance.process(request(item, attempt=1, checkpoint=tampered))


def _domain_evidence() -> MediaTextEvidence:
    item = manifest(b"test", duration_ms=1000)
    processing = T1
    return MediaTextEvidence(
        evidence_id="evidence-1",
        revision_id="revision-1",
        previous_revision_id=None,
        media_manifest=item,
        processor_kind=MediaProcessorKind.ASR,
        text="test",
        language="en-US",
        segments=(MediaTextSegment("test", 0, 4, 0, 100, None, 9000, 9000),),
        confidence_bps=9000,
        quality_bps=9000,
        event_time=None,
        publish_time=processing,
        ingest_time=processing,
        processing_time=processing,
        provenance=__import__(
            "intelligence_engine.pipelines.media.models", fromlist=["MediaEvidenceProvenance"]
        ).MediaEvidenceProvenance(
            pipeline_version="media-text-pipeline-v1",
            processor_kind=MediaProcessorKind.ASR,
            provider="provider",
            model="model",
            model_version="v1",
            prompt_version="not-applicable",
            configuration_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            recognition_run_id="run-1",
        ),
    )


def test_available_time_is_authoritative_in_schema_dto_and_adapter() -> None:
    original = _domain_evidence()
    payload = original.payload()
    assert parse_media_text_evidence_payload(payload) == original
    assert KolMediaTextEvidence.model_validate(payload).available_time == T1
    for value in ("2026-08-25T00:59:59Z", "2026-08-25T01:01:01Z"):
        bad = {**payload, "availableTime": value}
        with pytest.raises(ValueError, match="available|processing"):
            parse_media_text_evidence_payload(bad)
        with pytest.raises(ValueError, match="available|processing"):
            KolMediaTextEvidence.model_validate(bad)
    with pytest.raises(ValueError):
        parse_media_text_evidence_payload({**payload, "processingTime": "2026-08-25T01:01:00"})


def test_model_upgrade_keeps_stable_evidence_identity_and_appends_revision() -> None:
    root = manifest(b"aa", media_version="media-v1", revision_id="media-r1")
    correction = manifest(
        b"bb",
        media_version="media-v2",
        revision_id="media-r2",
        previous_revision_id="media-r1",
        available_time=T2,
    )
    reader = FakeMediaObjectReader(
        {
            (root.media_id, root.media_version): b"aa",
            (correction.media_id, correction.media_version): b"bb",
        }
    )
    recognizer = FakeMediaRecognizer([candidate("a"), candidate("b")])
    store = InMemoryMediaEvidenceStore()
    instance = MediaProcessingConsumer(reader=reader, recognizer=recognizer, store=store)
    first = instance.process(request(root, profile=fake_media_profile(T1, model_id="model-v1")))
    second = instance.process(
        request(
            correction,
            request_id="correction",
            decision_time=T2,
            profile=fake_media_profile(T2, model_id="model-v2"),
        )
    )
    assert first.evidence is not None and second.evidence is not None
    assert first.evidence.evidence_id == second.evidence.evidence_id
    assert second.evidence.previous_revision_id == first.evidence.revision_id
    assert store.as_of(first.evidence.evidence_id, T1) == first.evidence
    assert store.as_of(first.evidence.evidence_id, T2) == second.evidence
    with pytest.raises(ValueError, match="timezone-aware"):
        store.as_of(first.evidence.evidence_id, datetime(2026, 8, 25, 1, 1))


def _video_chunks(frame_identity: str | None, raw: bytes = b"frameframe") -> tuple[MediaChunk, ...]:
    return (
        MediaChunk(
            0,
            b"frame",
            0,
            50,
            frame_identity=frame_identity,
            width=100,
            height=100,
            bbox_context=MediaBoundingBox(50, 50, 20, 20),
        ),
        MediaChunk(
            1,
            b"frame",
            50,
            100,
            frame_identity=frame_identity,
            width=100,
            height=100,
            bbox_context=MediaBoundingBox(50, 50, 20, 20),
        ),
    )


def test_video_ocr_reader_frame_dedup_and_crop_local_bbox_conversion() -> None:
    frame_identity = hashlib.sha256(b"frame").hexdigest()
    item = manifest(
        b"frameframe",
        kind=MediaKind.VIDEO,
        width=100,
        height=100,
        duration_ms=100,
    )
    reader = FakeMediaObjectReader(
        {(item.media_id, item.media_version): b"frameframe"},
        chunk_specs={(item.media_id, item.media_version): _video_chunks(frame_identity)},
    )
    recognizer = FakeMediaRecognizer(
        [candidate("first", end_ms=10, bbox={"x": 0, "y": 0, "width": 10, "height": 10})]
    )
    instance = MediaProcessingConsumer(
        reader=reader,
        recognizer=recognizer,
        store=InMemoryMediaEvidenceStore(),
    )
    result = instance.process(request(item, processor_kind=MediaProcessorKind.OCR))
    assert result.status is MediaProcessStatus.COMMITTED
    assert len(recognizer.calls) == 1
    assert result.evidence is not None
    assert result.evidence.segments[0].bbox == MediaBoundingBox(50, 50, 10, 10)
    assert result.evidence.segments[0].frame_identity == frame_identity


def test_video_ocr_missing_reader_frame_identity_and_bbox_escape_are_rejected() -> None:
    item = manifest(b"frame", kind=MediaKind.VIDEO, width=100, height=100, duration_ms=100)
    missing_reader = FakeMediaObjectReader(
        {(item.media_id, item.media_version): b"frame"},
        chunk_specs={(item.media_id, item.media_version): _video_chunks(None)[:1]},
    )
    recognizer = FakeMediaRecognizer(
        [candidate("text", end_ms=10, bbox={"x": 0, "y": 0, "width": 10, "height": 10})]
    )
    sink = InMemoryMediaAuditSink()
    result = MediaProcessingConsumer(
        reader=missing_reader,
        recognizer=recognizer,
        store=InMemoryMediaEvidenceStore(),
        audit_sink=sink,
    ).process(request(item, processor_kind=MediaProcessorKind.OCR))
    assert result.failure_reason is MediaFailureReason.INVALID_CANDIDATE
    assert recognizer.calls == []
    assert sink.records[-1].status is MediaAuditStatus.INVALID_CANDIDATE

    escape_item = manifest(b"frame", kind=MediaKind.VIDEO, width=100, height=100, duration_ms=100)
    escape_reader = FakeMediaObjectReader(
        {(escape_item.media_id, escape_item.media_version): b"frame"},
        chunk_specs={
            (escape_item.media_id, escape_item.media_version): (
                replace(_video_chunks(hashlib.sha256(b"frame").hexdigest())[0], data=b"frame"),
            )
        },
    )
    escape = MediaProcessingConsumer(
        reader=escape_reader,
        recognizer=FakeMediaRecognizer(
            [candidate("text", end_ms=10, bbox={"x": 15, "y": 0, "width": 10, "height": 10})]
        ),
        store=InMemoryMediaEvidenceStore(),
    ).process(request(escape_item, processor_kind=MediaProcessorKind.OCR))
    assert escape.failure_reason is MediaFailureReason.INVALID_CANDIDATE


def test_audit_uses_only_safe_fingerprints_and_never_exception_or_revision_text() -> None:
    raw = b"expected"
    item = manifest(raw, revision_id="https://example.invalid/path?sig=secret-token")
    sink = InMemoryMediaAuditSink()
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): b"wrong!!!"})
    result = MediaProcessingConsumer(
        reader=reader,
        recognizer=FakeMediaRecognizer([]),
        store=InMemoryMediaEvidenceStore(),
        audit_sink=sink,
    ).process(request(item, request_id="https://example.invalid/?token=secret"))
    assert result.failure_reason is MediaFailureReason.CHECKSUM_MISMATCH
    record = sink.records[-1]
    serialized = f"{record!r} {record.payload()}"
    assert "secret-token" not in serialized
    assert "https://" not in serialized
    assert "manifestRevisionId" not in record.payload()
    assert "manifestRevisionFingerprint" in record.payload()
    assert len(record.manifest_revision_fingerprint) == 64
    assert record.reason is MediaAuditReason.CHECKSUM_MISMATCH
