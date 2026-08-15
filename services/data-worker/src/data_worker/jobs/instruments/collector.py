"""Paginated instrument collection with run-scoped restart checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from ashare_contracts.instrument_instrument import Instrument
from ashare_contracts.providers import Cursor, Page
from data_worker.jobs.instruments.repository import (
    ActiveRunConflictError,
    InstrumentCheckpoint,
    InstrumentRepository,
)
from market_core.providers import (
    InstrumentProvider,
    ProviderDataError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

ChangeKind = Literal["ADDED", "CHANGED", "DELISTED"]

__all__ = [
    "ActiveRunConflictError",
    "CollectResult",
    "InstrumentChange",
    "InstrumentCollector",
]

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

    def collect(self, exchange: str, run_id: str | None = None) -> CollectResult:
        """Collect one full snapshot, resuming an incomplete run when available."""
        checkpoint = self._repository.load_checkpoint(exchange, run_id)
        if checkpoint is None:
            checkpoint = self._repository.claim_run(
                exchange,
                run_id or uuid4().hex,
            )

        if checkpoint.reconciled:
            return CollectResult(added=[], changed=[], delisted=[])

        old = {instrument.unified_code: instrument for instrument in checkpoint.baseline}
        if not checkpoint.complete:
            checkpoint = self._fetch_pages(checkpoint)

        all_records = self._repository.get_all(exchange)
        instruments = {
            code: all_records[code]
            for code in sorted(checkpoint.accepted_codes)
            if code in all_records
        }

        added = [instrument for code, instrument in instruments.items() if code not in old]
        changed = [
            InstrumentChange(
                kind="CHANGED",
                unified_code=code,
                before=old[code],
                after=instrument,
            )
            for code, instrument in instruments.items()
            if code in old and old[code] != instrument
        ]
        delisted = [
            InstrumentChange(kind="DELISTED", unified_code=code, before=instrument)
            for code, instrument in old.items()
            if code not in instruments
        ]

        # A missing-code diff is meaningful only after the provider signalled
        # the final page.  Failed or partial runs leave this branch untouched.
        if checkpoint.complete:
            self._repository.reconcile_and_complete(
                checkpoint,
                tuple(change.unified_code for change in delisted),
            )
        else:
            delisted = []

        return CollectResult(added=added, changed=changed, delisted=delisted)

    def _fetch_pages(self, checkpoint: InstrumentCheckpoint) -> InstrumentCheckpoint:
        cursor = checkpoint.next_cursor

        while True:
            page = self._fetch_with_retry(checkpoint.exchange, cursor)
            next_cursor = page.next_cursor
            consumed_cursor_set = set(checkpoint.consumed_cursors)
            if cursor is not None and cursor in consumed_cursor_set:
                raise ProviderDataError("checkpoint cursor was already consumed")
            if next_cursor is not None and (
                next_cursor == cursor or next_cursor in consumed_cursor_set
            ):
                raise ProviderDataError("provider returned a repeated pagination cursor")

            checkpoint = self._repository.commit_page(
                checkpoint,
                tuple(page.items),
                next_cursor,
            )
            if checkpoint.complete:
                return checkpoint
            cursor = next_cursor

    def _fetch_with_retry(self, exchange: str, cursor: Cursor | None) -> Page[Instrument]:
        for attempt in range(self._max_retries):
            try:
                return self._provider.fetch_instruments(exchange, cursor)
            except _TRANSIENT_ERRORS:
                if attempt == self._max_retries - 1:
                    raise
            except ProviderError:
                raise
        raise ProviderUnavailableError("max retries exhausted")
