"""Verify an allocation snapshot and report risk without enabling execution."""

from datetime import datetime
from decimal import Decimal, localcontext

from ashare_contracts import PaperAllocationDecision as AllocationContract
from ashare_contracts import PaperRiskDecision as RiskContract
from paper_core import (
    PaperAccountState,
    PaperExecutionProjection,
    PaperMarketQuote,
    PaperRiskEnvironment,
    PaperRiskPolicy,
    ReconciliationHealth,
    evaluate_pretrade_risk,
)
from quant_core.strategy import Signal, SignalDirection

from .paper_preview import allocate_preview_inputs


def preview_risk_decision(
    account: PaperAccountState,
    execution: PaperExecutionProjection,
    reconciliation: ReconciliationHealth,
    snapshot: AllocationContract,
    now: datetime,
) -> dict[str, object]:
    if (
        snapshot.account_id != account.account_id
        or snapshot.account_state_digest != account.state_digest
    ):
        raise ValueError("试算基准已变化，请重新试算")
    if len(snapshot.targets) != 1 or len(snapshot.intents) != 1 or snapshot.rejections:
        raise ValueError("请先生成有调整意图的仓位试算")
    if snapshot.decision_time > now:
        raise ValueError("试算时间晚于风险检查时间")
    target = snapshot.targets[0]
    if (
        len(target.source_signal_ids) != 1
        or len(target.reference_price) > 32
        or len(target.target_weight) > 40
    ):
        raise ValueError("试算输入超出支持范围")
    if not 1 <= target.rounding_lot_size <= 10000:
        raise ValueError("试算交易单位超出支持范围")
    identity = target.source_signal_ids[0].root
    signal = Signal(
        signal_id=identity,
        schema_version="signal-v1",
        strategy_id="manual-paper-preview",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        entity_id=target.instrument_id,
        decision_time=snapshot.decision_time,
        data_cutoff_time=snapshot.decision_time,
        direction=SignalDirection.LONG,
        score=Decimal(target.target_weight),
        confidence=Decimal("1"),
        horizon_sessions=5,
        rationale="重新核对既有人工假设试算",
        input_snapshot_id=identity,
        input_snapshot_version="1.0.0",
        evidence_ids=(identity,),
    )
    quote = PaperMarketQuote(
        target.instrument_id,
        Decimal(target.reference_price),
        snapshot.decision_time,
        snapshot.decision_time,
        target.rounding_lot_size,
        "manual-preview-price-v1",
        identity,
    )
    allocation = allocate_preview_inputs(account, signal, quote, snapshot.decision_time)
    rebuilt = AllocationContract.model_validate(allocation.payload())
    if rebuilt.model_dump(by_alias=True, mode="json") != snapshot.model_dump(
        by_alias=True, mode="json"
    ):
        raise ValueError("仓位试算快照与当前计算不一致，请重新试算")
    with localcontext() as context:
        context.prec = 128
        risk = evaluate_pretrade_risk(
            allocation.intents[0],
            account=account,
            execution=execution,
            decision_time=now,
            policy=PaperRiskPolicy(
                "paper-terminal-risk",
                "1.0.0",
                Decimal("100000000"),
                Decimal("0.35"),
                Decimal("1000000000"),
                20,
                Decimal("0"),
            ),
            # The evaluator is running locally; v1 exposes no simulation
            # execution channel. Reconciliation is derived from actual books.
            environment=PaperRiskEnvironment(True, False, reconciliation),
        )
    return RiskContract.model_validate(risk.payload()).model_dump(by_alias=True, mode="json")
