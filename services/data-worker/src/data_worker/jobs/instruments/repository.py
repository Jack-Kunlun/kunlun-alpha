"""In-memory instrument repository and resumable collection checkpoint port."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol

from ashare_contracts.instrument_instrument import Instrument


class ActiveRunConflictError(RuntimeError):
    """Raised when a run cannot claim or update an exchange checkpoint."""


@dataclass(frozen=True)
class InstrumentCheckpoint:
    """Committed state for one exchange/run pagination snapshot."""

    exchange: str
    run_id: str
    next_cursor: str | None
    accepted_codes: frozenset[str]
    baseline: tuple[Instrument, ...] = ()
    consumed_cursors: tuple[str, ...] = ()
    page_count: int = 0
    complete: bool = False
    reconciled: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted_codes", frozenset(self.accepted_codes))
        object.__setattr__(
            self,
            "baseline",
            tuple(instrument.model_copy(deep=True) for instrument in self.baseline),
        )
        object.__setattr__(self, "consumed_cursors", tuple(dict.fromkeys(self.consumed_cursors)))

    @property
    def seen_codes(self) -> frozenset[str]:
        """Alias for accepted identities used by reconciliation consumers."""
        return self.accepted_codes

    @property
    def accepted_unified_codes(self) -> frozenset[str]:
        """Explicit identity-oriented alias for the persisted set."""
        return self.accepted_codes

    @property
    def seen_instrument_ids(self) -> frozenset[str]:
        """Alias used by checkpoint consumers describing accepted identities."""
        return self.accepted_codes

    @property
    def cursor_lineage(self) -> tuple[str, ...]:
        """Opaque cursor tokens whose pages were successfully consumed."""
        return self.consumed_cursors


class InstrumentRepository(Protocol):
    """Storage for security master records and collection checkpoints."""

    def get_all(self, exchange: str) -> dict[str, Instrument]: ...

    def upsert(self, instrument: Instrument) -> None: ...

    def remove(self, unified_code: str) -> None: ...

    def load_checkpoint(
        self, exchange: str, run_id: str | None = None
    ) -> InstrumentCheckpoint | None: ...

    def save_checkpoint(self, checkpoint: InstrumentCheckpoint) -> None: ...

    def claim_run(self, exchange: str, run_id: str) -> InstrumentCheckpoint: ...

    def reconcile_and_complete(
        self, checkpoint: InstrumentCheckpoint, delisted_codes: tuple[str, ...]
    ) -> InstrumentCheckpoint: ...

    def commit_page(
        self,
        checkpoint: InstrumentCheckpoint,
        instruments: tuple[Instrument, ...],
        next_cursor: str | None,
    ) -> InstrumentCheckpoint: ...

    def checkpoint_state(
        self, exchange: str, run_id: str | None = None
    ) -> InstrumentCheckpoint | None: ...

    def clear_checkpoint(self, exchange: str, run_id: str) -> None: ...

    # Legacy cursor accessors remain available for older in-process consumers.
    def checkpoint(self) -> str | None: ...

    def set_checkpoint(self, cursor: str | None) -> None: ...

    def audit_log(self) -> list[str]: ...


class InMemoryInstrumentRepository:
    """In-memory implementation for tests and single-run jobs."""

    def __init__(self) -> None:
        self._data: dict[str, Instrument] = {}
        self._checkpoints: dict[tuple[str, str], InstrumentCheckpoint] = {}
        self._active_runs: dict[str, str] = {}
        self._released_runs: set[tuple[str, str]] = set()
        self._last_checkpoint: InstrumentCheckpoint | None = None
        self._legacy_checkpoint: str | None = None
        self._audit: list[str] = []
        self._lock = RLock()

    def get_all(self, exchange: str) -> dict[str, Instrument]:
        with self._lock:
            return {
                code: instrument
                for code, instrument in self._data.items()
                if instrument.exchange.value == exchange
            }

    def upsert(self, instrument: Instrument) -> None:
        with self._lock:
            existing = self._data.get(instrument.unified_code)
            if existing == instrument:
                return
            self._data[instrument.unified_code] = instrument
            self._audit.append(f"UPSERT {instrument.unified_code}")

    def remove(self, unified_code: str) -> None:
        with self._lock:
            if unified_code not in self._data:
                return
            self._data.pop(unified_code)
            self._audit.append(f"DELIST {unified_code}")

    def load_checkpoint(
        self, exchange: str, run_id: str | None = None
    ) -> InstrumentCheckpoint | None:
        with self._lock:
            if run_id is not None:
                checkpoint = self._checkpoints.get((exchange, run_id))
                return self._copy_checkpoint(checkpoint) if checkpoint is not None else None
            active_run = self._active_runs.get(exchange)
            if active_run is not None:
                checkpoint = self._checkpoints.get((exchange, active_run))
                return self._copy_checkpoint(checkpoint) if checkpoint is not None else None
            return None

    def claim_run(self, exchange: str, run_id: str) -> InstrumentCheckpoint:
        """Atomically claim an exchange and snapshot its run-start baseline."""
        with self._lock:
            key = (exchange, run_id)
            if key in self._released_runs:
                raise ActiveRunConflictError(f"run {run_id} was already released")
            existing = self._checkpoints.get(key)
            if existing is not None:
                if existing.reconciled:
                    return self._copy_checkpoint(existing)
                if self._active_runs.get(exchange) != run_id:
                    raise ActiveRunConflictError(f"run {run_id} lost checkpoint ownership")
                return self._copy_checkpoint(existing)
            active_run = self._active_runs.get(exchange)
            if active_run is not None and active_run != run_id:
                raise ActiveRunConflictError(
                    f"exchange {exchange} already has active run {active_run}"
                )
            baseline = tuple(
                self._data[code].model_copy(deep=True)
                for code in sorted(self._data)
                if self._data[code].exchange.value == exchange
            )
            checkpoint = InstrumentCheckpoint(
                exchange=exchange,
                run_id=run_id,
                next_cursor=None,
                accepted_codes=frozenset(),
                baseline=baseline,
            )
            stored = self._copy_checkpoint(checkpoint)
            self._checkpoints[key] = stored
            self._active_runs[exchange] = run_id
            self._last_checkpoint = stored
            return self._copy_checkpoint(stored)

    def save_checkpoint(self, checkpoint: InstrumentCheckpoint) -> None:
        with self._lock:
            checkpoint = self._copy_checkpoint(checkpoint)
            key = (checkpoint.exchange, checkpoint.run_id)
            if key in self._released_runs:
                raise ActiveRunConflictError(f"run {checkpoint.run_id} was already released")
            owner = self._active_runs.get(checkpoint.exchange)
            existing = self._checkpoints.get(key)
            if owner is None:
                if checkpoint.reconciled or existing is not None:
                    raise ActiveRunConflictError(
                        f"run {checkpoint.run_id} does not own exchange {checkpoint.exchange}"
                    )
                self._active_runs[checkpoint.exchange] = checkpoint.run_id
            elif owner != checkpoint.run_id:
                raise ActiveRunConflictError(
                    f"run {checkpoint.run_id} does not own exchange {checkpoint.exchange}"
                )
            self._checkpoints[key] = checkpoint
            self._last_checkpoint = checkpoint
            if checkpoint.reconciled:
                self._active_runs.pop(checkpoint.exchange, None)

    def reconcile_and_complete(
        self, checkpoint: InstrumentCheckpoint, delisted_codes: tuple[str, ...]
    ) -> InstrumentCheckpoint:
        """Atomically apply delistings and release a completed run owner."""
        with self._lock:
            key = (checkpoint.exchange, checkpoint.run_id)
            if key in self._released_runs:
                raise ActiveRunConflictError(f"run {checkpoint.run_id} was already released")
            if self._active_runs.get(checkpoint.exchange) != checkpoint.run_id:
                raise ActiveRunConflictError(
                    f"run {checkpoint.run_id} does not own exchange {checkpoint.exchange}"
                )
            current = self._checkpoints.get(key)
            if current is None or current != checkpoint:
                raise ActiveRunConflictError("checkpoint compare-and-set failed")
            if not checkpoint.complete:
                raise ValueError("cannot reconcile an incomplete checkpoint")

            new_data = dict(self._data)
            new_audit = list(self._audit)
            for unified_code in dict.fromkeys(delisted_codes):
                existing = new_data.get(unified_code)
                if existing is None:
                    continue
                if existing.exchange.value != checkpoint.exchange:
                    raise ValueError("delisted instrument exchange does not match checkpoint")
                new_data.pop(unified_code)
                new_audit.append(f"DELIST {unified_code}")

            updated = InstrumentCheckpoint(
                exchange=checkpoint.exchange,
                run_id=checkpoint.run_id,
                next_cursor=checkpoint.next_cursor,
                accepted_codes=checkpoint.accepted_codes,
                baseline=checkpoint.baseline,
                consumed_cursors=checkpoint.consumed_cursors,
                page_count=checkpoint.page_count,
                complete=True,
                reconciled=True,
            )
            stored = self._copy_checkpoint(updated)
            self._data = new_data
            self._audit = new_audit
            self._checkpoints[key] = stored
            self._last_checkpoint = stored
            self._active_runs.pop(checkpoint.exchange, None)
            return self._copy_checkpoint(stored)

    def commit_page(
        self,
        checkpoint: InstrumentCheckpoint,
        instruments: tuple[Instrument, ...],
        next_cursor: str | None,
    ) -> InstrumentCheckpoint:
        """Atomically publish page records, audit entries, and next checkpoint."""
        with self._lock:
            key = (checkpoint.exchange, checkpoint.run_id)
            if key in self._released_runs:
                raise ActiveRunConflictError(f"run {checkpoint.run_id} was already released")
            if self._active_runs.get(checkpoint.exchange) != checkpoint.run_id:
                raise ActiveRunConflictError(
                    f"run {checkpoint.run_id} does not own exchange {checkpoint.exchange}"
                )
            current = self._checkpoints.get(key)
            if current is None or current != checkpoint:
                raise ActiveRunConflictError("checkpoint compare-and-set failed")

            consumed_cursors = list(checkpoint.consumed_cursors)
            current_cursor = checkpoint.next_cursor
            if current_cursor is not None:
                if current_cursor in consumed_cursors:
                    raise ValueError("checkpoint cursor was already consumed")
                consumed_cursors.append(current_cursor)
            if next_cursor is not None and (
                next_cursor == current_cursor or next_cursor in consumed_cursors
            ):
                raise ValueError("provider returned a repeated pagination cursor")

            new_data = dict(self._data)
            new_audit = list(self._audit)
            accepted_codes = set(checkpoint.accepted_codes)
            for instrument in instruments:
                if instrument.exchange.value != checkpoint.exchange:
                    raise ValueError("page instrument exchange does not match checkpoint")
                accepted_codes.add(instrument.unified_code)
                existing = new_data.get(instrument.unified_code)
                if existing != instrument:
                    new_data[instrument.unified_code] = instrument.model_copy(deep=True)
                    new_audit.append(f"UPSERT {instrument.unified_code}")

            updated = InstrumentCheckpoint(
                exchange=checkpoint.exchange,
                run_id=checkpoint.run_id,
                next_cursor=next_cursor,
                accepted_codes=frozenset(accepted_codes),
                baseline=checkpoint.baseline,
                consumed_cursors=tuple(consumed_cursors),
                page_count=checkpoint.page_count + 1,
                complete=next_cursor is None,
                reconciled=False,
            )
            stored = self._copy_checkpoint(updated)
            self._data = new_data
            self._audit = new_audit
            self._checkpoints[key] = stored
            self._last_checkpoint = stored
            return self._copy_checkpoint(stored)

    def checkpoint_state(
        self, exchange: str, run_id: str | None = None
    ) -> InstrumentCheckpoint | None:
        with self._lock:
            checkpoint = self.load_checkpoint(exchange, run_id)
            if checkpoint is not None or run_id is not None:
                return checkpoint
            history = [
                checkpoint
                for (checkpoint_exchange, _), checkpoint in self._checkpoints.items()
                if checkpoint_exchange == exchange
            ]
            return self._copy_checkpoint(history[-1]) if history else None

    @staticmethod
    def _copy_checkpoint(checkpoint: InstrumentCheckpoint) -> InstrumentCheckpoint:
        return InstrumentCheckpoint(
            exchange=checkpoint.exchange,
            run_id=checkpoint.run_id,
            next_cursor=checkpoint.next_cursor,
            accepted_codes=checkpoint.accepted_codes,
            baseline=checkpoint.baseline,
            consumed_cursors=checkpoint.consumed_cursors,
            page_count=checkpoint.page_count,
            complete=checkpoint.complete,
            reconciled=checkpoint.reconciled,
        )

    def clear_checkpoint(self, exchange: str, run_id: str) -> None:
        with self._lock:
            key = (exchange, run_id)
            removed = self._checkpoints.get(key)
            owner = self._active_runs.get(exchange)
            if owner is not None and owner != run_id:
                raise ActiveRunConflictError(f"run {run_id} does not own exchange {exchange}")
            if removed is not None:
                self._checkpoints.pop(key)
                self._released_runs.add(key)
                if self._last_checkpoint == removed:
                    self._last_checkpoint = None
            if owner == run_id:
                self._active_runs.pop(exchange, None)

    def checkpoint(self) -> str | None:
        with self._lock:
            if self._last_checkpoint is not None and not self._last_checkpoint.reconciled:
                return self._last_checkpoint.next_cursor
            return self._legacy_checkpoint

    def set_checkpoint(self, cursor: str | None) -> None:
        with self._lock:
            self._legacy_checkpoint = cursor

    def audit_log(self) -> list[str]:
        with self._lock:
            return list(self._audit)
