"""Validated wire boundary for the MarketEvent V1 contract."""

from __future__ import annotations

from ashare_contracts import MarketEvent as MarketEventDTO

from event_core.models.market_event import (
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
)


def from_contract(dto: MarketEventDTO) -> MarketEvent:
    """Convert a generated DTO into the authoritative domain and verify its id."""
    if type(dto) is not MarketEventDTO:
        raise TypeError("dto must be an ashare_contracts.MarketEvent")
    provenance = dto.model_provenance
    domain = MarketEvent(
        schema_version=dto.schema_version.value,
        event_type=MarketEventType(dto.event_type.value),
        headline=dto.headline,
        summary=dto.summary,
        occur_time=dto.occur_time,
        publish_time=dto.publish_time,
        available_time=dto.available_time,
        instrument_ids=tuple(instrument_id.root for instrument_id in dto.instrument_ids),
        sector_ids=tuple(sector_id.root for sector_id in dto.sector_ids),
        evidence=tuple(
            EventEvidence(
                evidence_id=item.evidence_id,
                content_record_id=item.content_record_id,
                content_version_id=item.content_version_id,
                source_id=item.source_id,
                source_version=item.source_version,
                available_time=item.available_time,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                excerpt=item.excerpt,
            )
            for item in dto.evidence
        ),
        model_provenance=ModelProvenance(
            producer_type=ProducerType(provenance.producer_type.value),
            provider=provenance.provider,
            model_id=provenance.model_id,
            model_version=provenance.model_version,
            prompt_version=provenance.prompt_version,
            output_schema_version=provenance.output_schema_version.value,
            configuration_fingerprint=provenance.configuration_fingerprint,
            extraction_run_id=provenance.extraction_run_id,
            processing_time=provenance.processing_time,
        ),
        confidence_bps=dto.confidence_bps,
    )
    if domain.event_id != dto.event_id:
        raise ValueError("event_id mismatch: identity does not match immutable event facts")
    return domain


def to_contract(event: MarketEvent) -> MarketEventDTO:
    """Serialize a trusted domain event through the generated DTO boundary."""
    if type(event) is not MarketEvent:
        raise TypeError("event must be a MarketEvent")
    return MarketEventDTO.model_validate(
        {
            "schemaVersion": event.schema_version,
            "eventId": event.event_id,
            "eventType": event.event_type.value,
            "headline": event.headline,
            "summary": event.summary,
            "occurTime": event.occur_time,
            "publishTime": event.publish_time,
            "availableTime": event.available_time,
            "instrumentIds": list(event.instrument_ids),
            "sectorIds": list(event.sector_ids),
            "evidence": [
                {
                    "evidenceId": item.evidence_id,
                    "contentRecordId": item.content_record_id,
                    "contentVersionId": item.content_version_id,
                    "sourceId": item.source_id,
                    "sourceVersion": item.source_version,
                    "availableTime": item.available_time,
                    "startOffset": item.start_offset,
                    "endOffset": item.end_offset,
                    "excerpt": item.excerpt,
                }
                for item in event.evidence
            ],
            "modelProvenance": {
                "producerType": event.model_provenance.producer_type.value,
                "provider": event.model_provenance.provider,
                "modelId": event.model_provenance.model_id,
                "modelVersion": event.model_provenance.model_version,
                "promptVersion": event.model_provenance.prompt_version,
                "outputSchemaVersion": event.model_provenance.output_schema_version,
                "configurationFingerprint": event.model_provenance.configuration_fingerprint,
                "extractionRunId": event.model_provenance.extraction_run_id,
                "processingTime": event.model_provenance.processing_time,
            },
            "confidenceBps": event.confidence_bps,
        }
    )


def parse_market_event_payload(payload: object) -> MarketEvent:
    """Validate an untrusted model/provider payload before it enters the domain."""
    return from_contract(MarketEventDTO.model_validate(payload))


__all__ = ["from_contract", "parse_market_event_payload", "to_contract"]
