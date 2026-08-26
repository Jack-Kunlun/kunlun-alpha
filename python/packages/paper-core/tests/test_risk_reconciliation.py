from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from paper_core import (
    ZERO_DIGEST,
    ApplyPaperFill,
    BookDiffKind,
    CreatePaperOrder,
    InMemoryPaperAccountEventStore,
    OpenPaperAccount,
    PaperBookPosition,
    PaperEventMetadata,
    PaperExecutionMetadata,
    PaperExecutionTape,
    PaperIntentSide,
    PaperOrderIntent,
    PaperOrderStatus,
    PaperRiskEnvironment,
    PaperRiskPolicy,
    PaperSettlementBook,
    ReconciliationHealth,
    ReconciliationStatus,
    RiskCheckCode,
    RiskCheckStatus,
    SubmitPaperOrder,
    append_execution_event,
    create_risk_check_event,
    evaluate_pretrade_risk,
    paper_order_id,
    project_execution_book,
    reconcile_paper_books,
    replay_account,
    replay_execution,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACCOUNT_ID = "a" * 64
T0 = datetime(2026, 8, 26, 10, tzinfo=SHANGHAI)


def _account():
    event = OpenPaperAccount(
        PaperEventMetadata(
            ACCOUNT_ID,
            "1" * 64,
            0,
            T0 - timedelta(hours=1),
            T0 - timedelta(hours=1),
            ZERO_DIGEST,
            "risk-test",
            "1.0.0",
        ),
        "local-research-user",
        "研究模拟账户",
        Decimal("100000"),
    )
    store = InMemoryPaperAccountEventStore()
    state = replay_account(store.append(event, expected_tape_digest=ZERO_DIGEST))
    assert state is not None
    return state


def _intent(*, quantity: int = 100, price: str = "100") -> PaperOrderIntent:
    return PaperOrderIntent(
        "b" * 64,
        ACCOUNT_ID,
        ("signal-risk",),
        "600519.SH",
        T0,
        PaperIntentSide.BUY,
        quantity,
        Decimal(price),
        quantity,
        Decimal("0.2"),
        "allocation",
        "1.0.0",
        "c" * 64,
        "risk fixture",
    )


def _metadata(tape: PaperExecutionTape, event_id: str, offset: int) -> PaperExecutionMetadata:
    when = T0 + timedelta(seconds=offset)
    return PaperExecutionMetadata(
        ACCOUNT_ID,
        event_id,
        len(tape.events),
        when,
        when,
        tape.last_event_digest,
        "risk-test",
        "1.0.0",
    )


def _created(intent: PaperOrderIntent | None = None) -> tuple[PaperExecutionTape, str]:
    tape = PaperExecutionTape(ACCOUNT_ID)
    tape = append_execution_event(
        tape,
        CreatePaperOrder(_metadata(tape, "2" * 64, 0), "risk-client-order", intent or _intent()),
    )
    return tape, paper_order_id(ACCOUNT_ID, "risk-client-order")


def _policy(maximum_order_notional: str = "50000") -> PaperRiskPolicy:
    return PaperRiskPolicy(
        "paper-risk",
        "1.0.0",
        Decimal(maximum_order_notional),
        Decimal("0.3"),
        Decimal("200000"),
        10,
        Decimal("10000"),
    )


def _environment(*, connected: bool = True) -> PaperRiskEnvironment:
    return PaperRiskEnvironment(True, connected, ReconciliationHealth.MATCHED)


def test_limit_breach_is_bound_to_a_rejected_order_check() -> None:
    intent = _intent(quantity=200, price="100")
    tape, _ = _created(intent)
    projection = replay_execution(tape)
    decision = evaluate_pretrade_risk(
        intent,
        account=_account(),
        execution=projection,
        decision_time=T0,
        policy=_policy("10000"),
        environment=_environment(),
    )
    notional = next(
        check for check in decision.checks if check.code is RiskCheckCode.ORDER_NOTIONAL_LIMIT
    )
    assert notional.status is RiskCheckStatus.FAIL
    check_event = create_risk_check_event(
        _metadata(tape, "3" * 64, 1),
        order=projection.orders[0],
        execution=projection,
        decision=decision,
    )
    order = replay_execution(append_execution_event(tape, check_event)).orders[0]
    assert order.status is PaperOrderStatus.REJECTED
    assert order.risk_decision_id == decision.decision_id


def test_execution_disconnect_fails_closed_before_submission() -> None:
    intent = _intent()
    tape, _ = _created(intent)
    projection = replay_execution(tape)
    decision = evaluate_pretrade_risk(
        intent,
        account=_account(),
        execution=projection,
        decision_time=T0,
        policy=_policy(),
        environment=_environment(connected=False),
    )
    assert decision.allowed is False
    connection = next(
        check for check in decision.checks if check.code is RiskCheckCode.EXECUTION_CONNECTED
    )
    assert connection.status is RiskCheckStatus.FAIL


def _filled_projection():
    intent = _intent()
    tape, order_id = _created(intent)
    projection = replay_execution(tape)
    decision = evaluate_pretrade_risk(
        intent,
        account=_account(),
        execution=projection,
        decision_time=T0,
        policy=_policy(),
        environment=_environment(),
    )
    tape = append_execution_event(
        tape,
        create_risk_check_event(
            _metadata(tape, "3" * 64, 1),
            order=projection.orders[0],
            execution=projection,
            decision=decision,
        ),
    )
    tape = append_execution_event(tape, SubmitPaperOrder(_metadata(tape, "4" * 64, 2), order_id))
    fill = ApplyPaperFill(
        _metadata(tape, "5" * 64, 3),
        order_id,
        "d" * 64,
        100,
        Decimal("100"),
        Decimal("1"),
        "reconciliation-liquidity",
    )
    tape = append_execution_event(tape, fill)
    assert append_execution_event(tape, fill) is tape
    return replay_execution(tape)


def test_duplicate_fill_is_counted_once_and_matching_books_reconcile() -> None:
    execution = _filled_projection()
    cutoff = T0 + timedelta(seconds=3)
    expected = project_execution_book(
        PaperSettlementBook(ACCOUNT_ID, Decimal("100000"), (), cutoff), execution, as_of=cutoff
    )
    observed = PaperSettlementBook(
        ACCOUNT_ID,
        Decimal("89999"),
        (PaperBookPosition("600519.SH", 100, Decimal("10001")),),
        cutoff,
    )
    result = reconcile_paper_books(expected, observed)
    assert result.status is ReconciliationStatus.MATCHED
    assert result.duplicate_fill_count == 0
    assert result.diffs == ()


def test_cash_and_position_book_drift_are_reported_independently() -> None:
    execution = _filled_projection()
    cutoff = T0 + timedelta(seconds=3)
    expected = project_execution_book(
        PaperSettlementBook(ACCOUNT_ID, Decimal("100000"), (), cutoff), execution, as_of=cutoff
    )
    observed = PaperSettlementBook(
        ACCOUNT_ID, Decimal("90000"), (PaperBookPosition("600519.SH", 99, Decimal("9999")),), cutoff
    )
    result = reconcile_paper_books(expected, observed)
    assert result.status is ReconciliationStatus.DRIFTED
    assert {diff.kind for diff in result.diffs} == {
        BookDiffKind.CASH,
        BookDiffKind.POSITION_QUANTITY,
        BookDiffKind.POSITION_COST,
    }
