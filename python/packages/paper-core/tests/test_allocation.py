from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from paper_core import (
    ZERO_DIGEST,
    AllocationRejectionReason,
    InMemoryPaperAccountEventStore,
    OpenPaperAccount,
    PaperAllocationPolicy,
    PaperEventMetadata,
    PaperIntentSide,
    PaperMarketQuote,
    PaperValuationMark,
    PositionTransferReason,
    RecordPaperValuation,
    TransferPaperPosition,
    ValuationMarkSource,
    allocate_signals,
    replay_account,
)
from quant_core.strategy import Signal, SignalDirection

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACCOUNT_ID = "a" * 64
DECISION_TIME = datetime(2026, 8, 26, 10, tzinfo=SHANGHAI)


def _account():
    opened = OpenPaperAccount(
        metadata=PaperEventMetadata(
            account_id=ACCOUNT_ID,
            event_id="1" * 64,
            sequence=0,
            event_time=DECISION_TIME.replace(hour=9),
            available_time=DECISION_TIME.replace(hour=9),
            previous_event_digest=ZERO_DIGEST,
            source_id="allocation-test",
            source_version="1.0.0",
        ),
        owner_ref="local-research-user",
        name="研究模拟账户",
        initial_capital=Decimal("100000"),
    )
    store = InMemoryPaperAccountEventStore()
    state = replay_account(store.append(opened, expected_tape_digest=ZERO_DIGEST))
    assert state is not None
    return state


def _invested_account():
    opened_event = OpenPaperAccount(
        metadata=PaperEventMetadata(
            account_id=ACCOUNT_ID,
            event_id="1" * 64,
            sequence=0,
            event_time=DECISION_TIME.replace(hour=9),
            available_time=DECISION_TIME.replace(hour=9),
            previous_event_digest=ZERO_DIGEST,
            source_id="allocation-test",
            source_version="1.0.0",
        ),
        owner_ref="local-research-user",
        name="研究模拟账户",
        initial_capital=Decimal("100000"),
    )
    store = InMemoryPaperAccountEventStore()
    opened = store.append(opened_event, expected_tape_digest=ZERO_DIGEST)
    transferred = store.append(
        TransferPaperPosition(
            metadata=PaperEventMetadata(
                account_id=ACCOUNT_ID,
                event_id="2" * 64,
                sequence=1,
                event_time=DECISION_TIME.replace(hour=9, minute=15),
                available_time=DECISION_TIME.replace(hour=9, minute=15),
                previous_event_digest=opened.last_event_digest,
                source_id="allocation-test",
                source_version="1.0.0",
            ),
            instrument_id="000001.SZ",
            quantity_delta=90,
            available_quantity_delta=90,
            cash_delta=Decimal("-90000"),
            position_cost_delta=Decimal("90000"),
            reason=PositionTransferReason.SIMULATION_SEED,
            explanation="模拟既有仓位",
        ),
        expected_tape_digest=opened.tape_digest,
    )
    valued = store.append(
        RecordPaperValuation(
            metadata=PaperEventMetadata(
                account_id=ACCOUNT_ID,
                event_id="3" * 64,
                sequence=2,
                event_time=DECISION_TIME.replace(hour=9, minute=30),
                available_time=DECISION_TIME.replace(hour=9, minute=30),
                previous_event_digest=transferred.last_event_digest,
                source_id="allocation-test",
                source_version="1.0.0",
            ),
            marks=(
                PaperValuationMark(
                    instrument_id="000001.SZ",
                    price=Decimal("1000"),
                    mark_time=DECISION_TIME.replace(hour=9, minute=30),
                    available_time=DECISION_TIME.replace(hour=9, minute=30),
                    source=ValuationMarkSource.EXECUTABLE_QUOTE,
                    source_version="quote-v1",
                    evidence_id="quote-existing-position",
                ),
            ),
        ),
        expected_tape_digest=transferred.tape_digest,
    )
    state = replay_account(valued)
    assert state is not None
    return state


def _signal(
    signal_id: str,
    *,
    direction: SignalDirection = SignalDirection.LONG,
    score: str = "1",
    confidence: str = "1",
    instrument_id: str = "600519.SH",
) -> Signal:
    return Signal(
        signal_id=signal_id,
        schema_version="signal-v1",
        strategy_id="allocation-test",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        entity_id=instrument_id,
        decision_time=DECISION_TIME,
        data_cutoff_time=DECISION_TIME,
        direction=direction,
        score=Decimal(score),
        confidence=Decimal(confidence),
        horizon_sessions=5,
        rationale="test signal",
        input_snapshot_id="snapshot-1",
        input_snapshot_version="1.0.0",
        evidence_ids=(f"evidence-{signal_id}",),
    )


def _quote(price: str = "333") -> PaperMarketQuote:
    return PaperMarketQuote(
        instrument_id="600519.SH",
        price=Decimal(price),
        observed_time=DECISION_TIME,
        available_time=DECISION_TIME,
        lot_size=100,
        source_version="quote-v1",
        evidence_id="quote-600519",
    )


def _policy(
    *,
    maximum_position_weight: str = "0.5",
    maximum_total_weight: str = "0.8",
    cash_buffer_weight: str = "0",
) -> PaperAllocationPolicy:
    return PaperAllocationPolicy(
        policy_id="paper-allocation",
        policy_version="1.0.0",
        maximum_position_weight=Decimal(maximum_position_weight),
        maximum_total_weight=Decimal(maximum_total_weight),
        cash_buffer_weight=Decimal(cash_buffer_weight),
        minimum_confidence=Decimal("0.5"),
    )


def test_board_lot_rounding_produces_explainable_paper_only_intent() -> None:
    decision = allocate_signals(
        (_signal("signal-1"),),
        account=_account(),
        quotes=(_quote(),),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )

    assert len(decision.intents) == 1
    intent = decision.intents[0]
    assert intent.side is PaperIntentSide.BUY
    assert intent.quantity == 100
    assert intent.target_quantity == 100
    assert intent.target_weight == Decimal("0.5")
    assert intent.broker_executable is False
    assert intent.execution_capability == "PAPER_ONLY"
    assert "100 股" in intent.explanation
    assert decision.payload()["dataMeaning"] == "INTENT_ONLY_NO_BROKER_PATH"


def test_cash_buffer_rejects_a_target_that_cannot_be_funded() -> None:
    decision = allocate_signals(
        (_signal("signal-cash"),),
        account=_invested_account(),
        quotes=(_quote("100"),),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )

    assert decision.intents == ()
    assert decision.rejections[0].reason is AllocationRejectionReason.INSUFFICIENT_CASH
    assert "可分配现金" in decision.rejections[0].explanation


def test_position_concentration_is_capped_before_quantity_rounding() -> None:
    decision = allocate_signals(
        (_signal("signal-concentration"),),
        account=_account(),
        quotes=(_quote("100"),),
        decision_time=DECISION_TIME,
        policy=_policy(maximum_position_weight="0.2"),
    )

    assert decision.targets[0].target_weight == Decimal("0.2")
    assert decision.intents[0].quantity == 200


def test_conflicting_long_and_short_signals_are_rejected_as_one_group() -> None:
    decision = allocate_signals(
        (
            _signal("signal-long", direction=SignalDirection.LONG),
            _signal("signal-short", direction=SignalDirection.SHORT),
        ),
        account=_account(),
        quotes=(_quote(),),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )

    assert decision.intents == ()
    assert decision.rejections[0].reason is AllocationRejectionReason.CONFLICTING_SIGNALS
    assert decision.rejections[0].source_signal_ids == ("signal-long", "signal-short")


def test_future_quote_and_sub_lot_target_fail_closed_with_specific_reasons() -> None:
    future_quote = PaperMarketQuote(
        instrument_id="600519.SH",
        price=Decimal("100"),
        observed_time=DECISION_TIME,
        available_time=DECISION_TIME.replace(hour=11),
        lot_size=100,
        source_version="quote-v1",
        evidence_id="future-quote",
    )
    future = allocate_signals(
        (_signal("signal-future"),),
        account=_account(),
        quotes=(future_quote,),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert future.rejections[0].reason is AllocationRejectionReason.FUTURE_DATA

    sub_lot = allocate_signals(
        (_signal("signal-small", score="0.01"),),
        account=_account(),
        quotes=(_quote("100"),),
        decision_time=DECISION_TIME,
        policy=_policy(),
    )
    assert sub_lot.intents == ()
    assert sub_lot.rejections[0].reason is AllocationRejectionReason.BOARD_LOT_ROUNDED_TO_ZERO
