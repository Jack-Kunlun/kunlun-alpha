"""Provider-boundary models for traceable market-bar parsing results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from ashare_contracts.market_data_bar import Bar

SINA_OVERFETCH_OUTSIDE_REQUEST = "SINA_OVERFETCH_OUTSIDE_REQUEST"


@dataclass(frozen=True, slots=True)
class BarExclusion:
    """One provider row intentionally excluded from the requested window."""

    raw_row_index: int
    timestamp: datetime
    requested_start: date
    requested_end: date
    reason_code: str = SINA_OVERFETCH_OUTSIDE_REQUEST

    def __post_init__(self) -> None:
        if type(self.raw_row_index) is not int or self.raw_row_index < 0:
            raise ValueError("raw_row_index must be a non-negative integer")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if type(self.requested_start) is not date or type(self.requested_end) is not date:
            raise ValueError("requested window must contain dates")
        if self.requested_end < self.requested_start:
            raise ValueError("requested_end must not precede requested_start")
        if self.reason_code != SINA_OVERFETCH_OUTSIDE_REQUEST:
            raise ValueError("reason_code is unsupported")

    def to_quality_record(self) -> dict[str, object]:
        """Return a bounded, provider-independent quality record."""

        return {
            "rawRowIndex": self.raw_row_index,
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "requestedStart": self.requested_start.isoformat(),
            "requestedEnd": self.requested_end.isoformat(),
            "reasonCode": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class ProviderParseResult:
    """Parsed bars plus explicit rows excluded by a provider boundary."""

    bars: list[Bar]
    exclusions: list[BarExclusion]


__all__ = [
    "BarExclusion",
    "ProviderParseResult",
    "SINA_OVERFETCH_OUTSIDE_REQUEST",
]
