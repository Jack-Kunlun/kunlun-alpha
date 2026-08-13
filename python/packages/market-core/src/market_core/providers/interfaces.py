"""Provider interface family.

One interface per domain so each adapter stays independent. Every interface
inherits :class:`Provider` (capability declaration) and adds cursor-paged fetch
methods. Engines depend on these interfaces, never on a concrete vendor SDK.
"""

from __future__ import annotations

from abc import abstractmethod

from ashare_contracts.calendar_holiday import Holiday
from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.market_data_bar import Bar
from ashare_contracts.market_data_tick import Tick
from ashare_contracts.providers import Cursor, Page

from market_core.providers.base import Provider


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
