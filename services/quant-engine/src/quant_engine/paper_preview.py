"""Read-only manual scenario allocation; no order, journal or broker dependency."""

from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256

from ashare_contracts import PaperAllocationDecision as AllocationContract
from ashare_contracts import PaperTerminalSimulationCommand
from paper_core import (
    PaperAccountState,
    PaperAllocationDecision,
    PaperAllocationPolicy,
    PaperMarketQuote,
    allocate_signals,
)
from quant_core.strategy import Signal, SignalDirection

MAX_SAFE_QUANTITY = 2**53 - 1


def preview_allocation(
    account: PaperAccountState, command: PaperTerminalSimulationCommand, now: datetime
) -> dict[str, object]:
    identity = sha256(command.model_dump_json(by_alias=True).encode()).hexdigest()
    evidence = sha256(f"manual-preview:{identity}".encode()).hexdigest()
    signal = Signal(
        signal_id=identity,
        schema_version="signal-v1",
        strategy_id="manual-paper-preview",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        entity_id=command.instrument_id,
        decision_time=now,
        data_cutoff_time=now,
        direction=SignalDirection.LONG,
        score=Decimal(command.score),
        confidence=Decimal(command.confidence),
        horizon_sessions=5,
        rationale="人工假设的只读仓位试算，不是行情或模型预测",
        input_snapshot_id=identity,
        input_snapshot_version="1.0.0",
        evidence_ids=(evidence,),
    )
    quote = PaperMarketQuote(
        command.instrument_id,
        Decimal(command.price),
        now,
        now,
        command.lot_size,
        "manual-preview-price-v1",
        evidence,
    )
    result = allocate_preview_inputs(account, signal, quote, now)
    return AllocationContract.model_validate(result.payload()).model_dump(
        by_alias=True, mode="json"
    )


def allocate_preview_inputs(
    account: PaperAccountState, signal: Signal, quote: PaperMarketQuote, now: datetime
) -> PaperAllocationDecision:
    # Bounded decimal strings can exceed the ambient Decimal precision. This
    # local context keeps this read-only calculation deterministic and isolated.
    with localcontext() as context:
        context.prec = 128
        result = allocate_signals(
            (signal,),
            account=account,
            quotes=(quote,),
            decision_time=now,
            policy=PaperAllocationPolicy(
                "paper-preview-allocation",
                "1.0.0",
                Decimal("0.30"),
                Decimal("0.95"),
                Decimal("0.05"),
                Decimal("0.50"),
            ),
        )
    for target in result.targets:
        if max(target.current_quantity, target.target_quantity) > MAX_SAFE_QUANTITY:
            raise ValueError("试算数量超出支持范围，请调整参考价或资金假设")
    return result
