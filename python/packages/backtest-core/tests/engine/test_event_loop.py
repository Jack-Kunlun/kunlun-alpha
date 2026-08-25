from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backtest_core.engine.manifest import (
    BACKTEST_ENGINE_VERSION,
    EVENT_ORDERING_VERSION,
    MANIFEST_SCHEMA_VERSION,
    RNG_ALGORITHM,
    BacktestRunManifest,
)
from backtest_core.engine.models import (
    BacktestOrderIntent,
    IntentSide,
    ScheduledDecisionEvent,
)
from backtest_core.engine.ports import PortfolioIntentPolicy, RandomSource
from backtest_core.engine.runtime import BacktestEngine
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

START = datetime(2026, 6, 1, 7, tzinfo=UTC)


def _descriptor() -> StrategyDescriptor:
    return StrategyDescriptor(
        strategy_id="event.loop",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Event loop test strategy",
        required_features=("feature.value",),
        parameter_specs=(
            StrategyParameterSpec(
                name="threshold",
                value_type=ParameterType.DECIMAL,
                required=True,
                description="Signal threshold",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
            ),
        ),
    )


DESCRIPTOR = _descriptor()
PARAMETERS = StrategyParameters(descriptor_version="1.0.0", values=(("threshold", Decimal("0.5")),))


def _context(at: datetime, snapshot_id: str) -> StrategyContext:
    cutoff = at - timedelta(minutes=1)
    universe = UniverseSnapshot(
        snapshot_id=f"universe:{snapshot_id}",
        snapshot_version="1.0.0",
        as_of_time=cutoff - timedelta(minutes=1),
        available_time=cutoff - timedelta(seconds=2),
        processing_time=cutoff - timedelta(seconds=1),
        entity_ids=("600001.SH",),
    )
    feature = FeatureValue(
        entity_id="600001.SH",
        feature_name="feature.value",
        feature_version="1.0.0",
        value=Decimal("0.8"),
        event_time=at - timedelta(days=1),
        available_time=cutoff - timedelta(seconds=2),
        processing_time=cutoff - timedelta(seconds=1),
        source_snapshot_id=f"features:{snapshot_id}",
        source_snapshot_version="1.0.0",
    )
    return StrategyContext(
        decision_time=at,
        data_cutoff_time=cutoff,
        snapshot_id=snapshot_id,
        snapshot_version="1.0.0",
        universe=universe,
        features=(feature,),
    )


def _event(event_id: str, minute: int, sequence: int) -> ScheduledDecisionEvent:
    at = START + timedelta(minutes=minute)
    return ScheduledDecisionEvent(
        event_id=event_id,
        source_id="market",
        source_sequence=sequence,
        logical_time=at,
        available_time=at - timedelta(minutes=2),
        context=_context(at, f"context:{event_id}"),
    )


def _manifest(events: object) -> BacktestRunManifest:
    return BacktestRunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        engine_version=BACKTEST_ENGINE_VERSION,
        strategy_descriptor=DESCRIPTOR,
        strategy_parameters=PARAMETERS,
        policy_id="explicit.side-policy",
        policy_version="1.0.0",
        strategy_implementation_fingerprint="strategy:fingerprint:v1",
        policy_implementation_fingerprint="policy:fingerprint:v1",
        dataset_id="dataset:event-loop",
        dataset_version="1.0.0",
        dataset_digest="dataset:digest:v1",
        code_version="code:v1",
        config_version="config:v1",
        event_ordering_version=EVENT_ORDERING_VERSION,
        rng_algorithm=RNG_ALGORITHM,
        rng_seed="seed:event-loop",
        start_time=START,
        end_time=START + timedelta(minutes=10),
        events=events,  # type: ignore[arg-type]
    )


def _signal(context: StrategyContext, signal_id: str) -> Signal:
    return Signal(
        signal_id=signal_id,
        schema_version="signal-v1",
        strategy_id=DESCRIPTOR.strategy_id,
        strategy_version=DESCRIPTOR.strategy_version,
        algorithm_version=DESCRIPTOR.algorithm_version,
        entity_id="600001.SH",
        decision_time=context.decision_time,
        data_cutoff_time=context.data_cutoff_time,
        direction=SignalDirection.LONG,
        score=Decimal("0.8"),
        confidence=Decimal("0.9"),
        horizon_sessions=2,
        rationale="deterministic test signal",
        input_snapshot_id=context.snapshot_id,
        input_snapshot_version=context.snapshot_version,
        evidence_ids=(f"evidence:{signal_id}",),
    )


class RecordingStrategy:
    descriptor = DESCRIPTOR

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState:
        self.calls.append("initialize")
        return StrategyState(state_version="1.0.0", values=(("decisions", 0),))

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        self.calls.append(f"decision:{context.snapshot_id}")
        second = _signal(context, f"signal:z:{context.snapshot_id}")
        first = _signal(context, f"signal:a:{context.snapshot_id}")
        return StrategyResult(
            signals=(second, first),
            next_state=StrategyState(
                state_version="1.0.0",
                values=(("decisions", int(state.get("decisions") or 0) + 1),),
            ),
            diagnostics=("decision-complete",),
        )

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        self.calls.append("finalize")
        return StrategyResult(signals=(), next_state=state, diagnostics=("finalized",))


class RecordingPolicy:
    policy_id = "explicit.side-policy"
    policy_version = "1.0.0"
    implementation_fingerprint = "policy:fingerprint:v1"

    def __init__(self, calls: list[tuple[str, ...]]) -> None:
        self.calls = calls

    def to_intents(
        self,
        signals: tuple[Signal, ...],
        *,
        context: StrategyContext,
        event_id: str,
        random_source: RandomSource,
        manifest_digest: str,
        domain: str,
    ) -> tuple[BacktestOrderIntent, ...]:
        self.calls.append(tuple(signal.signal_id for signal in signals))
        return tuple(
            BacktestOrderIntent(
                intent_id=f"intent:{signal.signal_id}",
                source_signal_id=signal.signal_id,
                entity_id=signal.entity_id,
                logical_time=context.decision_time,
                side=IntentSide.BUY,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                policy_fingerprint=self.implementation_fingerprint,
                manifest_digest=manifest_digest,
            )
            for signal in reversed(signals)
        )


class RecordingProgram:
    strategy_implementation_fingerprint = "strategy:fingerprint:v1"
    policy_implementation_fingerprint = "policy:fingerprint:v1"

    def __init__(self) -> None:
        self.strategy_calls: list[str] = []
        self.policy_calls: list[tuple[str, ...]] = []
        self.runner_count = 0
        self.policy_count = 0

    def create_strategy_runner(self) -> StrategyRunner:
        self.runner_count += 1
        return StrategyRunner(RecordingStrategy(self.strategy_calls), PARAMETERS)

    def create_portfolio_intent_policy(self) -> PortfolioIntentPolicy:
        self.policy_count += 1
        return RecordingPolicy(self.policy_calls)


def test_event_loop_calls_lifecycle_and_stably_orders_signals_and_intents() -> None:
    manifest = _manifest((_event("event-2", 2, 2), _event("event-1", 1, 1)))
    program = RecordingProgram()

    result = BacktestEngine().run(manifest, program)

    assert program.runner_count == 1
    assert program.policy_count == 1
    assert program.strategy_calls == [
        "initialize",
        "decision:context:event-1",
        "decision:context:event-2",
        "finalize",
    ]
    assert result.manifest == manifest
    assert tuple(item.event_id for item in result.trace) == ("event-1", "event-2")
    assert tuple(item.signal_id for item in result.trace[0].signals) == (
        "signal:a:context:event-1",
        "signal:z:context:event-1",
    )
    assert tuple(item.source_signal_id for item in result.trace[0].intents) == (
        "signal:a:context:event-1",
        "signal:z:context:event-1",
    )
    assert result.finalize_result.diagnostics == ("finalized",)
    assert result.finalize_intents == ()
    assert result.final_state.get("decisions") == 2
    assert result.result_digest
