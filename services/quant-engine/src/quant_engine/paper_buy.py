"""Prepare a fully validated buy-only paper transaction without mutating storage."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256

from ashare_contracts import PaperAllocationDecision as AllocationContract
from paper_core import (
    ApplyPaperFill,
    CreatePaperOrder,
    PaperAccountTape,
    PaperAllocationDecision,
    PaperBookPosition,
    PaperEventMetadata,
    PaperExecutionMetadata,
    PaperExecutionTape,
    PaperIntentSide,
    PaperOrderStatus,
    PaperReconciliationResult,
    PaperRiskDecision,
    PaperRiskEnvironment,
    PaperSettlementBook,
    PaperValuationMark,
    PositionTransferReason,
    ReconciliationHealth,
    RecordPaperValuation,
    SubmitPaperOrder,
    TransferPaperPosition,
    ValuationMarkSource,
    append_account_event,
    append_execution_event,
    create_risk_check_event,
    evaluate_pretrade_risk,
    project_execution_book,
    reconcile_paper_books,
    replay_account,
    replay_execution,
)

from .paper_risk_preview import PREVIEW_RISK_POLICY, validate_allocation_snapshot

Mark = tuple[Decimal, datetime, str]


@dataclass(frozen=True)
class ControlledBuyPlan:
    account: PaperAccountTape
    execution: PaperExecutionTape
    allocation: PaperAllocationDecision
    risk: PaperRiskDecision
    reconciliation: PaperReconciliationResult
    marks: dict[str, Mark]


def buy_request_id(snapshot: AllocationContract) -> str:
    return f"buy:{snapshot.decision_id}"


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def build_buy_plan(
    tape: PaperAccountTape,
    execution: PaperExecutionTape,
    opening: PaperSettlementBook,
    marks: Mapping[str, Mark],
    snapshot: AllocationContract,
    now: datetime,
) -> ControlledBuyPlan:
    with localcontext() as context:
        context.prec = 128
        context.rounding = ROUND_HALF_EVEN
        return _build(tape, execution, opening, marks, snapshot, now)


def _build(
    tape: PaperAccountTape,
    execution: PaperExecutionTape,
    opening: PaperSettlementBook,
    marks: Mapping[str, Mark],
    snapshot: AllocationContract,
    now: datetime,
) -> ControlledBuyPlan:
    account = replay_account(tape)
    if account is None:
        raise ValueError("请先创建模拟账户")
    allocation = validate_allocation_snapshot(account, snapshot, now)
    intent = allocation.intents[0]
    if intent.side is not PaperIntentSide.BUY:
        raise ValueError("当前仅支持受控模拟买入")
    if len(format(intent.reference_price.normalize(), "f").partition(".")[2]) > 8:
        raise ValueError("模拟买入价格最多支持 8 位小数，请重新试算")
    projection = replay_execution(execution)
    if any(
        o.status
        not in {PaperOrderStatus.FILLED, PaperOrderStatus.CANCELLED, PaperOrderStatus.REJECTED}
        for o in projection.orders
    ):
        raise ValueError("存在未结束的模拟订单，请先核对")
    before = reconcile_paper_books(
        project_execution_book(opening, projection, as_of=now),
        PaperSettlementBook(
            account.account_id,
            account.cash,
            tuple(
                PaperBookPosition(p.instrument_id, p.quantity, p.cost_amount)
                for p in account.positions
            ),
            now,
        ),
    )
    if before.status.value != "MATCHED":
        raise ValueError("账簿不一致，停止模拟买入")
    notional = intent.reference_price * intent.quantity
    fee = max(Decimal("1"), (notional * Decimal("0.0003")).quantize(Decimal("0.01")))
    if account.cash < notional + fee:
        raise ValueError("账面现金不足以覆盖假设金额及模拟手续费")
    request_id = buy_request_id(snapshot)

    def execution_meta(current: PaperExecutionTape) -> PaperExecutionMetadata:
        return PaperExecutionMetadata(
            account.account_id,
            _digest(f"{request_id}:execution:{len(current.events)}"),
            len(current.events),
            now,
            now,
            current.last_event_digest,
            "controlled-paper-buy",
            "1.0.0",
        )

    execution = append_execution_event(
        execution, CreatePaperOrder(execution_meta(execution), request_id, intent)
    )
    projection = replay_execution(execution)
    risk = evaluate_pretrade_risk(
        intent,
        account=account,
        execution=projection,
        decision_time=now,
        policy=PREVIEW_RISK_POLICY,
        environment=PaperRiskEnvironment(True, True, ReconciliationHealth(before.status.value)),
    )
    if not risk.allowed:
        raise ValueError("本次模拟买入未通过服务端风险检查")
    order = next(item for item in projection.orders if item.client_order_id == request_id)
    execution = append_execution_event(
        execution,
        create_risk_check_event(
            execution_meta(execution), order=order, execution=projection, decision=risk
        ),
    )
    execution = append_execution_event(
        execution, SubmitPaperOrder(execution_meta(execution), order.order_id)
    )
    evidence = _digest(f"{request_id}:manual-price")
    execution = append_execution_event(
        execution,
        ApplyPaperFill(
            execution_meta(execution),
            order.order_id,
            _digest(f"{request_id}:fill"),
            intent.quantity,
            intent.reference_price,
            fee,
            evidence,
        ),
    )

    def account_meta(current: PaperAccountTape) -> PaperEventMetadata:
        return PaperEventMetadata(
            account.account_id,
            _digest(f"{request_id}:account:{len(current.events)}"),
            len(current.events),
            now,
            now,
            current.last_event_digest,
            "controlled-paper-buy",
            "1.0.0",
        )

    tape = append_account_event(
        tape,
        TransferPaperPosition(
            account_meta(tape),
            intent.instrument_id,
            intent.quantity,
            0,
            -(notional + fee),
            notional + fee,
            PositionTransferReason.RECONCILIATION,
            "人工假设下的模拟买入及手续费入账",
        ),
    )
    next_marks = dict(marks)
    next_marks[intent.instrument_id] = (intent.reference_price, now, evidence)
    state = replay_account(tape)
    assert state is not None
    valuation = tuple(
        PaperValuationMark(
            p.instrument_id,
            *next_marks[p.instrument_id][:2],
            next_marks[p.instrument_id][1],
            ValuationMarkSource.EXECUTABLE_QUOTE,
            "controlled-manual-price-v1",
            next_marks[p.instrument_id][2],
        )
        for p in state.positions
    )
    tape = append_account_event(tape, RecordPaperValuation(account_meta(tape), valuation))
    state = replay_account(tape)
    assert state is not None
    # Old journal commands retain their historical decimal context. Refuse a new
    # transaction if its precise result would change under that replay context.
    with localcontext() as compatibility:
        compatibility.prec = 28
        compatible = replay_account(tape)
        normalized = replace(state)
    if compatible != normalized:
        raise ValueError("金额精度超出当前模拟成交支持范围，请减少价格小数位")
    after = reconcile_paper_books(
        project_execution_book(opening, replay_execution(execution), as_of=now),
        PaperSettlementBook(
            state.account_id,
            state.cash,
            tuple(
                PaperBookPosition(p.instrument_id, p.quantity, p.cost_amount)
                for p in state.positions
            ),
            now,
        ),
    )
    if after.status.value != "MATCHED" or replay_execution(execution).alerts:
        raise ValueError("模拟成交未通过入账核对")
    return ControlledBuyPlan(tape, execution, allocation, risk, after, next_marks)
