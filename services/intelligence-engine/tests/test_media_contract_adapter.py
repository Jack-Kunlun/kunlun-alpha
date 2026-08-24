"""Generated DTO and runtime adapter parity for P4-N07."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from intelligence_engine.pipelines.media import (
    MediaKind,
    MediaProcessorKind,
    parse_media_text_evidence_payload,
    to_media_text_evidence_contract,
)
from intelligence_engine.pipelines.media.fake import fake_media_profile
from intelligence_engine.pipelines.media.models import (
    MediaEvidenceProvenance,
    MediaManifest,
    MediaTextEvidence,
    MediaTextSegment,
)


def evidence() -> MediaTextEvidence:
    manifest = MediaManifest(
        content_id="content-1",
        content_version="content-version-1",
        media_id="media-1",
        media_version="media-version-1",
        revision_id="media-revision-1",
        previous_revision_id=None,
        raw_sha256="a" * 64,
        mime_type="audio/mpeg",
        byte_size=4,
        media_kind=MediaKind.AUDIO,
        source="provider",
        source_version="v1",
        license_id="license",
        usage_restriction="research",
        authorized=True,
        input_available_time=datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
        duration_ms=1000,
    )
    processing = datetime(2026, 8, 25, 1, 1, tzinfo=UTC)
    return MediaTextEvidence(
        evidence_id="evidence-1",
        revision_id="evidence-revision-1",
        previous_revision_id=None,
        media_manifest=manifest,
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
        provenance=MediaEvidenceProvenance(
            pipeline_version="media-text-pipeline-v1",
            processor_kind=MediaProcessorKind.ASR,
            provider="provider",
            model="model",
            model_version="v1",
            prompt_version="not-applicable",
            configuration_fingerprint=fake_media_profile(processing).configuration_fingerprint,
            policy_fingerprint="c" * 64,
            recognition_run_id="run-1",
        ),
    )


def test_generated_contract_round_trip_and_forbidden_claim_fields() -> None:
    original = evidence()
    contract = to_media_text_evidence_contract(original)
    payload = contract.model_dump(by_alias=True, mode="json")
    assert parse_media_text_evidence_payload(payload) == original
    assert "direction" not in payload
    assert "instrumentId" not in payload
    with pytest.raises(ValueError):
        parse_media_text_evidence_payload({**payload, "unknown": True})


def test_generated_dto_rejects_invalid_tombstone_metadata() -> None:
    original = to_media_text_evidence_contract(evidence())
    payload = original.model_dump(by_alias=True, mode="json")
    invalid = {**payload, "deleted": True, "deletedAt": None, "deletionReason": None}
    with pytest.raises(ValueError, match="deleted"):
        parse_media_text_evidence_payload(invalid)
