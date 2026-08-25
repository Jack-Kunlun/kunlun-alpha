from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from quant_core.strategy import (
    STRATEGY_SDK_VERSION,
    FeatureValue,
    ParameterType,
    Signal,
    SignalDirection,
    Strategy,
    StrategyContext,
    StrategyDescriptor,
    StrategyFutureDataError,
    StrategyInputError,
    StrategyParameters,
    StrategyParameterSpec,
    StrategyResult,
    StrategyRunner,
    StrategyState,
    UniverseSnapshot,
    validate_parameters,
    validate_strategy_result,
)

DECISION_TIME = datetime(2026, 6, 1, 7, tzinfo=UTC)
CUTOFF = DECISION_TIME - timedelta(minutes=1)


def _feature(
    *,
    entity_id: str = "600001.SH",
    name: str = "momentum.window_20d",
    value: Decimal = Decimal("0.25"),
) -> FeatureValue:
    return FeatureValue(
        entity_id=entity_id,
        feature_name=name,
        feature_version="1.0.0",
        value=value,
        event_time=CUTOFF - timedelta(days=1),
        available_time=CUTOFF - timedelta(seconds=2),
        processing_time=CUTOFF - timedelta(seconds=1),
        source_snapshot_id="features:2026-06-01",
        source_snapshot_version="1.0.0",
    )


def _universe() -> UniverseSnapshot:
    return UniverseSnapshot(
        snapshot_id="universe:2026-06-01",
        snapshot_version="1.0.0",
        as_of_time=CUTOFF - timedelta(minutes=1),
        available_time=CUTOFF - timedelta(seconds=2),
        processing_time=CUTOFF - timedelta(seconds=1),
        entity_ids=("600001.SH", "600002.SH"),
    )


def _context(*features: FeatureValue) -> StrategyContext:
    return StrategyContext(
        decision_time=DECISION_TIME,
        data_cutoff_time=CUTOFF,
        snapshot_id="strategy-context:2026-06-01",
        snapshot_version="1.0.0",
        universe=_universe(),
        features=features or (_feature(),),
    )


def _descriptor() -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id="momentum.research",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Point-in-time momentum research strategy",
        required_features=("momentum.window_20d",),
        parameter_specs=(
            StrategyParameterSpec(
                name="lookback",
                value_type=ParameterType.INTEGER,
                required=True,
                description="Research lookback sessions",
                minimum=1,
                maximum=250,
            ),
            StrategyParameterSpec(
                name="threshold",
                value_type=ParameterType.DECIMAL,
                required=False,
                description="Minimum research score",
                default_value=Decimal("0.2"),
                minimum=Decimal(0),
                maximum=Decimal(1),
            ),
        ),
    )


def _signal(context: StrategyContext) -> Signal:
    return Signal(
        signal_id="signal:momentum:600001.SH:20260601",
        schema_version="signal-v1",
        strategy_id="momentum.research",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        entity_id="600001.SH",
        decision_time=context.decision_time,
        data_cutoff_time=context.data_cutoff_time,
        direction=SignalDirection.LONG,
        score=Decimal("0.7"),
        confidence=Decimal("0.8"),
        horizon_sessions=20,
        rationale="Momentum score exceeded the configured research threshold.",
        input_snapshot_id=context.snapshot_id,
        input_snapshot_version=context.snapshot_version,
        evidence_ids=("feature:momentum.window_20d:600001.SH",),
    )


def test_context_rejects_future_features_and_survivorship_universe() -> None:
    feature = _feature()
    with pytest.raises(StrategyFutureDataError, match="feature exceeds data cutoff"):
        _context(
            replace(
                feature,
                available_time=CUTOFF + timedelta(seconds=1),
                processing_time=CUTOFF + timedelta(seconds=1),
            )
        )
    with pytest.raises(StrategyFutureDataError, match="universe exceeds data cutoff"):
        replace(
            _context(),
            universe=replace(
                _universe(),
                available_time=CUTOFF + timedelta(seconds=1),
                processing_time=CUTOFF + timedelta(seconds=1),
            ),
        )
    with pytest.raises(StrategyInputError, match="outside historical universe"):
        _context(_feature(entity_id="600003.SH"))


def test_context_is_immutable_pit_data_without_provider_or_clock_access() -> None:
    context = _context()

    assert context.get_feature("600001.SH", "momentum.window_20d") == _feature()
    assert context.get_feature("600001.SH", "missing.feature") is None
    assert context.entity_ids == ("600001.SH", "600002.SH")
    assert {
        "broker",
        "execution",
        "order",
        "provider",
        "network",
        "clock",
        "now",
    }.isdisjoint(StrategyContext.__dataclass_fields__)


def test_parameters_are_typed_bounded_complete_and_deterministically_ordered() -> None:
    descriptor = _descriptor()
    parameters = validate_parameters(descriptor, {"lookback": 20})

    assert parameters == StrategyParameters(
        descriptor_version="1.0.0",
        values=(("lookback", 20), ("threshold", Decimal("0.2"))),
    )
    with pytest.raises(StrategyInputError, match="unknown parameter"):
        validate_parameters(descriptor, {"lookback": 20, "quantity": 100})
    with pytest.raises(StrategyInputError, match="lookback.*minimum"):
        validate_parameters(descriptor, {"lookback": 0})
    with pytest.raises(StrategyInputError, match="lookback.*INTEGER"):
        validate_parameters(descriptor, {"lookback": Decimal(20)})
    with pytest.raises(StrategyInputError, match="lookback.*INTEGER bounds"):
        replace(
            descriptor.parameter_specs[0],
            minimum=Decimal(1),
            maximum=Decimal(250),
        )
    with pytest.raises(StrategyInputError, match="required_features must not be empty"):
        replace(descriptor, required_features=())
    with pytest.raises(StrategyInputError, match="parameter_specs must not be empty"):
        replace(descriptor, parameter_specs=())


def test_signal_is_research_only_decimal_typed_and_non_executable() -> None:
    signal = _signal(_context())

    assert signal.is_executable is False
    assert signal.execution_capability == "NONE"
    assert _descriptor().schema_version == "strategy-descriptor-v1"
    assert _descriptor().lifecycle_hooks == ("initialize", "onDecision", "finalize")
    assert _descriptor().signal_schema_version == "signal-v1"
    assert _descriptor().execution_capability == "NONE"
    assert {
        "account_id",
        "broker",
        "client_order_id",
        "limit_price",
        "order_id",
        "quantity",
    }.isdisjoint(Signal.__dataclass_fields__)
    with pytest.raises(ValueError, match="init=False"):
        replace(signal, is_executable=True)
    with pytest.raises(StrategyInputError, match="score.*Decimal"):
        replace(signal, score=cast(Decimal, 0.7))
    with pytest.raises(StrategyInputError, match="horizon_sessions"):
        replace(signal, horizon_sessions=10001)
    with pytest.raises(StrategyInputError, match="evidence_ids must be a tuple"):
        replace(signal, evidence_ids=cast(tuple[str, ...], ["mutable:evidence"]))
    with pytest.raises(StrategyInputError, match="signals must be a tuple"):
        StrategyResult(
            signals=cast(tuple[Signal, ...], [signal]),
            next_state=StrategyState(state_version="1.0.0", values=()),
            diagnostics=(),
        )
    with pytest.raises(StrategyInputError, match="signal_id"):
        StrategyResult(
            signals=(signal, signal),
            next_state=StrategyState(state_version="1.0.0", values=()),
            diagnostics=(),
        )


class MomentumStrategy:
    descriptor = _descriptor()

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState:
        return StrategyState(state_version="1.0.0", values=(("runs", 0),))

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        return StrategyResult(
            signals=(_signal(context),),
            next_state=StrategyState(state_version="1.0.0", values=(("runs", 1),)),
            diagnostics=("evaluated:1",),
        )

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        return StrategyResult(signals=(), next_state=state, diagnostics=("finalized",))


def test_strategy_protocol_and_result_validation_only_allow_context_bound_signals() -> None:
    strategy = MomentumStrategy()
    context = _context()
    parameters = validate_parameters(strategy.descriptor, {"lookback": 20})
    runner = StrategyRunner(strategy, parameters)
    state = runner.initialize(context)
    result = runner.on_decision(context, state)

    assert isinstance(strategy, Strategy)
    assert not hasattr(strategy, "on_decision")
    validated = validate_strategy_result(strategy.descriptor, context, result)
    assert validated == result
    assert validated is not result
    with pytest.raises(StrategyFutureDataError, match="decision_time"):
        validate_strategy_result(
            strategy.descriptor,
            context,
            replace(
                result,
                signals=(
                    replace(
                        result.signals[0],
                        decision_time=context.decision_time + timedelta(seconds=1),
                    ),
                ),
            ),
        )


def test_strategy_runner_rejects_unbound_hook_output_before_consumption() -> None:
    class ForgingStrategy(MomentumStrategy):
        def _on_decision(
            self,
            context: StrategyContext,
            parameters: StrategyParameters,
            state: StrategyState,
        ) -> StrategyResult:
            return StrategyResult(
                signals=(replace(_signal(context), input_snapshot_id="context:forged"),),
                next_state=state,
                diagnostics=("forged",),
            )

    context = _context()
    strategy = ForgingStrategy()
    parameters = validate_parameters(strategy.descriptor, {"lookback": 20})
    runner = StrategyRunner(strategy, parameters)
    valid_result = StrategyResult(
        signals=(_signal(context),),
        next_state=StrategyState(state_version="1.0.0", values=(("runs", 1),)),
        diagnostics=("evaluated:1",),
    )

    with pytest.raises(StrategyInputError, match="input_snapshot_id"):
        runner.on_decision(context, runner.initialize(context))
    with pytest.raises(StrategyInputError, match="outside context universe"):
        validate_strategy_result(
            strategy.descriptor,
            context,
            replace(
                valid_result,
                signals=(replace(valid_result.signals[0], entity_id="999999.SH"),),
            ),
        )
    with pytest.raises(StrategyInputError, match="missing required feature"):
        validate_strategy_result(
            strategy.descriptor,
            context,
            replace(
                valid_result,
                signals=(replace(valid_result.signals[0], entity_id="600002.SH"),),
            ),
        )


def test_strategy_runner_snapshots_descriptor_and_rejects_wrong_sdk() -> None:
    strategy = MomentumStrategy()
    original_descriptor = strategy.descriptor
    parameters = validate_parameters(original_descriptor, {"lookback": 20})
    runner = StrategyRunner(strategy, parameters)
    context = _context()

    strategy.descriptor = replace(
        original_descriptor,
        required_features=("missing.feature",),
    )
    assert runner.descriptor == original_descriptor
    assert runner.on_decision(context, runner.initialize(context)).signals

    incompatible_descriptor = replace(original_descriptor, sdk_version="9.0.0")
    incompatible = MomentumStrategy()
    incompatible.descriptor = incompatible_descriptor
    incompatible_parameters = validate_parameters(incompatible_descriptor, {"lookback": 20})
    with pytest.raises(StrategyInputError, match="sdk_version"):
        StrategyRunner(incompatible, incompatible_parameters)
