# MarketEvent V1

`MarketEvent` is the immutable P3-N05 event contract. A persisted event always
contains at least one exact `RawContent` evidence span and the complete model,
Prompt, output-Schema, configuration, run, and processing-time identity that
produced the conclusion.

## Invariants

- `publish_time <= available_time`; downstream decisions may only use an event
  when `available_time <= decision_time`.
- Every evidence reference identifies a `RawContent` record/version, source
  version, original half-open span, excerpt, and evidence availability time.
- Evidence cannot become available after the event itself.
- `instrument_ids` use canonical forms such as `600519.SH`; vendor symbols are
  rejected.
- Confidence is integer basis points in `[0, 10000]`.
- `event_id` is derived from every immutable event, evidence, and producer fact.
  Callers never supply or overwrite it in the domain model.
- Untrusted provider/model JSON must enter through
  `parse_market_event_payload`; a generated DTO validates the structure before
  the domain checks time ordering, evidence, and identity.

## Construction example

```python
from datetime import UTC, datetime

from event_core.models import (
    EventEvidence,
    MarketEvent,
    MarketEventType,
    ModelProvenance,
    ProducerType,
    to_contract,
)

published = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
event = MarketEvent(
    event_type=MarketEventType.CORPORATE,
    headline="A company disclosed a material event",
    summary="The conclusion is backed by the referenced source span.",
    occur_time=published,
    publish_time=published,
    available_time=datetime(2026, 8, 24, 1, 3, tzinfo=UTC),
    instrument_ids=("600519.SH",),
    sector_ids=("sector-food",),
    evidence=(
        EventEvidence(
            evidence_id="source-evidence-1",
            content_record_id="raw-record-1",
            content_version_id="a" * 64,
            source_id="cninfo",
            source_version="v1",
            available_time=published,
            start_offset=0,
            end_offset=10,
            excerpt="0123456789",
        ),
    ),
    model_provenance=ModelProvenance(
        producer_type=ProducerType.MODEL,
        provider="provider-a",
        model_id="event-extractor",
        model_version="model-v1",
        prompt_version="prompt-v1",
        output_schema_version="market-event-v1",
        configuration_fingerprint="b" * 64,
        extraction_run_id="run-1",
        processing_time=datetime(2026, 8, 24, 1, 2, tzinfo=UTC),
    ),
    confidence_bps=8500,
)

wire_payload = to_contract(event).model_dump(by_alias=True, mode="json")
```

Changing this contract requires a new Schema version and compatibility notes;
historical V1 events are never rewritten under a new model or Prompt version.
