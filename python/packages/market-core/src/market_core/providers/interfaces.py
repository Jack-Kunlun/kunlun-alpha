"""Provider interface family.

One interface per domain so each adapter stays independent. Every interface
inherits :class:`Provider` (capability declaration) and adds cursor-paged fetch
methods. Engines depend on these interfaces, never on a concrete vendor SDK.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.market_data_bar import Bar
from ashare_contracts.market_data_tick import Tick
from ashare_contracts.providers import Cursor, Page

from market_core.providers.base import Provider


def _is_bytes(value: object) -> bool:
    return isinstance(value, bytes)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


_MIME_TOKEN_RE = r"[A-Za-z0-9!#$&^_.+-]+"
_MIME_RE = re.compile(
    rf"^(?P<type>{_MIME_TOKEN_RE})/(?P<subtype>{_MIME_TOKEN_RE})(?:;\s*charset=(?P<charset>{_MIME_TOKEN_RE}))?$",
    re.ASCII,
)
_UNSAFE_MIME_MARKERS = ("bearer", "basic", "cookie", "credential", "token", "dsn")


def _normalize_content_type(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("raw fund response content_type must be non-empty")
    candidate = value.strip()
    if len(candidate) > 128 or not candidate.isascii():
        raise ValueError("raw fund response content_type is invalid")
    lowered = candidate.lower()
    if any(marker in lowered for marker in _UNSAFE_MIME_MARKERS):
        raise ValueError("raw fund response content_type contains unsafe material")
    match = _MIME_RE.fullmatch(candidate)
    if match is None:
        raise ValueError("raw fund response content_type is invalid")
    media_type = f"{match.group('type').lower()}/{match.group('subtype').lower()}"
    charset = match.group("charset")
    return media_type if charset is None else f"{media_type}; charset={charset.lower()}"


@dataclass(frozen=True, slots=True)
class RawFundProviderResponse:
    """Raw transport response for one fund endpoint page."""

    body: bytes
    source: str
    request: str
    content_type: str = "application/json"
    ingest_time: datetime | None = None
    available_time: datetime | None = None
    endpoint_kind: str | None = None
    run_id: str | None = None
    source_revision: str | None = None
    capture_id: str | None = None

    def __post_init__(self) -> None:
        if not _is_bytes(self.body):
            raise TypeError("raw fund response body must be bytes")
        if not _is_non_empty_string(self.source):
            raise ValueError("raw fund response source must be non-empty")
        if not _is_non_empty_string(self.request):
            raise ValueError("raw fund response request must be non-empty")
        object.__setattr__(self, "content_type", _normalize_content_type(self.content_type))
        for name, value in (
            ("ingest_time", self.ingest_time),
            ("available_time", self.available_time),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"raw fund response {name} must be timezone-aware")
        if (
            self.ingest_time is not None
            and self.available_time is not None
            and self.available_time < self.ingest_time
        ):
            raise ValueError("raw fund response available_time cannot precede ingest_time")


class InstrumentProvider(Provider):
    """Fetches security master records."""

    @abstractmethod
    def fetch_instruments(
        self, exchange: str, cursor: Cursor | None = None
    ) -> Page[Instrument]: ...


class CalendarProvider(Provider):
    """Fetches exchange calendar entries (holidays and temporary closures)."""

    @abstractmethod
    def fetch_holidays(
        self, exchange: str, year: int, cursor: Cursor | None = None
    ) -> Page[Holiday]: ...


class MarketDataProvider(Provider):
    """Fetches OHLCV bars and executed trades."""

    @abstractmethod
    def fetch_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: Cursor | None = None,
    ) -> Page[Bar]: ...

    @abstractmethod
    def fetch_ticks(
        self, unified_code: str, date: str, cursor: Cursor | None = None
    ) -> Page[Tick]: ...


class SectorProvider(Provider):
    """Fetches sector taxonomy and membership records (contract in P2-N06)."""

    @abstractmethod
    def fetch_sectors(self, cursor: Cursor | None = None) -> Page[dict[str, object]]: ...


class NewsProvider(Provider):
    """Fetches news items related to an instrument (contract not yet defined)."""

    @abstractmethod
    def fetch_news(
        self, unified_code: str | None = None, cursor: Cursor | None = None
    ) -> Page[dict[str, object]]: ...


class FundMetadataProvider(Provider):
    """Fetches exchange-listed precious-metals fund metadata."""

    @abstractmethod
    def fetch_fund_metadata(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse: ...


class FundNavProvider(Provider):
    """Fetches point-in-time NAV reference observations."""

    @abstractmethod
    def fetch_fund_nav(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse: ...

    def fetch_navs(self, exchange: str, cursor: Cursor | None = None) -> RawFundProviderResponse:
        """Backward-compatible alias used by the original NAV collector."""
        return self.fetch_fund_nav(exchange, cursor)


class FundInavProvider(Provider):
    """Fetches point-in-time indicative NAV reference observations."""

    @abstractmethod
    def fetch_fund_inav(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse: ...

    def fetch_inavs(self, exchange: str, cursor: Cursor | None = None) -> RawFundProviderResponse:
        """Alias for adapters that name the endpoint ``inavs``."""
        return self.fetch_fund_inav(exchange, cursor)


class FundBenchmarkProvider(Provider):
    """Fetches benchmark/tracking-index metadata for funds."""

    @abstractmethod
    def fetch_fund_benchmark(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse: ...

    def fetch_benchmark_metadata(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse:
        """Descriptive alias for the benchmark metadata endpoint."""
        return self.fetch_fund_benchmark(exchange, cursor)


class FundFeeProvider(Provider):
    """Fetches recurring fund fee metadata."""

    @abstractmethod
    def fetch_fund_fees(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse: ...

    def fetch_fee_metadata(
        self, exchange: str, cursor: Cursor | None = None
    ) -> RawFundProviderResponse:
        """Descriptive alias for the fee metadata endpoint."""
        return self.fetch_fund_fees(exchange, cursor)
