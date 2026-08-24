"""Generated DTO adapter for the media evidence public contract."""

from __future__ import annotations

from collections.abc import Mapping

from ashare_contracts.kol_media_text_evidence import (
    KolMediaTextEvidence,
)
from ashare_contracts.kol_media_text_evidence import (
    MediaBoundingBox as ContractBoundingBox,
)

from .models import (
    MediaBoundingBox,
    MediaEvidenceProvenance,
    MediaKind,
    MediaManifest,
    MediaProcessorKind,
    MediaTextEvidence,
    MediaTextSegment,
)


def to_media_text_evidence_contract(evidence: MediaTextEvidence) -> KolMediaTextEvidence:
    return KolMediaTextEvidence.model_validate(evidence.payload())


def parse_media_text_evidence_payload(payload: Mapping[str, object]) -> MediaTextEvidence:
    dto = KolMediaTextEvidence.model_validate(payload)
    manifest = dto.media_manifest
    time_values = (
        manifest.input_available_time,
        dto.processing_time,
        dto.available_time,
    )
    if any(value.tzinfo is None or value.utcoffset() is None for value in time_values):
        raise ValueError("media evidence times must be timezone-aware")
    if dto.available_time != max(manifest.input_available_time, dto.processing_time):
        raise ValueError("availableTime must equal max(inputAvailableTime, processingTime)")
    domain_manifest = MediaManifest(
        content_id=manifest.content_id,
        content_version=manifest.content_version,
        media_id=manifest.media_id,
        media_version=manifest.media_version,
        revision_id=manifest.revision_id,
        previous_revision_id=manifest.previous_revision_id,
        raw_sha256=manifest.raw_sha256,
        mime_type=manifest.mime_type,
        byte_size=manifest.byte_size,
        media_kind=MediaKind(manifest.media_kind.value),
        source=manifest.source,
        source_version=manifest.source_version,
        license_id=manifest.license_id,
        usage_restriction=manifest.usage_restriction,
        authorized=manifest.authorized,
        input_available_time=manifest.input_available_time,
        width=manifest.width,
        height=manifest.height,
        duration_ms=manifest.duration_ms,
        deleted=manifest.deleted,
        deleted_at=manifest.deleted_at,
        deletion_reason=manifest.deletion_reason,
    )
    segments: list[MediaTextSegment] = []
    for segment in dto.segments:
        bbox: MediaBoundingBox | None = None
        contract_bbox: ContractBoundingBox | None = segment.bbox
        if contract_bbox is not None:
            bbox = MediaBoundingBox(
                contract_bbox.x,
                contract_bbox.y,
                contract_bbox.width,
                contract_bbox.height,
            )
        segments.append(
            MediaTextSegment(
                segment.text,
                segment.start_offset,
                segment.end_offset,
                segment.start_ms,
                segment.end_ms,
                bbox,
                segment.confidence_bps,
                segment.quality_bps,
                segment.frame_identity,
            )
        )
    return MediaTextEvidence(
        evidence_id=dto.evidence_id,
        revision_id=dto.revision_id,
        previous_revision_id=dto.previous_revision_id,
        media_manifest=domain_manifest,
        processor_kind=MediaProcessorKind(dto.processor_kind.value),
        text=dto.text,
        language=dto.language,
        segments=tuple(segments),
        confidence_bps=dto.confidence_bps,
        quality_bps=dto.quality_bps,
        event_time=dto.event_time,
        publish_time=dto.publish_time,
        ingest_time=dto.ingest_time,
        processing_time=dto.processing_time,
        provenance=MediaEvidenceProvenance(
            pipeline_version=dto.provenance.pipeline_version,
            processor_kind=MediaProcessorKind(dto.provenance.processor_kind.value),
            provider=dto.provenance.provider,
            model=dto.provenance.model,
            model_version=dto.provenance.model_version,
            prompt_version=dto.provenance.prompt_version,
            configuration_fingerprint=dto.provenance.configuration_fingerprint,
            policy_fingerprint=dto.provenance.policy_fingerprint,
            recognition_run_id=dto.provenance.recognition_run_id,
        ),
        deleted=dto.deleted,
        deleted_at=dto.deleted_at,
        deletion_reason=dto.deletion_reason,
    )


__all__ = ["parse_media_text_evidence_payload", "to_media_text_evidence_contract"]
