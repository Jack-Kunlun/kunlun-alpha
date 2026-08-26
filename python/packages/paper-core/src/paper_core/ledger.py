"""Pure append and replay operations for the paper-account event tape."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .models import (
    ZERO_DIGEST,
    ChangePaperAccountStatus,
    OpenPaperAccount,
    PaperAccountConcurrencyError,
    PaperAccountEvent,
    PaperAccountEventConflictError,
    PaperAccountLifecycleError,
    PaperAccountState,
    PaperAccountStatus,
    PaperAccountValidationError,
    PaperPosition,
    PaperValuation,
    RecordPaperValuation,
    TransferPaperPosition,
    canonical_digest,
    event_digest,
)


@dataclass(frozen=True, slots=True)
class PaperAccountTape:
    account_id: str
    events: tuple[PaperAccountEvent, ...] = ()
    tape_digest: str = ""

    def __post_init__(self) -> None:
        digests: list[str] = []
        previous_event_digest = ZERO_DIGEST
        previous_available_time: datetime | None = None
        for sequence, event in enumerate(self.events):
            metadata = event.metadata
            if metadata.account_id != self.account_id:
                raise PaperAccountValidationError("event belongs to another paper account")
            if metadata.sequence != sequence:
                raise PaperAccountValidationError("event sequence must be contiguous")
            if metadata.previous_event_digest != previous_event_digest:
                raise PaperAccountValidationError("event digest chain is broken")
            if previous_available_time and metadata.available_time < previous_available_time:
                raise PaperAccountValidationError("event availability must be non-decreasing")
            digest = event_digest(event)
            digests.append(digest)
            previous_event_digest = digest
            previous_available_time = metadata.available_time
        computed = ZERO_DIGEST if not digests else canonical_digest(digests)
        if self.tape_digest and self.tape_digest != computed:
            raise PaperAccountValidationError("declared tape digest does not match events")
        object.__setattr__(self, "tape_digest", computed)

    @property
    def last_event_digest(self) -> str:
        return ZERO_DIGEST if not self.events else event_digest(self.events[-1])


def append_account_event(
    tape: PaperAccountTape,
    event: PaperAccountEvent,
) -> PaperAccountTape:
    existing = next(
        (
            candidate
            for candidate in tape.events
            if candidate.metadata.event_id == event.metadata.event_id
        ),
        None,
    )
    if existing is not None:
        if event_digest(existing) == event_digest(event):
            return tape
        raise PaperAccountEventConflictError("event_id was reused with different content")
    if event.metadata.account_id != tape.account_id:
        raise PaperAccountValidationError("event belongs to another paper account")
    if event.metadata.sequence != len(tape.events):
        raise PaperAccountConcurrencyError("event sequence was based on stale state")
    if event.metadata.previous_event_digest != tape.last_event_digest:
        raise PaperAccountConcurrencyError("previous event digest was based on stale state")
    candidate = PaperAccountTape(tape.account_id, tape.events + (event,))
    replay_account(candidate)
    return candidate


def replay_account(
    tape: PaperAccountTape,
    *,
    as_of: datetime | None = None,
) -> PaperAccountState | None:
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise PaperAccountValidationError("as_of must be timezone-aware")
    visible = tuple(
        event for event in tape.events if as_of is None or event.metadata.available_time <= as_of
    )
    if not visible:
        return None
    first = visible[0]
    if type(first) is not OpenPaperAccount:
        raise PaperAccountLifecycleError("the first account event must open the account")
    chain = canonical_digest([event_digest(first)])
    state = PaperAccountState(
        account_id=tape.account_id,
        owner_ref=first.owner_ref,
        name=first.name,
        status=PaperAccountStatus.ACTIVE,
        initial_capital=first.initial_capital,
        cash=first.initial_capital,
        positions=(),
        latest_valuation=None,
        data_cutoff_time=first.metadata.available_time,
        event_count=1,
        event_chain_digest=chain,
    )
    for event in visible[1:]:
        chain = canonical_digest([state.event_chain_digest, event_digest(event)])
        state = _apply(state, event, chain)
    return state


def _apply(
    state: PaperAccountState,
    event: PaperAccountEvent,
    chain_digest: str,
) -> PaperAccountState:
    if type(event) is OpenPaperAccount:
        raise PaperAccountLifecycleError("a paper account can be opened only once")
    if state.status is PaperAccountStatus.CLOSED:
        raise PaperAccountLifecycleError("a closed paper account is immutable")
    common: dict[str, object] = {
        "data_cutoff_time": event.metadata.available_time,
        "event_count": state.event_count + 1,
        "event_chain_digest": chain_digest,
    }
    if type(event) is TransferPaperPosition:
        if state.status is not PaperAccountStatus.ACTIVE:
            raise PaperAccountLifecycleError("position transfers require an active account")
        return _apply_position(state, event, common)
    if type(event) is RecordPaperValuation:
        return _apply_valuation(state, event, common)
    if type(event) is ChangePaperAccountStatus:
        return _apply_status(state, event, common)
    raise PaperAccountValidationError("unsupported paper account event")


def _apply_position(
    state: PaperAccountState,
    event: TransferPaperPosition,
    common: dict[str, object],
) -> PaperAccountState:
    existing = next(
        (item for item in state.positions if item.instrument_id == event.instrument_id),
        None,
    )
    old_quantity = existing.quantity if existing else 0
    old_available = existing.available_quantity if existing else 0
    old_cost = existing.cost_amount if existing else Decimal("0")
    quantity = old_quantity + event.quantity_delta
    available = old_available + event.available_quantity_delta
    cost = old_cost + event.position_cost_delta
    cash = state.cash + event.cash_delta
    if cash < 0:
        raise PaperAccountValidationError("paper account cash cannot become negative")
    if quantity < 0 or available < 0 or available > quantity or cost < 0:
        raise PaperAccountValidationError("position transfer creates an invalid position")
    if quantity == 0 and (available != 0 or cost != 0):
        raise PaperAccountValidationError("closed position must have zero availability and cost")
    positions = [item for item in state.positions if item.instrument_id != event.instrument_id]
    if quantity > 0:
        positions.append(PaperPosition(event.instrument_id, quantity, available, cost))
    positions.sort(key=lambda item: item.instrument_id)
    return replace(
        state,
        cash=cash,
        positions=tuple(positions),
        latest_valuation=None,
        **common,
    )


def _apply_valuation(
    state: PaperAccountState,
    event: RecordPaperValuation,
    common: dict[str, object],
) -> PaperAccountState:
    expected = {position.instrument_id for position in state.positions}
    received = {mark.instrument_id for mark in event.marks}
    if received != expected:
        raise PaperAccountValidationError("valuation must mark every current position exactly once")
    quantity = {position.instrument_id: position.quantity for position in state.positions}
    market_value = sum(
        (mark.price * Decimal(quantity[mark.instrument_id]) for mark in event.marks),
        start=Decimal("0"),
    )
    valuation = PaperValuation(
        valuation_id=event.metadata.event_id,
        valuation_time=event.metadata.event_time,
        available_time=event.metadata.available_time,
        cash=state.cash,
        position_market_value=market_value,
        nav=state.cash + market_value,
        marks=event.marks,
    )
    return replace(state, latest_valuation=valuation, **common)


def _apply_status(
    state: PaperAccountState,
    event: ChangePaperAccountStatus,
    common: dict[str, object],
) -> PaperAccountState:
    allowed: dict[PaperAccountStatus, set[PaperAccountStatus]] = {
        PaperAccountStatus.ACTIVE: {PaperAccountStatus.SUSPENDED, PaperAccountStatus.CLOSED},
        PaperAccountStatus.SUSPENDED: {PaperAccountStatus.ACTIVE, PaperAccountStatus.CLOSED},
        PaperAccountStatus.CLOSED: set(),
    }
    if event.target_status not in allowed[state.status]:
        raise PaperAccountLifecycleError(
            f"illegal account status transition {state.status.value} -> {event.target_status.value}"
        )
    if event.target_status is PaperAccountStatus.CLOSED and state.positions:
        raise PaperAccountLifecycleError("positions must be empty before account closure")
    return replace(state, status=event.target_status, **common)


class PaperAccountEventStore(Protocol):
    def load(self, account_id: str) -> PaperAccountTape | None: ...

    def append(
        self,
        event: PaperAccountEvent,
        *,
        expected_tape_digest: str,
    ) -> PaperAccountTape: ...


class InMemoryPaperAccountEventStore:
    """Deterministic optimistic-concurrency store for tests and adapters."""

    def __init__(self) -> None:
        self._tapes: dict[str, PaperAccountTape] = {}

    def load(self, account_id: str) -> PaperAccountTape | None:
        return self._tapes.get(account_id)

    def append(
        self,
        event: PaperAccountEvent,
        *,
        expected_tape_digest: str,
    ) -> PaperAccountTape:
        account_id = event.metadata.account_id
        current = self._tapes.get(account_id, PaperAccountTape(account_id))
        duplicate = next(
            (
                candidate
                for candidate in current.events
                if candidate.metadata.event_id == event.metadata.event_id
            ),
            None,
        )
        if duplicate is not None:
            if event_digest(duplicate) == event_digest(event):
                return current
            raise PaperAccountEventConflictError("event_id was reused with different content")
        if current.tape_digest != expected_tape_digest:
            raise PaperAccountConcurrencyError("expected tape digest does not match current tape")
        updated = append_account_event(current, event)
        self._tapes[account_id] = updated
        return updated
