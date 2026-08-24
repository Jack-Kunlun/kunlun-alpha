"""P4-N07 Terra repair probes. These are intentionally stricter than the first-round tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashare_contracts.kol_media_text_evidence import KolMediaTextEvidence
from intelligence_engine.pipelines.media import (
    MEDIA_CANDIDATE_SCHEMA_VERSION,
    MediaAuditReason,
    MediaAuditStatus,
    MediaCheckpoint,
    MediaFailureReason,
    MediaKind,
    MediaPipelinePolicy,
    MediaProcessingConsumer,
    MediaProcessingRequest,
    MediaProcessorKind,
    MediaProcessStatus,
    MediaTimeoutError,
    parse_media_recognition_candidate,
)
from intelligence_engine.pipelines.media.candidate import MediaRecognitionCandidate
from intelligence_engine.pipelines.media.fake import (
    FakeMediaObjectReader,
    FakeMediaRecognizer,
    InMemoryMediaAuditSink,
    InMemoryMediaEvidenceStore,
    fake_media_profile,
)
from intelligence_engine.pipelines.media.models import MediaManifest

T0 = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)
T3 = T0 + timedelta(minutes=3)


def manifest(
    raw: bytes = b"media-bytes",
    *,
    media_version: str = "media-version-1",
    revision_id: str = "media-revision-1",
    previous_revision_id: str | None = None,
    available_time: datetime = T0,
    deleted: bool = False,
) -> MediaManifest:
    return MediaManifest(
        content_id="content-1",
        content_version="content-version-1",
        media_id="media-1",
        media_version=media_version,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        mime_type="audio/mpeg",
        byte_size=len(raw),
        media_kind=MediaKind.AUDIO,
        source="media-provider",
        source_version="provider-v1",
        license_id="license-v1",
        usage_restriction="research-only",
        authorized=True,
        input_available_time=available_time,
        duration_ms=1000,
        deleted=deleted,
        deleted_at=T3 if deleted else None,
        deletion_reason="withdrawn" if deleted else None,
    )


def candidate(
    text: str,
    *,
    frame_identity: str | None = None,
    start_ms: int = 0,
    end_ms: int = 100,
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
                "bbox": None,
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
) -> MediaProcessingRequest:
    return MediaProcessingRequest(
        request_id=request_id,
        manifest=item,
        processor_kind=MediaProcessorKind.ASR,
        resolved_profile=fake_media_profile(decision_time),
        decision_time=decision_time,
        event_time=T0,
        publish_time=T0,
        ingest_time=T0 + timedelta(seconds=1),
        processing_time=T1,
        attempt=attempt,
        checkpoint=checkpoint,
    )


def test_stream_resume_starts_at_failed_chunk_and_rejects_stale_checkpoint() -> None:
    raw = b"abcd"
    item = manifest(raw)
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): raw})
    recognizer = FakeMediaRecognizer(
        [
            candidate("a", frame_identity="a" * 64),
            MediaTimeoutError("timeout"),
            candidate("b", frame_identity="b" * 64, start_ms=500, end_ms=510),
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
    resumed = instance.process(request(item, attempt=1, checkpoint=first.checkpoint))
    assert resumed.status is MediaProcessStatus.COMMITTED
    assert resumed.evidence is not None and resumed.evidence.text == "ab"
    assert [call[1] for call in recognizer.calls] == [0, 1, 1]
    assert reader.iteration_indexes == [0, 1, 1]
    with pytest.raises(ValueError, match="checkpoint"):
        instance.process(
            request(
                item,
                attempt=1,
                checkpoint=replace(first.checkpoint, policy_fingerprint="f" * 64),
            )
        )


def test_idempotency_claim_precedes_read_and_conflicts_do_not_overwrite() -> None:
    raw = b"media-bytes"
    item = manifest(raw)
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): raw})
    recognizer = FakeMediaRecognizer([candidate("x")])
    store = InMemoryMediaEvidenceStore()
    instance = MediaProcessingConsumer(reader=reader, recognizer=recognizer, store=store)
    assert instance.process(request(item)).status is MediaProcessStatus.COMMITTED
    reads_after_commit = len(reader.reads)
    calls_after_commit = len(recognizer.calls)
    assert instance.process(request(item)).status is MediaProcessStatus.ALREADY_COMMITTED
    assert len(reader.reads) == reads_after_commit
    assert len(recognizer.calls) == calls_after_commit
    with pytest.raises(ValueError, match="conflict"):
        instance.process(request(replace(item, media_version="other")))
    assert len(reader.reads) == reads_after_commit
    assert len(recognizer.calls) == calls_after_commit


def test_candidate_object_and_mapping_share_one_strict_parser() -> None:
    item = manifest()
    valid = candidate("x")
    parsed = parse_media_recognition_candidate(
        valid,
        manifest=item,
        processor_kind=MediaProcessorKind.ASR,
    )
    assert parsed.text == "x"
    with pytest.raises((TypeError, ValueError)):
        MediaRecognitionCandidate(
            MEDIA_CANDIDATE_SCHEMA_VERSION,
            "x",
            "en-US",
            True,
            9000,
            parsed.segments,
        )
    for invalid in (
        {**valid, "schemaVersion": "candidate-v2"},
        {**valid, "confidenceBps": 9000.0},
        {**valid, "qualityBps": True},
        {**valid, "unexpected": "field"},
    ):
        with pytest.raises((TypeError, ValueError)):
            parse_media_recognition_candidate(
                invalid,
                manifest=item,
                processor_kind=MediaProcessorKind.ASR,
            )
    contract_payload: dict[str, object] = {
        "schemaVersion": "kol-media-text-evidence-v1",
        "evidenceId": "e",
        "revisionId": "r",
        "previousRevisionId": None,
        "mediaManifest": {},
    }
    with pytest.raises(ValueError):
        KolMediaTextEvidence.model_validate({**contract_payload, "confidenceBps": 9000.0})


def test_revision_chain_and_as_of_tombstone_are_append_only() -> None:
    raw = b"media-bytes"
    root = manifest(raw)
    correction = manifest(
        raw,
        media_version="media-version-2",
        revision_id="media-revision-2",
        previous_revision_id="media-revision-1",
        available_time=T2,
    )
    withdrawn = manifest(
        raw,
        media_version="media-version-3",
        revision_id="media-revision-3",
        previous_revision_id="media-revision-2",
        available_time=T3,
        deleted=True,
    )
    reader = FakeMediaObjectReader(
        {
            (root.media_id, root.media_version): raw,
            (correction.media_id, correction.media_version): raw,
        }
    )
    recognizer = FakeMediaRecognizer([candidate("a"), candidate("b")])
    store = InMemoryMediaEvidenceStore()
    instance = MediaProcessingConsumer(reader=reader, recognizer=recognizer, store=store)
    first = instance.process(request(root, request_id="root"))
    second = instance.process(request(correction, request_id="correction", decision_time=T2))
    assert first.evidence is not None and second.evidence is not None
    assert first.evidence.evidence_id == second.evidence.evidence_id
    assert second.evidence.previous_revision_id == first.evidence.revision_id
    assert store.as_of(first.evidence.evidence_id, T1) == first.evidence
    tombstone = instance.process(request(withdrawn, request_id="withdrawn", decision_time=T3))
    assert tombstone.status is MediaProcessStatus.TERMINAL
    assert tombstone.failure_reason is MediaFailureReason.DELETED
    latest = store.as_of(first.evidence.evidence_id, T3)
    assert latest is not None and latest.deleted is True
    assert store.as_of(first.evidence.evidence_id, T2) == second.evidence


def test_stream_budgets_and_authoritative_chunk_timeline_fail_closed() -> None:
    raw = b"abcd"
    item = manifest(raw)
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): raw})
    recognizer = FakeMediaRecognizer([candidate("x")])
    instance = MediaProcessingConsumer(
        reader=reader,
        recognizer=recognizer,
        store=InMemoryMediaEvidenceStore(),
        policy=MediaPipelinePolicy(max_bytes=3),
    )
    result = instance.process(request(item))
    assert result.failure_reason is MediaFailureReason.BUDGET_EXCEEDED
    assert reader.iteration_indexes == []
    assert recognizer.calls == []
    assert (
        MediaPipelinePolicy(max_bytes=3).fingerprint != MediaPipelinePolicy(max_bytes=4).fingerprint
    )


def test_audit_sink_is_append_only_and_privacy_safe() -> None:
    raw = b"expected"
    item = manifest(raw)
    sink = InMemoryMediaAuditSink()
    reader = FakeMediaObjectReader({(item.media_id, item.media_version): b"wrong"})
    instance = MediaProcessingConsumer(
        reader=reader,
        recognizer=FakeMediaRecognizer([candidate("secret transcript")]),
        store=InMemoryMediaEvidenceStore(),
        audit_sink=sink,
    )
    result = instance.process(request(item))
    assert result.failure_reason is MediaFailureReason.CHECKSUM_MISMATCH
    assert sink.records[-1].status is MediaAuditStatus.CHECKSUM_MISMATCH
    assert sink.records[-1].reason is MediaAuditReason.CHECKSUM_MISMATCH
    payload = sink.records[-1].payload()
    assert "secret transcript" not in str(payload)
    assert "wrong" not in str(payload)
    assert "rawBytes" not in payload
