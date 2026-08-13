"""Market data validation and sequence quality.

Provides quality events for out-of-order and duplicate bars on top of the
per-bar validators in :mod:`market_core.models.validators`. Abnormal data is
never silently dropped — every rejected record is surfaced as a quality event
with a reason, so it can be routed to a rejection zone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from market_core.models.validators import Bar, ValidationResult, validate_bar

QualityKind = Literal[
    "OUT_OF_ORDER",
    "DUPLICATE",
    "NEGATIVE_PRICE",
    "ABNORMAL_VOLUME",
    "MISSING_FIELD",
]


@dataclass(frozen=True)
class QualityEvent:
    """One market data quality issue."""

    kind: QualityKind
    unified_code: str
    timestamp: str
    detail: str


def detect_sequence_issues(bars: list[Bar]) -> list[QualityEvent]:
    """Detect out-of-order and duplicate bars in a time-ordered sequence."""
    events: list[QualityEvent] = []
    for i in range(1, len(bars)):
        prev = bars[i - 1]
        curr = bars[i]
        if curr.timestamp == prev.timestamp:
            events.append(
                QualityEvent(
                    kind="DUPLICATE",
                    unified_code=curr.unified_code,
                    timestamp=curr.timestamp,
                    detail=f"duplicate timestamp {curr.timestamp}",
                )
            )
        elif curr.timestamp < prev.timestamp:
            events.append(
                QualityEvent(
                    kind="OUT_OF_ORDER",
                    unified_code=curr.unified_code,
                    timestamp=curr.timestamp,
                    detail=f"{curr.timestamp} after {prev.timestamp}",
                )
            )
    return events


def validate_bar_with_event(bar: Bar) -> tuple[ValidationResult, list[QualityEvent]]:
    """Validate a bar and translate failures into quality events."""
    result = validate_bar(bar)
    if result.valid:
        return result, []
    kind: QualityKind
    if "open must be >= 0" in result.errors or "close must be >= 0" in result.errors:
        kind = "NEGATIVE_PRICE"
    elif "volume must be >= 0" in result.errors:
        kind = "ABNORMAL_VOLUME"
    else:
        kind = "NEGATIVE_PRICE"
    events = [
        QualityEvent(
            kind=kind,
            unified_code=bar.unified_code,
            timestamp=bar.timestamp,
            detail="; ".join(result.errors),
        )
    ]
    return result, events
