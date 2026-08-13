"""Mock providers for contract tests.

These fake implementations let tests exercise the provider contract — timeout,
rate limiting and empty pages — without any vendor SDK. Engines are written
against the interfaces in :mod:`market_core.providers.interfaces`, so a mock
that honours the same contract validates the abstraction.
"""

from __future__ import annotations

from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.providers import Capability, Cursor, Page

from market_core.providers.errors import ProviderTimeoutError
from market_core.providers.interfaces import InstrumentProvider


class MockInstrumentProvider(InstrumentProvider):
    """An InstrumentProvider whose behaviour is scripted via flags."""

    def __init__(
        self,
        *,
        timeout: bool = False,
        empty_page: bool = False,
    ) -> None:
        self._timeout = timeout
        self._empty_page = empty_page

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_INSTRUMENTS})

    def fetch_instruments(self, exchange: str, cursor: Cursor | None = None) -> Page[Instrument]:
        if self._timeout:
            raise ProviderTimeoutError("simulated upstream timeout")
        if self._empty_page:
            return Page(items=[], next_cursor=None)
        instrument = Instrument.model_validate(
            {
                "unifiedCode": "SH.600000",
                "code": "600000",
                "exchange": "SH",
                "board": "MAIN",
                "type": "STOCK",
                "name": "浦发银行",
                "tradingStatus": "LISTED",
                "currency": "CNY",
            }
        )
        return Page(items=[instrument], next_cursor=None)
