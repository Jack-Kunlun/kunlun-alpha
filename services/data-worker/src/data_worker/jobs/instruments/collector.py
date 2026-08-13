"""Instrument collection job.

Collects the full security master for an exchange from a provider, upserts it
into the repository keyed by ``unified_code``, and emits a diff report of
added / changed / delisted instruments. Repeated runs are idempotent: the
second run over unchanged data produces an empty diff. Transient provider
errors (rate limit, timeout, unavailable) are retried; permanent errors
(auth, data error) fail fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ashare_contracts.instrument_instrument import Instrument
from data_worker.jobs.instruments.repository import InstrumentRepository
from market_core.providers import (
    InstrumentProvider,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

ChangeKind = Literal["ADDED", "CHANGED", "DELISTED"]

_TRANSIENT_ERRORS = (ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError)


@dataclass(frozen=True)
class InstrumentChange:
    """One instrument-level diff between the previous and current snapshot."""

    kind: ChangeKind
    unified_code: str
    before: Instrument | None = None
    after: Instrument | None = None


@dataclass(frozen=True)
class CollectResult:
    """Diff report for a collection run."""

    added: list[Instrument]
    changed: list[InstrumentChange]
    delisted: list[InstrumentChange]

    def is_empty(self) -> bool:
        return not self.added and not self.changed and not self.delisted


class InstrumentCollector:
    """Collects and reconciles an exchange's security master."""

    def __init__(
        self, provider: InstrumentProvider, repository: InstrumentRepository, max_retries: int = 3
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._max_retries = max_retries

    def collect(self, exchange: str) -> CollectResult:
        instruments = self._fetch_all(exchange)
        old = self._repository.get_all(exchange)

        added = [inst for code, inst in instruments.items() if code not in old]
        delisted = [
            InstrumentChange(kind="DELISTED", unified_code=code, before=inst)
            for code, inst in old.items()
            if code not in instruments
        ]
        changed = [
            InstrumentChange(
                kind="CHANGED", unified_code=code, before=inst, after=instruments[code]
            )
            for code, inst in old.items()
            if code in instruments and inst != instruments[code]
        ]

        for code, inst in instruments.items():
            if code not in old or inst != old.get(code):
                self._repository.upsert(inst)
        for change in delisted:
            self._repository.remove(change.unified_code)

        self._repository.set_checkpoint(None)
        return CollectResult(added=added, changed=changed, delisted=delisted)

    def _fetch_all(self, exchange: str) -> dict[str, Instrument]:
        instruments: dict[str, Instrument] = {}
        cursor = self._repository.checkpoint()
        while True:
            page = self._fetch_with_retry(exchange, cursor)
            for inst in page.items:
                instruments[inst.unified_code] = inst
            cursor = page.next_cursor
            if cursor is None:
                return instruments

    def _fetch_with_retry(self, exchange: str, cursor: str | None):
        for attempt in range(self._max_retries):
            try:
                return self._provider.fetch_instruments(exchange, cursor)
            except _TRANSIENT_ERRORS:
                if attempt == self._max_retries - 1:
                    raise
            except ProviderError:
                raise
        raise ProviderUnavailableError("max retries exhausted")
