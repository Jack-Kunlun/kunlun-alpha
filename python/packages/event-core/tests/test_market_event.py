"""MarketEvent domain invariants (P3-N05)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from event_core.models import (
    MARKET_EVENT_SCHEMA_VERSION,
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
)

PUBLISH = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
PROCESSING = datetime(2026, 8, 24, 1, 2, tzinfo=UTC)
AVAILABLE = datetime(2026, 8, 24, 1, 3, tzinfo=UTC)


def make_evidence(
    evidence_id: str = "evidence-1", *, start: int = 0, excerpt: str = "公司发布重大事项公告"
) -> EventEvidence:
    return EventEvidence(
        evidence_id=evidence_id,
        content_record_id="raw-record-1",
        content_version_id="a" * 64,
        source_id="cninfo",
        source_version="v1",
        available_time=PUBLISH,
        start_offset=start,
        end_offset=start + len(excerpt),
        excerpt=excerpt,
    )


def make_provenance() -> ModelProvenance:
    return ModelProvenance(
        producer_type=ProducerType.MODEL,
        provider="provider-a",
        model_id="event-extractor",
        model_version="model-v1",
        prompt_version="prompt-v1",
        output_schema_version=MARKET_EVENT_SCHEMA_VERSION,
        configuration_fingerprint="b" * 64,
        extraction_run_id="run-1",
        processing_time=PROCESSING,
    )


def make_event() -> MarketEvent:
    return MarketEvent(
        event_type=MarketEventType.CORPORATE,
        headline="某公司发布重大事项公告",
        summary="公司公告披露一项可追溯的重大事项。",
        occur_time=PUBLISH,
        publish_time=PUBLISH,
        available_time=AVAILABLE,
        instrument_ids=("600519.SH",),
        sector_ids=("sector-food",),
        evidence=(make_evidence(),),
        model_provenance=make_provenance(),
        confidence_bps=8500,
    )


def test_event_id_is_stable_sha256() -> None:
    first = make_event()
    second = make_event()
    assert first.event_id == second.event_id
    assert len(first.event_id) == 64
    assert all(character in "0123456789abcdef" for character in first.event_id)


def test_identity_is_order_independent_for_set_like_fields() -> None:
    first = dataclasses.replace(
        make_event(),
        instrument_ids=("600519.SH", "000001.SZ"),
        sector_ids=("sector-food", "sector-finance"),
        evidence=(make_evidence("evidence-2", start=30), make_evidence()),
    )
    second = dataclasses.replace(
        make_event(),
        instrument_ids=("000001.SZ", "600519.SH"),
        sector_ids=("sector-finance", "sector-food"),
        evidence=(make_evidence(), make_evidence("evidence-2", start=30)),
    )
    assert first == second
    assert first.event_id == second.event_id


def test_identity_binds_evidence_and_model_versions() -> None:
    base = make_event()
    changed_prompt = dataclasses.replace(
        base,
        model_provenance=dataclasses.replace(base.model_provenance, prompt_version="prompt-v2"),
    )
    changed_evidence = dataclasses.replace(
        base, evidence=(make_evidence(excerpt="不同的原文证据"),)
    )
    assert changed_prompt.event_id != base.event_id
    assert changed_evidence.event_id != base.event_id


def test_event_requires_source_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        dataclasses.replace(make_event(), evidence=())


def test_evidence_span_must_match_excerpt() -> None:
    with pytest.raises(ValueError, match="span length"):
        dataclasses.replace(make_evidence(), end_offset=999)


def test_future_evidence_is_rejected() -> None:
    future = dataclasses.replace(make_evidence(), available_time=datetime(2027, 1, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="evidence.available_time"):
        dataclasses.replace(make_event(), evidence=(future,))


def test_publish_and_processing_cannot_be_after_availability() -> None:
    with pytest.raises(ValueError, match="publish_time"):
        dataclasses.replace(make_event(), publish_time=datetime(2027, 1, 1, tzinfo=UTC))
    future_model = dataclasses.replace(
        make_provenance(), processing_time=datetime(2027, 1, 1, tzinfo=UTC)
    )
    with pytest.raises(ValueError, match="processing_time"):
        dataclasses.replace(make_event(), model_provenance=future_model)


def test_planned_event_may_occur_after_publication() -> None:
    planned = dataclasses.replace(make_event(), occur_time=datetime(2027, 1, 1, tzinfo=UTC))
    assert planned.occur_time > planned.publish_time


def test_noncanonical_or_duplicate_instruments_are_rejected() -> None:
    with pytest.raises(ValueError, match="canonical instrument"):
        dataclasses.replace(make_event(), instrument_ids=("SH.600519",))
    with pytest.raises(ValueError, match="duplicates"):
        dataclasses.replace(make_event(), instrument_ids=("600519.SH", "600519.SH"))


def test_confidence_is_strict_integer_basis_points() -> None:
    with pytest.raises(TypeError, match="basis points"):
        dataclasses.replace(make_event(), confidence_bps=True)
    with pytest.raises(ValueError, match="10000"):
        dataclasses.replace(make_event(), confidence_bps=10001)


def test_event_is_immutable() -> None:
    event = make_event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.headline = "tampered"  # type: ignore[misc]
