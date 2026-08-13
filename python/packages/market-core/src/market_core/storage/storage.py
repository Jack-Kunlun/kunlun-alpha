"""Market data storage.

``BarStorage`` is the write/query abstraction for high-frequency market data.
``InMemoryBarStorage`` mirrors ClickHouse's ReplacingMergeTree semantics for
tests: rows are keyed by (unified_code, timestamp) and re-writing the same key
replaces the previous row, so batch writes are idempotent. The ordering key
matches the dominant query pattern (one instrument over a time range).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from market_core.models.validators import Bar


class BarStorage(ABC):
    """Storage for OHLCV bars (backed by ClickHouse in production)."""

    @abstractmethod
    def write_bars(self, bars: list[Bar]) -> int:
        """Write bars idempotently; returns the number of distinct keys."""

    @abstractmethod
    def query_bars(self, unified_code: str, start: str, end: str) -> list[Bar]:
        """Query bars for an instrument in [start, end], ordered by timestamp."""


class InMemoryBarStorage(BarStorage):
    """In-memory storage with ReplacingMergeTree (key dedupe) semantics."""

    def __init__(self) -> None:
        self._bars: dict[tuple[str, str], Bar] = {}

    def write_bars(self, bars: list[Bar]) -> int:
        for bar in bars:
            self._bars[(bar.unified_code, bar.timestamp)] = bar
        return len(self._bars)

    def query_bars(self, unified_code: str, start: str, end: str) -> list[Bar]:
        rows = [
            bar
            for (code, _), bar in self._bars.items()
            if code == unified_code and start <= bar.timestamp <= end
        ]
        return sorted(rows, key=lambda b: b.timestamp)
