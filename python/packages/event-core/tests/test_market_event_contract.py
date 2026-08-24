"""Generated DTO and MarketEvent domain-boundary tests (P3-N05)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from ashare_contracts import MarketEvent as MarketEventDTO
from event_core.models import (
    MARKET_EVENT_SCHEMA_VERSION,
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
    from_contract,
    parse_market_event_payload,
    to_contract,
)
from pydantic import ValidationError

type JSONObject = dict[str, object]


def make_event() -> MarketEvent:
    publish_time = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    return MarketEvent(
        event_type=MarketEventType.CORPORATE,
        headline="某公司发布重大事项公告",
        summary="公司公告披露一项可追溯的重大事项。",
        occur_time=publish_time,
        publish_time=publish_time,
        available_time=datetime(2026, 8, 24, 1, 3, tzinfo=UTC),
        instrument_ids=("600519.SH",),
        sector_ids=("sector-food",),
        evidence=(
            EventEvidence(
                evidence_id="evidence-1",
                content_record_id="raw-record-1",
                content_version_id="a" * 64,
                source_id="cninfo",
                source_version="v1",
                available_time=publish_time,
                start_offset=0,
                end_offset=len("公司发布重大事项公告"),
                excerpt="公司发布重大事项公告",
            ),
        ),
        model_provenance=ModelProvenance(
            producer_type=ProducerType.MODEL,
            provider="provider-a",
            model_id="event-extractor",
            model_version="model-v1",
            prompt_version="prompt-v1",
            output_schema_version=MARKET_EVENT_SCHEMA_VERSION,
            configuration_fingerprint="b" * 64,
            extraction_run_id="run-1",
            processing_time=datetime(2026, 8, 24, 1, 2, tzinfo=UTC),
        ),
        confidence_bps=8500,
    )


def wire() -> JSONObject:
    return cast(JSONObject, to_contract(make_event()).model_dump(by_alias=True, mode="json"))


def test_domain_dto_domain_roundtrip_is_lossless() -> None:
    event = make_event()
    assert from_contract(to_contract(event)) == event


def test_untrusted_payload_is_structurally_validated() -> None:
    assert parse_market_event_payload(wire()) == make_event()
    malformed = wire()
    malformed["unexpected"] = "not allowed"
    with pytest.raises(ValidationError):
        parse_market_event_payload(malformed)


def test_forged_event_id_is_rejected() -> None:
    payload = wire()
    payload["eventId"] = "0" * 64
    with pytest.raises(ValueError, match="event_id mismatch"):
        parse_market_event_payload(payload)


def test_missing_evidence_is_rejected() -> None:
    payload = wire()
    payload["evidence"] = []
    with pytest.raises(ValidationError):
        MarketEventDTO.model_validate(payload)


def test_float_confidence_and_vendor_symbol_are_rejected() -> None:
    confidence = wire()
    confidence["confidenceBps"] = 8500.5
    with pytest.raises(ValidationError):
        MarketEventDTO.model_validate(confidence)

    symbol = wire()
    symbol["instrumentIds"] = ["SH.600519"]
    with pytest.raises(ValidationError):
        MarketEventDTO.model_validate(symbol)


def test_naive_time_is_rejected() -> None:
    payload = wire()
    payload["availableTime"] = "2026-08-24T01:03:00"
    with pytest.raises(ValidationError):
        MarketEventDTO.model_validate(payload)


def test_cross_field_evidence_time_is_checked_by_domain() -> None:
    payload = wire()
    evidence = cast(list[JSONObject], payload["evidence"])
    evidence[0]["availableTime"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="evidence.available_time"):
        parse_market_event_payload(payload)
