from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import backtest_core as package_api
import backtest_core.portfolio as portfolio_api
import backtest_core.portfolio.accounting as accounting_api
import pytest
from backtest_core.portfolio import (
    ZERO_DIGEST,
    BuyCashReservation,
    BuyCashReservationEvent,
    DuplicateEventConflictError,
    EventMetadata,
    EventOrderError,
    EventPhase,
    InitialCapitalEvent,
    PortfolioState,
    ReservationReleaseEvent,
    apply_portfolio_event,
)
from backtest_core.portfolio.models import PortfolioEvent, PortfolioHistoryRef

SHANGHAI = ZoneInfo("Asia/Shanghai")
PROVENANCE = "1" * 64
CONFIG = "2" * 64


class _PortfolioSource:
    def __init__(self) -> None:
        self.tapes: dict[str, tuple[PortfolioEvent, ...]] = {"portfolio-genesis": ()}
        self.versions: dict[tuple[str, str, int], tuple[PortfolioEvent, ...]] = {}

    def resolve_portfolio_history(
        self, history_ref: PortfolioHistoryRef
    ) -> tuple[PortfolioEvent, ...]:
        tape_id = history_ref.tape_id
        key = (
            tape_id,
            history_ref.expected_event_tape_digest,
            history_ref.expected_event_count,
        )
        return self.versions.get(key, self.tapes.get(tape_id, ()))

    def record(self, history_ref: PortfolioHistoryRef, events: tuple[PortfolioEvent, ...]) -> None:
        key = (
            history_ref.tape_id,
            history_ref.expected_event_tape_digest,
            history_ref.expected_event_count,
        )
        self.versions[key] = events
        self.tapes[history_ref.tape_id] = events

    def apply(self, state: PortfolioState, event: PortfolioEvent) -> PortfolioState:
        previous = self.resolve_portfolio_history(state.history_ref)
        result = apply_portfolio_event(state, event, source=self)
        self.record(result.history_ref, previous + (event,))
        return result


def _time(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 5, day, hour, tzinfo=SHANGHAI)


def _metadata(
    event_id: str,
    when: datetime,
    phase: EventPhase,
    state_digest: str,
    previous_event_digest: str = ZERO_DIGEST,
    sequence: int = 0,
) -> EventMetadata:
    return EventMetadata(
        event_id=event_id,
        logical_time=when,
        event_phase=phase,
        source_id="portfolio-test",
        source_version="1.0.0",
        source_sequence=sequence,
        available_time=when,
        previous_event_digest=previous_event_digest,
        expected_previous_state_digest=state_digest,
        provenance_digest=PROVENANCE,
        config_digest=CONFIG,
    )


def _opened(source: _PortfolioSource, capital: str = "10000") -> PortfolioState:
    state = PortfolioState.empty()
    event = InitialCapitalEvent(
        metadata=_metadata("opening-1", _time(1), EventPhase.OPENING, state.state_digest),
        amount=Decimal(capital),
    )
    return source.apply(state, event)


def _reservation(
    source: _PortfolioSource, state: PortfolioState, amount: str = "6000"
) -> PortfolioState:
    when = _time(2)
    reservation = BuyCashReservation(
        order_id="order-1",
        order_digest="a" * 64,
        fee_schedule_digest="b" * 64,
        artifact_id="artifact-1",
        execution_input_digest="d" * 64,
        policy_id="reserve-policy",
        policy_version="1.0.0",
        policy_digest="c" * 64,
        reservation_logical_time=when,
        maximum_debit=Decimal(amount),
    )
    event = BuyCashReservationEvent(
        metadata=_metadata(
            "reserve-1",
            when,
            EventPhase.RESERVATION,
            state.state_digest,
            state.last_event_digest,
            1,
        ),
        reservation=reservation,
    )
    return source.apply(state, event)


def test_opening_reservation_release_and_double_entry_identity() -> None:
    empty = PortfolioState.empty()
    source = _PortfolioSource()
    opened = _opened(source)
    assert opened.available_cash == Decimal("10000")
    assert opened.frozen_cash == Decimal("0")
    assert opened.book_assets == opened.initial_capital
    assert opened.realized_pnl == Decimal("0")

    reserved = _reservation(source, opened)
    assert reserved.available_cash == Decimal("4000")
    assert reserved.frozen_cash == Decimal("6000")
    assert reserved.frozen_cash == sum(
        item.maximum_debit for item in reserved.active_buy_reservations
    )
    assert reserved.book_assets == reserved.initial_capital

    when = _time(3)
    released = source.apply(
        reserved,
        ReservationReleaseEvent(
            metadata=_metadata(
                "release-1",
                when,
                EventPhase.RESERVATION,
                reserved.state_digest,
                reserved.last_event_digest,
                2,
            ),
            order_id="order-1",
        ),
    )
    assert released.available_cash == Decimal("10000")
    assert released.frozen_cash == Decimal("0")
    assert released.active_buy_reservations == ()
    assert released.book_assets == released.initial_capital
    assert empty.state_digest != released.state_digest


def test_insufficient_cash_is_rejected_before_mutation() -> None:
    source = _PortfolioSource()
    opened = _opened(source, "100")
    reservation = BuyCashReservation(
        order_id="order-too-large",
        order_digest="a" * 64,
        fee_schedule_digest="b" * 64,
        artifact_id="artifact-1",
        execution_input_digest="d" * 64,
        policy_id="reserve-policy",
        policy_version="1.0.0",
        policy_digest="c" * 64,
        reservation_logical_time=_time(2),
        maximum_debit=Decimal("101"),
    )
    with pytest.raises(ValueError, match="available cash"):
        source.apply(
            opened,
            BuyCashReservationEvent(
                metadata=_metadata(
                    "reserve-too-large",
                    _time(2),
                    EventPhase.RESERVATION,
                    opened.state_digest,
                    opened.last_event_digest,
                    1,
                ),
                reservation=reservation,
            ),
        )
    assert opened.available_cash == Decimal("100")
    assert opened.active_buy_reservations == ()


def test_exact_duplicate_is_noop_but_conflicting_duplicate_is_rejected() -> None:
    source = _PortfolioSource()
    opened = _opened(source)
    reservation = BuyCashReservation(
        order_id="duplicate-order",
        order_digest="a" * 64,
        fee_schedule_digest="b" * 64,
        artifact_id="artifact-1",
        execution_input_digest="d" * 64,
        policy_id="reserve-policy",
        policy_version="1.0.0",
        policy_digest="c" * 64,
        reservation_logical_time=_time(2),
        maximum_debit=Decimal("1"),
    )
    event = BuyCashReservationEvent(
        metadata=_metadata(
            "duplicate-opening",
            _time(2),
            EventPhase.RESERVATION,
            opened.state_digest,
            opened.last_event_digest,
            1,
        ),
        reservation=reservation,
    )
    applied = source.apply(opened, event)
    assert apply_portfolio_event(applied, event, source=source) == applied

    conflicting = BuyCashReservationEvent(
        metadata=_metadata(
            "duplicate-opening",
            _time(2),
            EventPhase.RESERVATION,
            applied.state_digest,
            applied.last_event_digest,
            1,
        ),
        reservation=BuyCashReservation(
            order_id="duplicate-order",
            order_digest="a" * 64,
            fee_schedule_digest="b" * 64,
            artifact_id="artifact-1",
            execution_input_digest="d" * 64,
            policy_id="reserve-policy",
            policy_version="1.0.0",
            policy_digest="c" * 64,
            reservation_logical_time=_time(2),
            maximum_debit=Decimal("2"),
        ),
    )
    with pytest.raises(DuplicateEventConflictError):
        apply_portfolio_event(applied, conflicting, source=source)


def test_out_of_order_event_and_forced_nested_digest_mutation_fail_closed() -> None:
    source = _PortfolioSource()
    opened = _opened(source)
    later = _reservation(source, opened)
    earlier = InitialCapitalEvent(
        metadata=_metadata(
            "earlier",
            _time(1, 10),
            EventPhase.OPENING,
            later.state_digest,
            later.last_event_digest,
            99,
        ),
        amount=Decimal("1"),
    )
    with pytest.raises(EventOrderError):
        apply_portfolio_event(later, earlier, source=source)

    object.__setattr__(later.active_buy_reservations[0], "maximum_debit", Decimal("1"))
    with pytest.raises(ValueError, match="forged"):
        apply_portfolio_event(
            later,
            ReservationReleaseEvent(
                metadata=_metadata(
                    "release-forged",
                    _time(4),
                    EventPhase.RESERVATION,
                    later.state_digest,
                    later.last_event_digest,
                    3,
                ),
                order_id="order-1",
            ),
            source=source,
        )


def test_unchecked_event_application_is_private_and_never_a_public_export() -> None:
    assert not hasattr(accounting_api, "apply_portfolio_event_unchecked")
    assert "apply_portfolio_event_unchecked" not in getattr(accounting_api, "__all__", ())
    assert "apply_portfolio_event_unchecked" not in portfolio_api.__all__
    assert "apply_portfolio_event_unchecked" not in package_api.__all__
    assert portfolio_api.apply_portfolio_event is apply_portfolio_event
