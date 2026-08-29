"""Bar normalization + validation pipeline.

Combines normalization, per-bar validation and sequence checks into one pass:
accepted bars are returned, abnormal records go to the rejection zone, and
every issue is surfaced as a quality event (nothing is silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass

from market_core.models.validators import Bar
from market_core.validation import QualityEvent, validate_bar_with_event

from data_worker.normalize.normalizer import MissingFieldError, normalize_bar
from data_worker.normalize.rejection import RejectionZone


@dataclass(frozen=True)
class BarPipelineResult:
    """Result of running the bar pipeline over a batch of raw records."""

    accepted: list[Bar]
    rejection_zone: RejectionZone
    events: list[QualityEvent]


def process_bars(records: list[dict[str, object]]) -> BarPipelineResult:
    """Normalize, validate and sequence-check a batch of raw bar records."""
    rejection = RejectionZone()
    accepted: list[Bar] = []
    accepted_records: list[dict[str, object]] = []
    events: list[QualityEvent] = []

    for record in records:
        try:
            bar = normalize_bar(record)
        except (MissingFieldError, KeyError, TypeError, ValueError) as exc:
            rejection.add(record, f"normalization: {exc}")
            events.append(
                QualityEvent(
                    kind="MISSING_FIELD",
                    unified_code=str(record.get("unifiedCode", "")),
                    timestamp=str(record.get("timestamp", "")),
                    detail=str(exc),
                )
            )
            continue

        result, bar_events = validate_bar_with_event(bar)
        if not result.valid:
            rejection.add(record, f"validation: {'; '.join(result.errors)}")
            events.extend(bar_events)
            continue

        accepted.append(bar)
        accepted_records.append(record)

    seen_identities: set[tuple[str, str, str, str, str]] = set()
    previous: Bar | None = None
    for bar, record in zip(accepted, accepted_records, strict=True):
        identity = (
            bar.unified_code,
            bar.interval,
            bar.timestamp,
            bar.session,
            bar.price_type,
        )
        if identity in seen_identities:
            rejection.add(record, f"sequence: duplicate bar identity {bar.timestamp}")
            events.append(
                QualityEvent(
                    kind="DUPLICATE",
                    unified_code=bar.unified_code,
                    timestamp=bar.timestamp,
                    detail=f"duplicate bar identity at {bar.timestamp}",
                )
            )
        elif previous is not None and bar.timestamp == previous.timestamp:
            rejection.add(record, f"sequence: duplicate timestamp {bar.timestamp}")
            events.append(
                QualityEvent(
                    kind="DUPLICATE",
                    unified_code=bar.unified_code,
                    timestamp=bar.timestamp,
                    detail=f"duplicate timestamp {bar.timestamp}",
                )
            )
        elif previous is not None and bar.timestamp < previous.timestamp:
            rejection.add(
                record,
                f"sequence: out-of-order timestamp {bar.timestamp} after {previous.timestamp}",
            )
            events.append(
                QualityEvent(
                    kind="OUT_OF_ORDER",
                    unified_code=bar.unified_code,
                    timestamp=bar.timestamp,
                    detail=f"{bar.timestamp} after {previous.timestamp}",
                )
            )
        seen_identities.add(identity)
        previous = bar
    return BarPipelineResult(accepted=accepted, rejection_zone=rejection, events=events)
