"""Versioned market-data storage abstractions.

``Bar`` is the shared domain contract and intentionally contains no provider or
point-in-time storage metadata.  ``StoredBar`` is the immutable storage-side
envelope that carries that metadata without widening the shared contract.
``InMemoryBarStorage`` mirrors the deterministic read semantics required by
ClickHouse's ``ReplacingMergeTree(replacement_version)`` tables: rows retain
all replacement versions, while reads choose the highest version *after* the
``available_time`` as-of filter has been applied.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from market_core.models.validators import (
    Bar,
    BarInterval,
    ExchangeId,
    PriceType,
    SessionKind,
)


def _parse_utc(value: datetime | str, field: str) -> datetime:
    """Parse an aware timestamp and normalize it to UTC."""

    parsed = value if isinstance(value, datetime) else _parse_iso_timestamp(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid timestamp: {value!r}") from exc


def _required_timestamp(value: datetime | str | None, field: str) -> datetime:
    if value is None:
        raise ValueError(f"{field} is required")
    return _parse_utc(value, field)


def _require_bar(value: object) -> Bar:
    if not isinstance(value, Bar):
        raise TypeError("bar must be a Bar")
    return value


@dataclass(frozen=True, slots=True)
class StoredBar:
    """Immutable storage envelope for a validated :class:`~market_core.models.Bar`.

    ``event_time`` defaults to the domain bar timestamp.  Provenance and PIT
    fields are required so storage cannot silently fabricate source metadata.
    """

    bar: Bar
    data_version: str
    source: str
    source_version: str
    raw_capture_id: str
    available_time: datetime | str
    ingest_time: datetime | str
    processing_time: datetime | str
    replacement_version: int
    event_time: datetime | str | None = None

    def __post_init__(self) -> None:
        _require_bar(self.bar)
        for field in ("data_version", "source", "source_version", "raw_capture_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")
        replacement_version: object = self.replacement_version
        if type(replacement_version) is not int:
            raise TypeError("replacement_version must be an integer")
        if self.replacement_version < 1:
            raise ValueError("replacement_version must be >= 1")

        event_time = _parse_utc(
            self.bar.timestamp if self.event_time is None else self.event_time,
            "event_time",
        )
        ingest_time = _parse_utc(self.ingest_time, "ingest_time")
        available_time = _parse_utc(self.available_time, "available_time")
        processing_time = _parse_utc(self.processing_time, "processing_time")
        if available_time < ingest_time:
            raise ValueError("available_time cannot precede ingest_time")
        if processing_time < available_time:
            raise ValueError("processing_time cannot precede available_time")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "ingest_time", ingest_time)
        object.__setattr__(self, "available_time", available_time)
        object.__setattr__(self, "processing_time", processing_time)

    @property
    def identity(self) -> tuple[str, str, str, str, str, str, str, str]:
        """Return the complete semantic identity used by the storage key."""

        return (
            self.bar.unified_code,
            self.bar.interval,
            _required_timestamp(self.event_time, "event_time").isoformat(),
            self.bar.session,
            self.bar.price_type,
            self.data_version,
            self.source,
            self.source_version,
        )

    @property
    def unified_code(self) -> str:
        return self.bar.unified_code

    @property
    def exchange(self) -> ExchangeId:
        return self.bar.exchange

    @property
    def date(self) -> str:
        return self.bar.date

    @property
    def interval(self) -> BarInterval:
        return self.bar.interval

    @property
    def session(self) -> SessionKind:
        return self.bar.session

    @property
    def timestamp(self) -> str:
        return self.bar.timestamp

    @property
    def open(self) -> Decimal:
        return self.bar.open

    @property
    def high(self) -> Decimal:
        return self.bar.high

    @property
    def low(self) -> Decimal:
        return self.bar.low

    @property
    def close(self) -> Decimal:
        return self.bar.close

    @property
    def volume(self) -> int:
        return self.bar.volume

    @property
    def amount(self) -> Decimal:
        return self.bar.amount

    @property
    def price_type(self) -> PriceType:
        return self.bar.price_type

    @property
    def suspended(self) -> bool:
        return self.bar.suspended


_Identity = tuple[str, str, str, str, str, str, str, str]


def _require_stored_bar(value: object) -> StoredBar:
    if not isinstance(value, StoredBar):
        raise TypeError("write_bars requires explicit StoredBar metadata")
    return value


class BarStorage(ABC):
    """Storage for OHLCV bars (backed by ClickHouse in production)."""

    @abstractmethod
    def write_bars(self, bars: Iterable[StoredBar]) -> int:
        """Write bars idempotently; return the number of semantic identities."""

    @abstractmethod
    def query_bars(
        self,
        unified_code: str,
        start: str,
        end: str,
        *,
        as_of: datetime | str | None = None,
    ) -> list[StoredBar]:
        """Query deterministic latest rows in an event-time range."""


class InMemoryBarStorage(BarStorage):
    """In-memory storage with deterministic replacement and PIT semantics."""

    def __init__(self) -> None:
        self._bars: dict[_Identity, dict[int, StoredBar]] = {}

    def write_bars(self, bars: Iterable[StoredBar]) -> int:
        staged = {identity: dict(versions) for identity, versions in self._bars.items()}
        for bar in bars:
            stored = _require_stored_bar(bar)
            versions = staged.setdefault(stored.identity, {})
            existing = versions.get(stored.replacement_version)
            if existing is not None and existing != stored:
                raise ValueError("conflicting revision for the same identity and version")
            versions[stored.replacement_version] = stored
        self._bars = staged
        return len(self._bars)

    def query_bars(
        self,
        unified_code: str,
        start: str,
        end: str,
        *,
        as_of: datetime | str | None = None,
    ) -> list[StoredBar]:
        start_time = _parse_utc(start, "start")
        end_time = _parse_utc(end, "end")
        if end_time < start_time:
            raise ValueError("end must be greater than or equal to start")
        as_of_time = None if as_of is None else _parse_utc(as_of, "as_of")

        rows: list[StoredBar] = []
        for versions in self._bars.values():
            candidates = [
                row
                for row in versions.values()
                if row.unified_code == unified_code
                and start_time <= _required_timestamp(row.event_time, "event_time") <= end_time
                and (
                    as_of_time is None
                    or _required_timestamp(row.available_time, "available_time") <= as_of_time
                )
            ]
            if candidates:
                row = max(candidates, key=lambda candidate: candidate.replacement_version)
                rows.append(row)
        return sorted(
            rows,
            key=lambda row: (
                _required_timestamp(row.event_time, "event_time"),
                row.identity,
            ),
        )

    def query_bars_as_of(
        self,
        unified_code: str,
        start: str,
        end: str,
        as_of: datetime | str,
    ) -> list[StoredBar]:
        """Explicit alias for callers issuing a point-in-time query."""

        return self.query_bars(unified_code, start, end, as_of=as_of)


__all__ = ["BarStorage", "InMemoryBarStorage", "StoredBar"]
