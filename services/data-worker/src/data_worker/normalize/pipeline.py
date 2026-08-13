"""Bar normalization + validation pipeline.

Combines normalization, per-bar validation and sequence checks into one pass:
accepted bars are returned, abnormal records go to the rejection zone, and
every issue is surfaced as a quality event (nothing is silently dropped).
"""

from __future__ import annotations

from dataclasses import dataclass

from market_core.models.validators import Bar
from market_core.validation import QualityEvent, detect_sequence_issues, validate_bar_with_event

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
    events: list[QualityEvent] = []

    for record in records:
        try:
            bar = normalize_bar(record)
        except (MissingFieldError, KeyError, ValueError) as exc:
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

    events.extend(detect_sequence_issues(accepted))
    return BarPipelineResult(accepted=accepted, rejection_zone=rejection, events=events)
