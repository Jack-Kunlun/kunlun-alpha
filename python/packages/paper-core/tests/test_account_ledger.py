from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from paper_core import (
    ZERO_DIGEST,
    ChangePaperAccountStatus,
    InMemoryPaperAccountEventStore,
    OpenPaperAccount,
    PaperAccountConcurrencyError,
    PaperAccountEventConflictError,
    PaperAccountLifecycleError,
    PaperAccountStatus,
    PaperAccountTape,
    PaperAccountValidationError,
    PaperEventMetadata,
    PaperValuationMark,
    PositionTransferReason,
    RecordPaperValuation,
    TransferPaperPosition,
    ValuationMarkSource,
    event_digest,
    replay_account,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACCOUNT_ID = "a" * 64


def _time(hour: int) -> datetime:
    return datetime(2026, 8, 26, hour, tzinfo=SHANGHAI)


def _metadata(
    event_id: str,
    sequence: int,
    when: datetime,
    previous: str = ZERO_DIGEST,
) -> PaperEventMetadata:
    return PaperEventMetadata(
        account_id=ACCOUNT_ID,
        event_id=event_id,
        sequence=sequence,
        event_time=when,
        available_time=when,
        previous_event_digest=previous,
        source_id="paper-account-test",
        source_version="1.0.0",
    )


def _open() -> OpenPaperAccount:
    return OpenPaperAccount(
        metadata=_metadata("1" * 64, 0, _time(9)),
        owner_ref="local-research-user",
        name="研究模拟账户",
        initial_capital=Decimal("100000"),
    )


def _opened_store() -> tuple[InMemoryPaperAccountEventStore, PaperAccountTape]:
    store = InMemoryPaperAccountEventStore()
    tape = store.append(_open(), expected_tape_digest=ZERO_DIGEST)
    return store, tape


def test_account_opening_is_immutable_and_reconstructable_before_and_after_visibility() -> None:
    store, tape = _opened_store()
    assert replay_account(tape, as_of=_time(8)) is None

    state = replay_account(tape, as_of=_time(9))
    assert state is not None
    assert state.cash == Decimal("100000")
    assert state.initial_capital == Decimal("100000")
    assert state.positions == ()
    assert state.execution_capability == "PAPER_ONLY"
    assert state.snapshot(_time(10))["dataMeaning"] == "SIMULATION_ONLY_NO_BROKER_PATH"
    with pytest.raises(FrozenInstanceError):
        state.cash = Decimal("0")  # type: ignore[misc]
    assert store.load(ACCOUNT_ID) == tape


def test_balanced_position_transfer_and_point_in_time_valuation_use_decimal_nav() -> None:
    store, opened = _opened_store()
    transfer = TransferPaperPosition(
        metadata=_metadata("2" * 64, 1, _time(10), opened.last_event_digest),
        instrument_id="600519.SH",
        quantity_delta=100,
        available_quantity_delta=100,
        cash_delta=Decimal("-150000") + Decimal("100000"),
        position_cost_delta=Decimal("50000"),
        reason=PositionTransferReason.SIMULATION_SEED,
        explanation="可审计的模拟初始持仓",
    )
    positioned = store.append(transfer, expected_tape_digest=opened.tape_digest)
    state_at_open = replay_account(positioned, as_of=_time(9))
    state_at_position = replay_account(positioned, as_of=_time(10))
    assert state_at_open is not None and state_at_open.positions == ()
    assert state_at_position is not None
    assert state_at_position.cash == Decimal("50000")
    assert state_at_position.positions[0].average_cost == Decimal("500")
    assert state_at_position.latest_valuation is None

    mark = PaperValuationMark(
        instrument_id="600519.SH",
        price=Decimal("600.125"),
        mark_time=_time(11),
        available_time=_time(11),
        source=ValuationMarkSource.EXECUTABLE_QUOTE,
        source_version="quote-v1",
        evidence_id="quote-600519-20260826",
    )
    valuation = RecordPaperValuation(
        metadata=_metadata("3" * 64, 2, _time(11), positioned.last_event_digest),
        marks=(mark,),
    )
    valued = store.append(valuation, expected_tape_digest=positioned.tape_digest)
    state = replay_account(valued)
    assert state is not None and state.latest_valuation is not None
    assert state.latest_valuation.position_market_value == Decimal("60012.500")
    assert state.latest_valuation.nav == Decimal("110012.500")
    assert state.snapshot(_time(12))["latestValuation"] is not None


def test_duplicate_is_idempotent_but_conflict_and_stale_append_fail_closed() -> None:
    store, opened = _opened_store()
    assert store.append(_open(), expected_tape_digest="f" * 64) is opened

    conflicting = OpenPaperAccount(
        metadata=_metadata("1" * 64, 0, _time(9)),
        owner_ref="local-research-user",
        name="changed",
        initial_capital=Decimal("100000"),
    )
    with pytest.raises(PaperAccountEventConflictError):
        store.append(conflicting, expected_tape_digest=opened.tape_digest)

    status = ChangePaperAccountStatus(
        metadata=_metadata("4" * 64, 1, _time(10), opened.last_event_digest),
        target_status=PaperAccountStatus.SUSPENDED,
        reason="暂停研究",
    )
    with pytest.raises(PaperAccountConcurrencyError):
        store.append(status, expected_tape_digest=ZERO_DIGEST)


def test_lifecycle_is_explicit_and_closed_account_cannot_mutate() -> None:
    store, opened = _opened_store()
    suspended = store.append(
        ChangePaperAccountStatus(
            metadata=_metadata("4" * 64, 1, _time(10), opened.last_event_digest),
            target_status=PaperAccountStatus.SUSPENDED,
            reason="暂停研究",
        ),
        expected_tape_digest=opened.tape_digest,
    )
    resumed = store.append(
        ChangePaperAccountStatus(
            metadata=_metadata("5" * 64, 2, _time(11), suspended.last_event_digest),
            target_status=PaperAccountStatus.ACTIVE,
            reason="恢复研究",
        ),
        expected_tape_digest=suspended.tape_digest,
    )
    closed = store.append(
        ChangePaperAccountStatus(
            metadata=_metadata("6" * 64, 3, _time(12), resumed.last_event_digest),
            target_status=PaperAccountStatus.CLOSED,
            reason="结束模拟",
        ),
        expected_tape_digest=resumed.tape_digest,
    )
    state = replay_account(closed)
    assert state is not None and state.status is PaperAccountStatus.CLOSED

    after_close = RecordPaperValuation(
        metadata=_metadata("7" * 64, 4, _time(13), closed.last_event_digest),
        marks=(),
    )
    with pytest.raises(PaperAccountLifecycleError):
        store.append(after_close, expected_tape_digest=closed.tape_digest)


def test_unbalanced_money_float_values_and_future_marks_are_rejected() -> None:
    opened = _open()
    with pytest.raises(PaperAccountValidationError, match="balance"):
        TransferPaperPosition(
            metadata=_metadata("2" * 64, 1, _time(10), event_digest(opened)),
            instrument_id="600519.SH",
            quantity_delta=100,
            available_quantity_delta=100,
            cash_delta=Decimal("-100"),
            position_cost_delta=Decimal("99"),
            reason=PositionTransferReason.RECONCILIATION,
            explanation="invalid",
        )
    with pytest.raises(PaperAccountValidationError, match="Decimal"):
        OpenPaperAccount(
            metadata=_metadata("8" * 64, 0, _time(9)),
            owner_ref="local-research-user",
            name="invalid",
            initial_capital=100.0,  # type: ignore[arg-type]
        )
    future_mark = PaperValuationMark(
        instrument_id="600519.SH",
        price=Decimal("10"),
        mark_time=_time(11),
        available_time=_time(12),
        source=ValuationMarkSource.MARKET_CLOSE,
        source_version="close-v1",
        evidence_id="future-mark",
    )
    with pytest.raises(PaperAccountValidationError, match="future-available"):
        RecordPaperValuation(
            metadata=_metadata("9" * 64, 1, _time(11), event_digest(opened)),
            marks=(future_mark,),
        )
