from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from paper_core import (
    AcknowledgePaperCancel,
    ApplyPaperFill,
    CheckPaperOrder,
    CreatePaperOrder,
    PaperAuditOutcome,
    PaperExecutionMetadata,
    PaperExecutionTape,
    PaperIntentSide,
    PaperOrderAlertCode,
    PaperOrderIntent,
    PaperOrderStatus,
    RequestPaperCancel,
    SubmitPaperOrder,
    append_execution_event,
    paper_order_id,
    replay_execution,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACCOUNT_ID = "a" * 64
T0 = datetime(2026, 8, 26, 10, tzinfo=SHANGHAI)


def _intent(intent_id: str = "b" * 64, quantity: int = 200) -> PaperOrderIntent:
    return PaperOrderIntent(
        intent_id=intent_id,
        account_id=ACCOUNT_ID,
        source_signal_ids=("signal-1",),
        instrument_id="600519.SH",
        decision_time=T0,
        side=PaperIntentSide.BUY,
        quantity=quantity,
        reference_price=Decimal("100"),
        target_quantity=quantity,
        target_weight=Decimal("0.2"),
        policy_id="paper-allocation",
        policy_version="1.0.0",
        policy_digest="c" * 64,
        explanation="test paper intent",
    )


def _metadata(tape: PaperExecutionTape, event_id: str, offset: int) -> PaperExecutionMetadata:
    when = T0 + timedelta(seconds=offset)
    return PaperExecutionMetadata(
        account_id=ACCOUNT_ID,
        event_id=event_id,
        sequence=len(tape.events),
        event_time=when,
        available_time=when,
        previous_event_digest=tape.last_event_digest,
        source_id="paper-execution-test",
        source_version="1.0.0",
    )


def _created(client_order_id: str = "client-order-1") -> tuple[PaperExecutionTape, str]:
    tape = PaperExecutionTape(ACCOUNT_ID)
    tape = append_execution_event(
        tape,
        CreatePaperOrder(_metadata(tape, "1" * 64, 0), client_order_id, _intent()),
    )
    return tape, paper_order_id(ACCOUNT_ID, client_order_id)


def _submitted() -> tuple[PaperExecutionTape, str]:
    tape, order_id = _created()
    tape = append_execution_event(
        tape,
        CheckPaperOrder(
            _metadata(tape, "2" * 64, 1),
            order_id,
            True,
            None,
            "检查通过",
            "d" * 64,
            "e" * 64,
        ),
    )
    tape = append_execution_event(
        tape,
        SubmitPaperOrder(_metadata(tape, "3" * 64, 2), order_id),
    )
    return tape, order_id


def test_create_check_submit_partial_fill_and_fill_replay_exactly() -> None:
    tape, order_id = _submitted()
    tape = append_execution_event(
        tape,
        ApplyPaperFill(
            _metadata(tape, "4" * 64, 3),
            order_id,
            "d" * 64,
            100,
            Decimal("100"),
            Decimal("1"),
            "liquidity-1",
        ),
    )
    partial = replay_execution(tape).orders[0]
    assert partial.status is PaperOrderStatus.PARTIALLY_FILLED
    assert partial.remaining_quantity == 100

    tape = append_execution_event(
        tape,
        ApplyPaperFill(
            _metadata(tape, "5" * 64, 4),
            order_id,
            "e" * 64,
            100,
            Decimal("102"),
            Decimal("1.5"),
            "liquidity-2",
        ),
    )
    projection = replay_execution(tape)
    order = projection.orders[0]
    assert order.status is PaperOrderStatus.FILLED
    assert order.filled_quantity == 200
    assert order.average_fill_price == Decimal("101")
    assert order.total_fees == Decimal("2.5")
    assert len(projection.audits) == 5
    assert projection.payload()["dataMeaning"] == "SIMULATED_EXECUTION_NO_BROKER_PATH"


def test_client_order_id_and_fill_retries_are_idempotent_but_conflicts_alert() -> None:
    tape, order_id = _created()
    duplicate = CreatePaperOrder(
        _metadata(tape, "6" * 64, 1),
        "client-order-1",
        _intent(),
    )
    tape = append_execution_event(tape, duplicate)
    projection = replay_execution(tape)
    assert len(projection.orders) == 1
    assert projection.audits[-1].outcome is PaperAuditOutcome.DUPLICATE

    conflicting = CreatePaperOrder(
        _metadata(tape, "7" * 64, 2),
        "client-order-1",
        _intent("f" * 64),
    )
    tape = append_execution_event(tape, conflicting)
    projection = replay_execution(tape)
    assert projection.orders[0].order_id == order_id
    assert projection.alerts[-1].code is PaperOrderAlertCode.IDEMPOTENCY_CONFLICT


def test_out_of_order_submit_is_rejected_and_alerted_without_state_change() -> None:
    tape, _ = _created()
    order_id = replay_execution(tape).orders[0].order_id
    tape = append_execution_event(
        tape,
        SubmitPaperOrder(_metadata(tape, "8" * 64, 1), order_id),
    )
    projection = replay_execution(tape)

    assert projection.orders[0].status is PaperOrderStatus.CREATED
    assert projection.audits[-1].outcome is PaperAuditOutcome.REJECTED
    assert projection.alerts[-1].code is PaperOrderAlertCode.ILLEGAL_ORDER_TRANSITION


def test_fill_wins_cancel_race_and_late_cancel_ack_is_rejected() -> None:
    tape, order_id = _submitted()
    tape = append_execution_event(
        tape,
        RequestPaperCancel(_metadata(tape, "9" * 64, 3), order_id, "用户撤单"),
    )
    tape = append_execution_event(
        tape,
        ApplyPaperFill(
            _metadata(tape, "a" * 64, 4),
            order_id,
            "b" * 64,
            200,
            Decimal("100"),
            Decimal("2"),
            "race-fill",
        ),
    )
    tape = append_execution_event(
        tape,
        AcknowledgePaperCancel(_metadata(tape, "c" * 64, 5), order_id),
    )
    projection = replay_execution(tape)

    assert projection.orders[0].status is PaperOrderStatus.FILLED
    assert projection.alerts[-1].code is PaperOrderAlertCode.ILLEGAL_ORDER_TRANSITION


def test_partial_fill_during_cancel_pending_preserves_fill_before_cancellation() -> None:
    tape, order_id = _submitted()
    tape = append_execution_event(
        tape,
        RequestPaperCancel(_metadata(tape, "9" * 64, 3), order_id, "用户撤单"),
    )
    tape = append_execution_event(
        tape,
        ApplyPaperFill(
            _metadata(tape, "a" * 64, 4),
            order_id,
            "b" * 64,
            100,
            Decimal("100"),
            Decimal("1"),
            "partial-race-fill",
        ),
    )
    assert replay_execution(tape).orders[0].status is PaperOrderStatus.CANCEL_PENDING
    tape = append_execution_event(
        tape,
        AcknowledgePaperCancel(_metadata(tape, "c" * 64, 5), order_id),
    )
    order = replay_execution(tape).orders[0]
    assert order.status is PaperOrderStatus.CANCELLED
    assert order.filled_quantity == 100
    assert order.remaining_quantity == 100
