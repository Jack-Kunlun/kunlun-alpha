"""Instrument repository.

Stores normalized security master records keyed by ``unified_code`` (never by
display name) and keeps an append-only audit log of upserts and delistings so
additions, changes and delistings are all traceable.
"""

from __future__ import annotations

from typing import Protocol

from ashare_contracts.instrument_instrument import Instrument


class InstrumentRepository(Protocol):
    """Storage for security master records."""

    def get_all(self, exchange: str) -> dict[str, Instrument]: ...

    def upsert(self, instrument: Instrument) -> None: ...

    def remove(self, unified_code: str) -> None: ...

    def checkpoint(self) -> str | None: ...

    def set_checkpoint(self, cursor: str | None) -> None: ...

    def audit_log(self) -> list[str]: ...


class InMemoryInstrumentRepository:
    """In-memory implementation for tests and single-run jobs."""

    def __init__(self) -> None:
        self._data: dict[str, Instrument] = {}
        self._checkpoint: str | None = None
        self._audit: list[str] = []

    def get_all(self, exchange: str) -> dict[str, Instrument]:
        return {code: inst for code, inst in self._data.items() if inst.exchange.value == exchange}

    def upsert(self, instrument: Instrument) -> None:
        self._data[instrument.unified_code] = instrument
        self._audit.append(f"UPSERT {instrument.unified_code}")

    def remove(self, unified_code: str) -> None:
        self._data.pop(unified_code, None)
        self._audit.append(f"DELIST {unified_code}")

    def checkpoint(self) -> str | None:
        return self._checkpoint

    def set_checkpoint(self, cursor: str | None) -> None:
        self._checkpoint = cursor

    def audit_log(self) -> list[str]:
        return list(self._audit)
