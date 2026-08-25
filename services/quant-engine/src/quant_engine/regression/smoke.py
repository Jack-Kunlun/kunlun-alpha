"""Deterministic public-API smoke chain for P5-N10 through P5-N12."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from ashare_contracts.backtest_regression_semantics import (
    ROOT_PYPROJECT_ENTRY,
    SERVICE_PYPROJECT_ENTRY,
    UV_LOCK_ENTRY,
    toolchain_evidence_sha256,
)
from backtest_core.engine import (
    BACKTEST_ENGINE_VERSION,
    EVENT_ORDERING_VERSION,
    MANIFEST_SCHEMA_VERSION,
    RNG_ALGORITHM,
    BacktestEngine,
    BacktestOrderIntent,
    BacktestRunManifest,
    IntentSide,
    ScheduledDecisionEvent,
    canonical_digest,
)
from backtest_core.execution import (
    EXECUTION_SCHEMA_VERSION,
    MATCHING_SCHEMA_VERSION,
    ExecutableLiquidityLevel,
    ExecutionProvenance,
    FeeComponent,
    FeeSchedule,
    FeeScope,
    InstrumentExecutionRules,
    InstrumentKind,
    LimitLockState,
    MarketExecutionSnapshot,
    OddLotSellPolicy,
    OrderType,
    PriceBand,
    PriceSource,
    SameDaySellPolicy,
    SellabilitySnapshot,
    SessionKind,
    SimulationOrder,
    SlippageModel,
    TradeStatus,
    match_orders,
)
from backtest_core.execution import (
    RoundingMode as ExecutionRoundingMode,
)
from backtest_core.portfolio import (
    PORTFOLIO_SCHEMA_VERSION,
    VALUATION_SCHEMA_VERSION,
    ZERO_DIGEST,
    BuyCashReservation,
    BuyCashReservationEvent,
    EventMetadata,
    EventPhase,
    ExecutionArtifactRef,
    ExecutionReplayBundle,
    ExecutionSettlementEvent,
    InitialCapitalEvent,
    LotCostAllocationPolicy,
    NextTradingDateResolution,
    PortfolioHistoryRef,
    PortfolioState,
    PortfolioValuation,
    ReservationPolicy,
    TrustedExecutionInputs,
    ValuationMark,
    ValuationMarkSource,
    apply_portfolio_event,
    export_sellability_snapshot,
    settle_execution_bundle,
    value_portfolio,
)
from backtest_core.portfolio.models import PortfolioEvent
from quant_core.metrics import (
    METRICS_ALGORITHM_VERSION,
    MetricsPolicy,
    NavObservation,
    RiskFreeObservation,
    calculate_performance_metrics,
)
from quant_core.strategy import (
    STRATEGY_SDK_VERSION,
    FeatureValue,
    ParameterType,
    Signal,
    SignalDirection,
    StrategyContext,
    StrategyDescriptor,
    StrategyParameters,
    StrategyParameterSpec,
    StrategyResult,
    StrategyRunner,
    StrategyState,
    UniverseSnapshot,
)

from .artifact import RegressionRunArtifact
from .canonical import canonical_sha256, timestamp_string

SUITE_ID = "p5-core-chain"
RUN_ID = "p5-core-chain-run"
FIXTURE_ID = "p5-core-chain-fixture-v1"
UTC_START = datetime(2026, 5, 29, 0, 30, tzinfo=UTC)
MATCH_TIME = datetime(2026, 5, 29, 1, 0, tzinfo=UTC)
NEXT_DAY_MATCH_TIME = datetime(2026, 6, 1, 1, 0, tzinfo=UTC)
INSTRUMENT = "600001.SH"
PRICE = Decimal("10.00")


def _context(at: datetime, snapshot_id: str) -> StrategyContext:
    cutoff = at - timedelta(minutes=5)
    return StrategyContext(
        decision_time=at,
        data_cutoff_time=cutoff,
        snapshot_id=snapshot_id,
        snapshot_version="1.0.0",
        universe=UniverseSnapshot(
            snapshot_id=f"universe:{snapshot_id}",
            snapshot_version="1.0.0",
            as_of_time=cutoff - timedelta(minutes=3),
            available_time=cutoff - timedelta(minutes=2),
            processing_time=cutoff - timedelta(minutes=1),
            entity_ids=(INSTRUMENT,),
        ),
        features=(
            FeatureValue(
                entity_id=INSTRUMENT,
                feature_name="fixture.value",
                feature_version="1.0.0",
                value=Decimal("0.8"),
                event_time=at - timedelta(days=1),
                available_time=cutoff - timedelta(minutes=2),
                processing_time=cutoff - timedelta(minutes=1),
                source_snapshot_id=f"features:{snapshot_id}",
                source_snapshot_version="1.0.0",
            ),
        ),
    )


def _descriptor() -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id="p5.core-chain.strategy",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Fixed self-contained regression strategy",
        required_features=("fixture.value",),
        parameter_specs=(
            StrategyParameterSpec(
                name="threshold",
                value_type=ParameterType.DECIMAL,
                required=True,
                description="Fixed fixture threshold",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
            ),
        ),
    )


DESCRIPTOR = _descriptor()
PARAMETERS = StrategyParameters(
    descriptor_version="1.0.0",
    values=(("threshold", Decimal("0.5")),),
)


def _signal(context: StrategyContext) -> Signal:
    return Signal(
        signal_id=f"signal:{context.snapshot_id}",
        schema_version="signal-v1",
        strategy_id=DESCRIPTOR.strategy_id,
        strategy_version=DESCRIPTOR.strategy_version,
        algorithm_version=DESCRIPTOR.algorithm_version,
        entity_id=INSTRUMENT,
        decision_time=context.decision_time,
        data_cutoff_time=context.data_cutoff_time,
        direction=SignalDirection.LONG,
        score=Decimal("0.8"),
        confidence=Decimal("0.9"),
        horizon_sessions=2,
        rationale="fixed regression signal",
        input_snapshot_id=context.snapshot_id,
        input_snapshot_version=context.snapshot_version,
        evidence_ids=(f"evidence:{context.snapshot_id}",),
    )


class _RegressionStrategy:
    descriptor = DESCRIPTOR

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState:
        return StrategyState(state_version="1.0.0", values=(("decisionCount", 0),))

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        del parameters
        return StrategyResult(
            signals=(_signal(context),),
            next_state=StrategyState(
                state_version="1.0.0",
                values=(("decisionCount", int(state.get("decisionCount") or 0) + 1),),
            ),
            diagnostics=("fixture",),
        )

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        del context, parameters
        return StrategyResult(signals=(), next_state=state, diagnostics=("finalize",))


class _RegressionPolicy:
    policy_id = "p5.core-chain.policy"
    policy_version = "1.0.0"
    implementation_fingerprint = "fixture:policy:v1"

    def to_intents(
        self,
        signals: tuple[Signal, ...],
        *,
        context: StrategyContext,
        event_id: str,
        random_source: object,
        manifest_digest: str,
        domain: str,
    ) -> tuple[BacktestOrderIntent, ...]:
        del context, random_source, domain
        return tuple(
            BacktestOrderIntent(
                intent_id=f"intent:{signal.signal_id}",
                source_signal_id=signal.signal_id,
                entity_id=signal.entity_id,
                logical_time=signal.decision_time,
                side=IntentSide.SELL if event_id == "decision-2" else IntentSide.BUY,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                policy_fingerprint=self.implementation_fingerprint,
                manifest_digest=manifest_digest,
            )
            for signal in signals
        )


class _RegressionProgram:
    strategy_implementation_fingerprint = "fixture:strategy:v1"
    policy_implementation_fingerprint = "fixture:policy:v1"

    def create_strategy_runner(self) -> StrategyRunner:
        return StrategyRunner(_RegressionStrategy(), PARAMETERS)

    def create_portfolio_intent_policy(self) -> _RegressionPolicy:
        return _RegressionPolicy()


def _manifest() -> BacktestRunManifest:
    events = tuple(
        ScheduledDecisionEvent(
            event_id=f"decision-{index}",
            source_id="fixture-market",
            source_sequence=index,
            logical_time=UTC_START + timedelta(minutes=15 * (index - 1)),
            available_time=UTC_START + timedelta(minutes=15 * (index - 1)) - timedelta(minutes=5),
            context=_context(
                UTC_START + timedelta(minutes=15 * (index - 1)),
                f"context-{index}",
            ),
        )
        for index in (1, 2)
    )
    return BacktestRunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        engine_version=BACKTEST_ENGINE_VERSION,
        strategy_descriptor=DESCRIPTOR,
        strategy_parameters=PARAMETERS,
        strategy_implementation_fingerprint=_RegressionProgram.strategy_implementation_fingerprint,
        policy_id=_RegressionPolicy.policy_id,
        policy_version=_RegressionPolicy.policy_version,
        policy_implementation_fingerprint=_RegressionProgram.policy_implementation_fingerprint,
        dataset_id="p5-core-chain-market-fixture",
        dataset_version="1.0.0",
        dataset_digest="fixture:p5-core-chain-market:v1",
        code_version="p5-n13-fixture-code-v1",
        config_version="p5-n13-fixture-config-v1",
        event_ordering_version=EVENT_ORDERING_VERSION,
        rng_algorithm=RNG_ALGORITHM,
        rng_seed="p5-core-chain-seed",
        start_time=UTC_START - timedelta(minutes=1),
        end_time=MATCH_TIME + timedelta(minutes=30),
        events=events,
    )


class _ExecutionSource:
    def __init__(self, *inputs: TrustedExecutionInputs) -> None:
        self.inputs = {item.artifact_id: item for item in inputs}

    def register(self, inputs: TrustedExecutionInputs) -> None:
        self.inputs[inputs.artifact_id] = inputs

    def resolve_execution_artifact(
        self, artifact_ref: ExecutionArtifactRef
    ) -> TrustedExecutionInputs:
        if artifact_ref.artifact_id not in self.inputs:
            raise RuntimeError("unknown execution artifact")
        return self.inputs[artifact_ref.artifact_id]


class _PortfolioSource:
    def __init__(self) -> None:
        self._tapes: dict[PortfolioHistoryRef, tuple[PortfolioEvent, ...]] = {}

    def resolve_portfolio_history(
        self, history_ref: PortfolioHistoryRef
    ) -> tuple[PortfolioEvent, ...]:
        return self._tapes.get(history_ref, ())

    def record(self, history_ref: PortfolioHistoryRef, events: tuple[PortfolioEvent, ...]) -> None:
        self._tapes[history_ref] = events

    def apply(
        self,
        state: PortfolioState,
        event: PortfolioEvent,
        execution_source: _ExecutionSource,
    ) -> PortfolioState:
        previous = self.resolve_portfolio_history(state.history_ref)
        result = apply_portfolio_event(
            state,
            event,
            source=self,
            execution_source=execution_source,
        )
        if result is not state:
            self.record(result.history_ref, previous + (event,))
        return result


def _source(
    record_id: str, digest: str, available_time: datetime = MATCH_TIME
) -> ExecutionProvenance:
    return ExecutionProvenance(
        source_id="p5-core-chain-fixture",
        source_version="1.0.0",
        record_id=record_id,
        digest=digest,
        available_time=available_time,
    )


@dataclass(frozen=True, slots=True)
class _ExecutionPlan:
    buy_inputs: TrustedExecutionInputs
    buy_bundle: ExecutionReplayBundle
    sell_order: SimulationOrder
    sell_snapshot_same_day: MarketExecutionSnapshot
    sell_snapshot_next_day: MarketExecutionSnapshot
    rules: InstrumentExecutionRules
    fee_schedule: FeeSchedule
    slippage_model: SlippageModel


@dataclass(frozen=True, slots=True)
class _TPlusOneEvidence:
    same_day_inputs: TrustedExecutionInputs
    next_day_inputs: TrustedExecutionInputs
    same_day_sellability: SellabilitySnapshot
    next_day_sellability: SellabilitySnapshot
    same_day_bundle: ExecutionReplayBundle
    next_day_bundle: ExecutionReplayBundle


def _execution_inputs(
    run_manifest: BacktestRunManifest, intents: tuple[BacktestOrderIntent, ...]
) -> _ExecutionPlan:
    buy_intent = next(intent for intent in intents if intent.side is IntentSide.BUY)
    sell_intent = next(intent for intent in intents if intent.side is IntentSide.SELL)
    buy_order = SimulationOrder(
        order_id="simulation-order-buy",
        source_intent=buy_intent,
        instrument_code=INSTRUMENT,
        side=IntentSide.BUY,
        manifest_digest=run_manifest.manifest_digest,
        submitted_at=buy_intent.logical_time,
        submission_sequence=1,
        quantity=100,
        order_type=OrderType.LIMIT_IOC,
        limit_price=PRICE,
        protection_price=None,
    )
    sell_order = SimulationOrder(
        order_id="simulation-order-sell",
        source_intent=sell_intent,
        instrument_code=INSTRUMENT,
        side=IntentSide.SELL,
        manifest_digest=run_manifest.manifest_digest,
        submitted_at=MATCH_TIME,
        submission_sequence=2,
        quantity=100,
        order_type=OrderType.LIMIT_IOC,
        limit_price=Decimal("10.20"),
        protection_price=None,
    )
    orders = (buy_order,)
    source_digest = "a" * 64
    snapshot = MarketExecutionSnapshot(
        schema_version=EXECUTION_SCHEMA_VERSION,
        snapshot_id="p5-core-chain-snapshot",
        instrument_code=INSTRUMENT,
        match_time=MATCH_TIME,
        observed_time=MATCH_TIME,
        available_time=MATCH_TIME - timedelta(minutes=1),
        processing_time=MATCH_TIME,
        trading_date="2026-05-29",
        is_trading_day=True,
        calendar_id="cn-a-share",
        calendar_version="1.0.0",
        calendar_digest="b" * 64,
        session=SessionKind.CONTINUOUS,
        trade_status=TradeStatus.OPEN,
        price_band=PriceBand(None, None, None, None),
        bid_levels=(),
        ask_levels=(
            ExecutableLiquidityLevel(
                level_id="ask-p5-core-chain",
                side=IntentSide.SELL,
                price=PRICE,
                quantity=200,
                available_time=MATCH_TIME - timedelta(minutes=1),
                price_source=PriceSource.EXECUTABLE_QUOTE,
                source=_source("ask-level", source_digest, MATCH_TIME - timedelta(minutes=1)),
            ),
        ),
        lock_state=LimitLockState.NONE,
        source=_source("execution-snapshot", source_digest, MATCH_TIME - timedelta(minutes=1)),
    )
    rules = InstrumentExecutionRules(
        rule_set_id="p5-core-chain-rules",
        rule_set_version="1.0.0",
        instrument_code=INSTRUMENT,
        instrument_kind=InstrumentKind.A_SHARE_STOCK,
        effective_from=MATCH_TIME - timedelta(hours=1),
        effective_to=None,
        available_time=MATCH_TIME - timedelta(minutes=1),
        lot_size=100,
        tick_size=Decimal("0.01"),
        buy_min_quantity=100,
        buy_increment=100,
        max_order_quantity=100000,
        odd_lot_sell_policy=OddLotSellPolicy.DISALLOW,
        same_day_sell_policy=SameDaySellPolicy.T_PLUS_1,
        supported_order_types=(OrderType.LIMIT_IOC,),
        source=_source("execution-rules", "c" * 64, MATCH_TIME - timedelta(minutes=1)),
    )
    fee = FeeComponent(
        code="commission",
        applies_sides=(IntentSide.BUY, IntentSide.SELL),
        instrument_kinds=(InstrumentKind.A_SHARE_STOCK,),
        rate=Decimal("0.001"),
        minimum=Decimal("0"),
        maximum=None,
        rounding_quantum=Decimal("0.01"),
        rounding_mode=ExecutionRoundingMode.HALF_UP,
        scope=FeeScope.PER_FILL,
        effective_from=MATCH_TIME - timedelta(hours=1),
        effective_to=None,
        available_time=MATCH_TIME - timedelta(minutes=1),
        source=_source("commission", "d" * 64, MATCH_TIME - timedelta(minutes=1)),
    )
    fee_schedule = FeeSchedule(
        schedule_id="p5-core-chain-fees",
        schedule_version="1.0.0",
        effective_from=MATCH_TIME - timedelta(hours=1),
        effective_to=None,
        available_time=MATCH_TIME - timedelta(minutes=1),
        components=(fee,),
        source=_source("fee-schedule", "e" * 64, MATCH_TIME - timedelta(minutes=1)),
    )
    slippage = SlippageModel(
        model_id="p5-core-chain-slippage",
        model_version="1.0.0",
        effective_from=MATCH_TIME - timedelta(hours=1),
        effective_to=None,
        available_time=MATCH_TIME - timedelta(minutes=1),
        max_level_participation=None,
        adverse_level_offset=0,
        skip_level_ids=(),
        source=_source("slippage", "f" * 64, MATCH_TIME - timedelta(minutes=1)),
    )
    candidate = match_orders(orders, snapshot, rules, None, fee_schedule, slippage)
    inputs = TrustedExecutionInputs(
        artifact_id="p5-core-chain-execution-buy-artifact",
        orders=orders,
        snapshot=snapshot,
        rules=rules,
        sellability=None,
        fee_schedule=fee_schedule,
        slippage_model=slippage,
        external_source_digest=snapshot.source.digest,
        external_config_digest=candidate.code_config_digest,
        next_trading_date_resolution=NextTradingDateResolution(
            calendar_id=snapshot.calendar_id,
            calendar_version=snapshot.calendar_version,
            calendar_digest=snapshot.calendar_digest,
            trading_date=snapshot.trading_date,
            next_trading_date="2026-06-01",
            available_time=MATCH_TIME,
            match_time=MATCH_TIME,
            provenance_available_time=MATCH_TIME,
        ),
    )
    same_day_level_source = _source(
        "same-day-sell-level", "1" * 64, MATCH_TIME - timedelta(minutes=1)
    )
    same_day_level = ExecutableLiquidityLevel(
        level_id="bid-p5-core-chain-same-day",
        side=IntentSide.BUY,
        price=Decimal("10.20"),
        quantity=100,
        available_time=MATCH_TIME - timedelta(minutes=1),
        price_source=PriceSource.EXECUTABLE_QUOTE,
        source=same_day_level_source,
    )
    same_day_snapshot = replace(
        snapshot,
        snapshot_id="p5-core-chain-same-day-sell-snapshot",
        bid_levels=(same_day_level,),
        ask_levels=(),
        source=_source("same-day-sell-snapshot", "2" * 64, MATCH_TIME - timedelta(minutes=1)),
    )
    next_day_level_source = _source(
        "next-day-sell-level", "3" * 64, NEXT_DAY_MATCH_TIME - timedelta(minutes=1)
    )
    next_day_level = replace(
        same_day_level,
        level_id="bid-p5-core-chain-next-day",
        available_time=NEXT_DAY_MATCH_TIME - timedelta(minutes=1),
        source=next_day_level_source,
    )
    next_day_snapshot = replace(
        same_day_snapshot,
        snapshot_id="p5-core-chain-next-day-sell-snapshot",
        match_time=NEXT_DAY_MATCH_TIME,
        observed_time=NEXT_DAY_MATCH_TIME,
        available_time=NEXT_DAY_MATCH_TIME - timedelta(minutes=1),
        processing_time=NEXT_DAY_MATCH_TIME,
        trading_date="2026-06-01",
        bid_levels=(next_day_level,),
        source=_source(
            "next-day-sell-snapshot", "4" * 64, NEXT_DAY_MATCH_TIME - timedelta(minutes=1)
        ),
    )
    return _ExecutionPlan(
        buy_inputs=inputs,
        buy_bundle=ExecutionReplayBundle(
        artifact_ref=ExecutionArtifactRef(inputs.artifact_id, inputs.input_digest),
        candidate=candidate,
        ),
        sell_order=sell_order,
        sell_snapshot_same_day=same_day_snapshot,
        sell_snapshot_next_day=next_day_snapshot,
        rules=rules,
        fee_schedule=fee_schedule,
        slippage_model=slippage,
    )


def _portfolio_and_valuations(
    plan: _ExecutionPlan,
) -> tuple[
    PortfolioState,
    tuple[tuple[PortfolioValuation, ValuationMark], ...],
    tuple[NavObservation, ...],
    tuple[RiskFreeObservation, ...],
    _TPlusOneEvidence,
]:
    bundle = plan.buy_bundle
    inputs = plan.buy_inputs
    execution_source = _ExecutionSource(inputs)
    portfolio_source = _PortfolioSource()
    state = PortfolioState.empty("p5-core-chain-history")
    opening_time = MATCH_TIME - timedelta(minutes=30)
    opening_metadata = EventMetadata.for_event(
        event_id="p5-core-chain-opening",
        logical_time=opening_time,
        event_phase=EventPhase.OPENING,
        source_id="p5-core-chain-opening",
        source_version="1.0.0",
        source_sequence=0,
        expected_previous_state_digest=state.state_digest,
        previous_event_digest=ZERO_DIGEST,
        provenance_digest=ZERO_DIGEST,
        config_digest=ZERO_DIGEST,
        available_time=opening_time,
    )
    state = portfolio_source.apply(
        state,
        InitialCapitalEvent(metadata=opening_metadata, amount=Decimal("100000")),
        execution_source,
    )
    reservation_policy = ReservationPolicy(
        policy_id="p5-core-chain-reservation",
        policy_version="1.0.0",
        policy_digest=canonical_digest(
            {"policy_id": "p5-core-chain-reservation", "policy_version": "1.0.0"}
        ),
    )
    result_by_order = {result.order_id: result for result in bundle.candidate.results}
    for sequence, order in enumerate(inputs.orders, start=1):
        result = result_by_order[order.order_id]
        if not result.fills:
            raise RuntimeError("fixture order did not fill")
        maximum_debit = sum(
            (fill.gross_notional + fill.total_fee for fill in result.fills), Decimal("0")
        )
        reservation = BuyCashReservation(
            order_id=order.order_id,
            order_digest=order.order_digest,
            fee_schedule_digest=inputs.fee_schedule.fee_schedule_digest,
            artifact_id=inputs.artifact_id,
            execution_input_digest=inputs.input_digest,
            policy_id=reservation_policy.policy_id,
            policy_version=reservation_policy.policy_version,
            policy_digest=reservation_policy.policy_digest,
            reservation_logical_time=MATCH_TIME,
            maximum_debit=maximum_debit,
        )
        metadata = EventMetadata.for_event(
            event_id=f"p5-core-chain-reservation-{sequence}",
            logical_time=MATCH_TIME,
            event_phase=EventPhase.RESERVATION,
            source_id="p5-core-chain-reservation",
            source_version="1.0.0",
            source_sequence=sequence,
            expected_previous_state_digest=state.state_digest,
            previous_event_digest=state.last_event_digest,
            provenance_digest=inputs.external_source_digest,
            config_digest=inputs.external_config_digest,
            payload={"event_type": "BUY_CASH_RESERVATION", "reservation": reservation},
        )
        state = portfolio_source.apply(
            state,
            BuyCashReservationEvent(metadata=metadata, reservation=reservation),
            execution_source,
        )
    settlement_metadata = EventMetadata.for_event(
        event_id="p5-core-chain-settlement",
        logical_time=MATCH_TIME,
        event_phase=EventPhase.EXECUTION,
        source_id="p5-core-chain-settlement",
        source_version="1.0.0",
        source_sequence=1,
        expected_previous_state_digest=state.state_digest,
        previous_event_digest=state.last_event_digest,
        provenance_digest=inputs.external_source_digest,
        config_digest=inputs.external_config_digest,
        payload={
            "event_type": "EXECUTION_SETTLEMENT",
            "bundle": bundle,
            "lot_cost_policy": LotCostAllocationPolicy(),
        },
    )
    previous = portfolio_source.resolve_portfolio_history(state.history_ref)
    settlement_event = ExecutionSettlementEvent(
        metadata=settlement_metadata,
        bundle=bundle,
        lot_cost_policy=LotCostAllocationPolicy(),
    )
    state = settle_execution_bundle(
        state,
        bundle,
        source=portfolio_source,
        execution_source=execution_source,
        metadata=settlement_metadata,
    )
    portfolio_source.record(state.history_ref, previous + (settlement_event,))
    pre_sell_state = state

    same_day_sellability = export_sellability_snapshot(
        state,
        INSTRUMENT,
        MATCH_TIME,
        source=portfolio_source,
        execution_source=execution_source,
    )
    next_day_sellability = export_sellability_snapshot(
        state,
        INSTRUMENT,
        NEXT_DAY_MATCH_TIME,
        source=portfolio_source,
        execution_source=execution_source,
    )

    def sell_inputs(
        artifact_id: str,
        snapshot: MarketExecutionSnapshot,
        sellability: SellabilitySnapshot,
        next_trading_date: str,
    ) -> TrustedExecutionInputs:
        candidate = match_orders(
            (plan.sell_order,),
            snapshot,
            plan.rules,
            sellability,
            plan.fee_schedule,
            plan.slippage_model,
        )
        return TrustedExecutionInputs(
            artifact_id=artifact_id,
            orders=(plan.sell_order,),
            snapshot=snapshot,
            rules=plan.rules,
            sellability=sellability,
            fee_schedule=plan.fee_schedule,
            slippage_model=plan.slippage_model,
            external_source_digest=snapshot.source.digest,
            external_config_digest=candidate.code_config_digest,
            next_trading_date_resolution=NextTradingDateResolution(
                calendar_id=snapshot.calendar_id,
                calendar_version=snapshot.calendar_version,
                calendar_digest=snapshot.calendar_digest,
                trading_date=snapshot.trading_date,
                next_trading_date=next_trading_date,
                available_time=snapshot.available_time,
                match_time=snapshot.match_time,
                provenance_available_time=snapshot.source.available_time,
            ),
        )

    same_day_inputs = sell_inputs(
        "p5-core-chain-execution-sell-same-day-artifact",
        plan.sell_snapshot_same_day,
        same_day_sellability,
        "2026-06-01",
    )
    next_day_inputs = sell_inputs(
        "p5-core-chain-execution-sell-next-day-artifact",
        plan.sell_snapshot_next_day,
        next_day_sellability,
        "2026-06-02",
    )
    execution_source.register(same_day_inputs)
    execution_source.register(next_day_inputs)
    same_day_batch = match_orders(
        same_day_inputs.orders,
        same_day_inputs.snapshot,
        same_day_inputs.rules,
        same_day_inputs.sellability,
        same_day_inputs.fee_schedule,
        same_day_inputs.slippage_model,
    )
    next_day_batch = match_orders(
        next_day_inputs.orders,
        next_day_inputs.snapshot,
        next_day_inputs.rules,
        next_day_inputs.sellability,
        next_day_inputs.fee_schedule,
        next_day_inputs.slippage_model,
    )
    if not next_day_batch.results or not next_day_batch.results[0].fills:
        raise RuntimeError("next-day sell did not fill")
    if (
        not same_day_batch.results
        or same_day_batch.results[0].reject_reason is None
        or same_day_batch.results[0].reject_reason.value != "T_PLUS_ONE_NOT_SELLABLE"
    ):
        raise RuntimeError("same-day sell did not fail with T_PLUS_ONE_NOT_SELLABLE")
    sell_bundle = ExecutionReplayBundle(
        artifact_ref=ExecutionArtifactRef(
            next_day_inputs.artifact_id,
            next_day_inputs.input_digest,
        ),
        candidate=next_day_batch,
    )
    sell_settlement_metadata = EventMetadata.for_event(
        event_id="p5-core-chain-next-day-sell-settlement",
        logical_time=NEXT_DAY_MATCH_TIME,
        event_phase=EventPhase.EXECUTION,
        source_id="p5-core-chain-next-day-sell-settlement",
        source_version="1.0.0",
        source_sequence=2,
        expected_previous_state_digest=state.state_digest,
        previous_event_digest=state.last_event_digest,
        provenance_digest=next_day_inputs.external_source_digest,
        config_digest=next_day_inputs.external_config_digest,
        payload={
            "event_type": "EXECUTION_SETTLEMENT",
            "bundle": sell_bundle,
            "lot_cost_policy": LotCostAllocationPolicy(),
        },
    )
    previous = portfolio_source.resolve_portfolio_history(state.history_ref)
    sell_settlement_event = ExecutionSettlementEvent(
        metadata=sell_settlement_metadata,
        bundle=sell_bundle,
        lot_cost_policy=LotCostAllocationPolicy(),
    )
    state = settle_execution_bundle(
        state,
        sell_bundle,
        source=portfolio_source,
        execution_source=execution_source,
        metadata=sell_settlement_metadata,
    )
    portfolio_source.record(state.history_ref, previous + (sell_settlement_event,))
    post_sell_state = state

    prices = (Decimal("10.00"), Decimal("10.20"), Decimal("10.10"), Decimal("10.30"))
    cutoff_times = tuple(MATCH_TIME + timedelta(days=index) for index in range(4))
    valuations: list[tuple[PortfolioValuation, ValuationMark]] = []
    nav: list[NavObservation] = []
    risk_free: list[RiskFreeObservation] = []
    for index, (cutoff, price) in enumerate(zip(cutoff_times, prices, strict=True)):
        mark = ValuationMark(
            instrument_code=INSTRUMENT,
            mark_time=cutoff,
            available_time=cutoff,
            price=price,
            source=ValuationMarkSource.RAW_MARKET_CLOSE,
            source_id="p5-core-chain-close",
            source_version="1.0.0",
            provenance_digest=canonical_digest(("close", index, price)),
            provenance_available_time=cutoff,
        )
        valuation_state = pre_sell_state if cutoff < NEXT_DAY_MATCH_TIME else post_sell_state
        valuation = value_portfolio(
            valuation_state,
            cutoff,
            (mark,) if valuation_state.open_lots else (),
            source=portfolio_source,
            execution_source=execution_source,
        )
        valuations.append((valuation, mark))
        nav.append(
            NavObservation(
                observation_time=cutoff,
                available_time=cutoff,
                nav=valuation.nav,
                source_id="p5-core-chain-nav",
                source_version="1.0.0",
                provenance_digest=mark.provenance_digest,
            )
        )
        risk_free.append(
            RiskFreeObservation(
                observation_time=cutoff,
                available_time=cutoff,
                rate=Decimal("0"),
                source_id="p5-core-chain-rf",
                source_version="1.0.0",
                provenance_digest=canonical_digest(("rf", index)),
            )
        )
    return (
        state,
        tuple(valuations),
        tuple(nav),
        tuple(risk_free),
        _TPlusOneEvidence(
            same_day_inputs=same_day_inputs,
            next_day_inputs=next_day_inputs,
            same_day_sellability=same_day_sellability,
            next_day_sellability=next_day_sellability,
            same_day_bundle=ExecutionReplayBundle(
                artifact_ref=ExecutionArtifactRef(
                    same_day_inputs.artifact_id,
                    same_day_inputs.input_digest,
                ),
                candidate=same_day_batch,
            ),
            next_day_bundle=sell_bundle,
        ),
    )


def _repo_root(repo_root: Path | None) -> Path:
    candidate = repo_root or (
        Path(os.environ["KUNLUN_REPO_ROOT"])
        if os.environ.get("KUNLUN_REPO_ROOT")
        else Path(__file__).resolve().parents[5]
    )
    root = candidate.absolute()
    if (
        not root.is_dir()
        or not (root / "pyproject.toml").is_file()
        or not (root / "uv.lock").is_file()
    ):
        raise RuntimeError("repo root must contain pyproject.toml and uv.lock")
    return root


_SOURCE_ROOTS = (
    "services/quant-engine/src/quant_engine/regression",
    "python/packages/backtest-core/src/backtest_core",
    "python/packages/quant-core/src/quant_core",
    "python/packages/ashare-contracts/src/ashare_contracts",
)


def _source_files(repo_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative_root in _SOURCE_ROOTS:
        source_root = repo_root / relative_root
        if not source_root.is_dir() or source_root.is_symlink():
            raise RuntimeError(f"source closure root is unavailable or symlinked: {relative_root}")
        for path in source_root.rglob("*.py"):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"source closure contains a non-regular file: {path}")
            relative = path.relative_to(repo_root).as_posix()
            if any(part in ("", ".", "..", "__pycache__") for part in relative.split("/")):
                raise RuntimeError(f"source closure path is not canonical: {relative}")
            files.append(path)
    return tuple(sorted(set(files), key=lambda path: path.relative_to(repo_root).as_posix()))


def _source_allowlist(repo_root: Path) -> tuple[dict[str, str], ...]:
    values = tuple(
        (
            path.relative_to(repo_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _source_files(repo_root)
    )
    return tuple({"path": path, "sha256": digest} for path, digest in values)


def _source_aggregate(repo_root: Path, relative_root: str) -> str:
    values = tuple(
        (
            path.relative_to(repo_root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in _source_files(repo_root)
        if path.is_relative_to(repo_root / relative_root)
    )
    if not values:
        raise RuntimeError(f"source package has no Python source: {relative_root}")
    return canonical_sha256(values)


def _pinned_toolchain(repo_root: Path) -> dict[str, str]:
    root_pyproject = repo_root / "pyproject.toml"
    service_pyproject = repo_root / "services/quant-engine/pyproject.toml"
    uv_lock = repo_root / "uv.lock"
    root_project = tomllib.loads(root_pyproject.read_text(encoding="utf-8"))
    service_project = tomllib.loads(service_pyproject.read_text(encoding="utf-8"))
    python_pin = (repo_root / ".python-version").read_text(encoding="utf-8").strip()
    requires_python = root_project.get("project", {}).get("requires-python")
    uv_pin = root_project.get("tool", {}).get("uv", {}).get("required-version")
    build_requires = service_project.get("build-system", {}).get("requires", [])
    hatchling_pins = [
        value.removeprefix("hatchling==")
        for value in build_requires
        if isinstance(value, str) and value.startswith("hatchling==")
    ]
    if len(hatchling_pins) != 1:
        raise RuntimeError("quant-engine Hatchling pin is not uniquely declared")
    lock = tomllib.loads(uv_lock.read_text(encoding="utf-8"))
    lock_python = lock.get("requires-python")
    if python_pin != "3.12.13" or requires_python != "==3.12.13" or lock_python != "==3.12.13":
        raise RuntimeError("repository Python pin is not exactly 3.12.13")
    if uv_pin != "==0.12.3":
        raise RuntimeError("repository uv pin is not exactly 0.12.3")
    runtime_python = ".".join(str(part) for part in sys.version_info[:3])
    if runtime_python != python_pin:
        raise RuntimeError("runtime Python does not match repository pin")
    uv_result = subprocess.run(
        ["uv", "--version"], capture_output=True, text=True, check=False
    )
    if uv_result.returncode != 0:
        raise RuntimeError("uv version could not be verified")
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", uv_result.stdout)
    if match is None or match.group(1) != uv_pin.removeprefix("=="):
        raise RuntimeError("runtime uv does not match repository pin")
    return {
        "python": python_pin,
        "uv": uv_pin.removeprefix("=="),
        "hatchling": hatchling_pins[0],
        "rootPyprojectSha256": hashlib.sha256(root_pyproject.read_bytes()).hexdigest(),
        "servicePyprojectSha256": hashlib.sha256(
            service_pyproject.read_bytes()
        ).hexdigest(),
        "uvLockSha256": hashlib.sha256(uv_lock.read_bytes()).hexdigest(),
    }


def _dependency_entries(repo_root: Path) -> tuple[dict[str, str], ...]:
    packages = {
        "ashare-contracts": "python/packages/ashare-contracts",
        "backtest-core": "python/packages/backtest-core",
        "quant-core": "python/packages/quant-core",
    }
    entries: list[dict[str, str]] = []
    for name, relative_root in packages.items():
        project = tomllib.loads(
            (repo_root / relative_root / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = project.get("project", {}).get("version")
        build_requires = project.get("build-system", {}).get("requires", [])
        if not isinstance(version, str) or "hatchling==1.27.0" not in build_requires:
            raise RuntimeError(f"{name} package metadata is not pinned")
        entries.append(
            {
                "name": name,
                "version": version,
                "sha256": _source_aggregate(repo_root, f"{relative_root}/src"),
            }
        )
    lock_digest = hashlib.sha256((repo_root / "uv.lock").read_bytes()).hexdigest()
    entries.append({"name": UV_LOCK_ENTRY, "version": "repo-root", "sha256": lock_digest})
    return tuple(sorted(entries, key=lambda item: item["name"]))


def run_smoke_chain(repo_root: Path | None = None) -> RegressionRunArtifact:
    resolved_root = _repo_root(repo_root)
    manifest = _manifest()
    run = BacktestEngine().run(manifest, _RegressionProgram())
    intents = tuple(intent for trace in run.trace for intent in trace.intents)
    plan = _execution_inputs(manifest, intents)
    state, valuations, nav, risk_free, t_plus_one = _portfolio_and_valuations(plan)
    inputs = plan.buy_inputs
    bundle = plan.buy_bundle
    metrics_policy = MetricsPolicy(
        policy_id="p5-core-chain-metrics",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    metrics = calculate_performance_metrics(nav, risk_free, metrics_policy)
    metric_names = (
        "cumulative_chained_return",
        "annualized_return",
        "annualized_volatility",
        "maximum_drawdown",
        "sharpe",
        "sortino",
        "calmar",
    )
    metric_payload: dict[str, object] = {}
    for name in metric_names:
        value = metrics.metric(name)
        metric_payload[
            {
                "cumulative_chained_return": "cumulativeChainedReturn",
                "annualized_return": "annualizedReturn",
                "annualized_volatility": "annualizedVolatility",
                "maximum_drawdown": "maximumDrawdown",
                "sharpe": "sharpe",
                "sortino": "sortino",
                "calmar": "calmar",
            }[name]
        ] = {
            "status": value.status.value,
            "value": value.value,
        }
    final_valuation, _final_mark = valuations[-1]
    final_nav = final_valuation.nav
    final_total_pnl = final_valuation.total_pnl
    results = bundle.candidate.results
    same_day_result = t_plus_one.same_day_bundle.candidate.results[0]
    next_day_result = t_plus_one.next_day_bundle.candidate.results[0]
    fill_count = sum(len(result.fills) for result in results) + len(next_day_result.fills)
    observations = tuple(
        {
            "observationTime": timestamp_string(item.observation_time),
            "nav": item.nav,
            "provenanceDigest": item.provenance_digest,
        }
        for item in nav
    )
    risk_free_observations = tuple(
        {
            "observationTime": timestamp_string(item.observation_time),
            "rate": item.rate,
            "provenanceDigest": item.provenance_digest,
        }
        for item in risk_free
    )
    valuation_lineage: tuple[dict[str, object], ...] = tuple(
        {
            "observationTime": timestamp_string(valuation.cutoff_time),
            "inputDigest": valuation.input_digest,
            "markDigest": mark.digest,
            "stateDigest": valuation.state_digest,
            "nav": valuation.nav,
        }
        for valuation, mark in valuations
    )
    calendar = inputs.next_trading_date_resolution
    if (
        calendar is None
        or calendar.match_time is None
        or calendar.provenance_available_time is None
    ):
        raise RuntimeError("fixture calendar resolution is incomplete")
    fixture_input = {
        "manifest": manifest.to_canonical_json(),
        "orders": tuple((order.order_id, order.order_digest) for order in inputs.orders),
        "sellOrder": (plan.sell_order.order_id, plan.sell_order.order_digest),
        "calendar": {
            "calendarId": calendar.calendar_id,
            "calendarVersion": calendar.calendar_version,
            "calendarDigest": calendar.calendar_digest,
            "tradingDate": calendar.trading_date,
            "nextTradingDate": calendar.next_trading_date,
            "availableTime": timestamp_string(calendar.available_time),
            "matchTime": timestamp_string(calendar.match_time),
            "provenanceAvailableTime": timestamp_string(calendar.provenance_available_time),
        },
        "nav": tuple(item.nav for item in nav),
        "riskFree": tuple(item.rate for item in risk_free),
        "tPlusOne": {
            "sameDaySellabilityDigest": t_plus_one.same_day_sellability.sellability_digest,
            "nextDaySellabilityDigest": t_plus_one.next_day_sellability.sellability_digest,
            "sameDayBatchDigest": t_plus_one.same_day_bundle.candidate.batch_digest,
            "nextDayBatchDigest": t_plus_one.next_day_bundle.candidate.batch_digest,
        },
    }
    allowlist = _source_allowlist(resolved_root)
    code_tree_digest = canonical_sha256(tuple((item["path"], item["sha256"]) for item in allowlist))
    toolchain = _pinned_toolchain(resolved_root)
    service_project = tomllib.loads(
        (resolved_root / "services/quant-engine/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    service_version = cast(str, service_project["project"]["version"])
    config_entries = tuple(
        sorted(
            (
                {
                    "name": FIXTURE_ID,
                    "version": FIXTURE_ID,
                    "sha256": canonical_sha256(fixture_input),
                },
                {
                    "name": ROOT_PYPROJECT_ENTRY,
                    "version": "repo-root",
                    "sha256": toolchain["rootPyprojectSha256"],
                },
                {
                    "name": SERVICE_PYPROJECT_ENTRY,
                    "version": service_version,
                    "sha256": toolchain["servicePyprojectSha256"],
                },
            ),
            key=lambda item: item["name"],
        )
    )
    dependency_entries = _dependency_entries(resolved_root)
    toolchain_evidence = toolchain_evidence_sha256(toolchain)
    manifest_json = cast(dict[str, object], json.loads(manifest.to_canonical_json()))
    payload: dict[str, object] = {
        "schemaVersion": "backtest-regression-run-v1",
        "canonicalizationVersion": "backtest-regression-c14n-v1",
        "suiteId": SUITE_ID,
        "runId": RUN_ID,
        "fixtureId": FIXTURE_ID,
        "trust": {
            "mode": "FIXTURE_SELF_CONTAINED",
            "evidenceIntegrityConfidence": "HIGH",
            "evidenceRefs": (
                {
                    "kind": "OPAQUE_EXTERNAL",
                    "namespace": "fixture-review",
                    "value": "p5-core-chain",
                },
            ),
        },
        "manifest": {"json": manifest_json, "sha256": canonical_sha256(manifest_json)},
        "inputs": {
            "fixtureSha256": canonical_sha256(fixture_input),
            "executionInputDigests": tuple(
                sorted(
                    (
                        inputs.input_digest,
                        t_plus_one.same_day_inputs.input_digest,
                        t_plus_one.next_day_inputs.input_digest,
                    )
                )
            ),
            "portfolioHistoryRef": {
                "tapeId": state.history_ref.tape_id,
                "eventTapeDigest": state.history_ref.event_tape_digest,
                "eventCount": state.history_ref.event_count,
            },
            "valuationLineage": {
                "valuationPolicyId": "raw-accounting-mark",
                "valuationPolicyVersion": "1.0.0",
                "valuationPolicyDigest": final_valuation.valuation_policy_digest,
                "valuations": valuation_lineage,
            },
            "navObservations": observations,
            "riskFreeObservations": risk_free_observations,
            "tPlusOne": {
                "buyOrderId": inputs.orders[0].order_id,
                "sellOrderId": plan.sell_order.order_id,
                "buyExecutionInputDigest": inputs.input_digest,
                "sameDaySellExecutionInputDigest": t_plus_one.same_day_inputs.input_digest,
                "nextDaySellExecutionInputDigest": t_plus_one.next_day_inputs.input_digest,
                "sameDaySellabilityDigest": t_plus_one.same_day_sellability.sellability_digest,
                "nextDaySellabilityDigest": t_plus_one.next_day_sellability.sellability_digest,
                "sameDayBatchDigest": t_plus_one.same_day_bundle.candidate.batch_digest,
                "nextDayBatchDigest": t_plus_one.next_day_bundle.candidate.batch_digest,
            },
        },
        "provenance": {
            "code": {"allowlist": allowlist, "treeSha256": code_tree_digest},
            "config": config_entries,
            "dependencies": dependency_entries,
            "toolchain": {
                **toolchain,
                "evidenceSha256": toolchain_evidence,
            },
        },
        "versions": {
            "engine": BACKTEST_ENGINE_VERSION,
            "manifest": MANIFEST_SCHEMA_VERSION,
            "eventOrder": EVENT_ORDERING_VERSION,
            "execution": EXECUTION_SCHEMA_VERSION,
            "matching": MATCHING_SCHEMA_VERSION,
            "portfolio": PORTFOLIO_SCHEMA_VERSION,
            "valuation": VALUATION_SCHEMA_VERSION,
            "metrics": METRICS_ALGORITHM_VERSION,
            "strategy": DESCRIPTOR.algorithm_version,
            "policy": _RegressionPolicy.policy_version,
            "fixture": FIXTURE_ID,
        },
        "results": {
            "counts": {
                "events": len(run.trace),
                "intents": len(intents),
                "orders": len(inputs.orders) + 1,
                "fills": fill_count,
                "navObservations": len(nav),
                "tPlusOneRejected": int(same_day_result.status.value == "REJECTED"),
                "nextDaySellFills": len(next_day_result.fills),
            },
            "pnl": {
                "realized": final_valuation.realized_price_pnl,
                "unrealized": final_valuation.unrealized_price_pnl,
                "total": final_total_pnl,
                "fees": final_valuation.fee_pnl,
            },
            "finalNav": final_nav,
            "finalValuation": {
                "cutoffTime": timestamp_string(final_valuation.cutoff_time),
                "nav": final_nav,
                "totalPnl": final_total_pnl,
                "stateDigest": final_valuation.state_digest,
                "inputDigest": final_valuation.input_digest,
                "sampleCount": final_valuation.sample_count,
            },
            "metrics": metric_payload,
            "observations": observations,
            "tPlusOne": {
                "sameDay": {
                    "orderId": same_day_result.order_id,
                    "status": same_day_result.status.value,
                    "rejectReason": (
                        same_day_result.reject_reason.value
                        if same_day_result.reject_reason is not None
                        else None
                    ),
                    "fillCount": len(same_day_result.fills),
                    "batchDigest": t_plus_one.same_day_bundle.candidate.batch_digest,
                    "resultDigest": same_day_result.result_digest,
                    "tradingDate": t_plus_one.same_day_inputs.snapshot.trading_date,
                    "sellabilityDigest": t_plus_one.same_day_sellability.sellability_digest,
                },
                "nextDay": {
                    "orderId": next_day_result.order_id,
                    "status": next_day_result.status.value,
                    "rejectReason": (
                        next_day_result.reject_reason.value
                        if next_day_result.reject_reason is not None
                        else None
                    ),
                    "fillCount": len(next_day_result.fills),
                    "batchDigest": t_plus_one.next_day_bundle.candidate.batch_digest,
                    "resultDigest": next_day_result.result_digest,
                    "tradingDate": t_plus_one.next_day_inputs.snapshot.trading_date,
                    "sellabilityDigest": t_plus_one.next_day_sellability.sellability_digest,
                },
            },
        },
    }
    return RegressionRunArtifact.build(payload)


__all__ = ["run_smoke_chain"]
