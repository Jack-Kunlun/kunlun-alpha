from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import backtest_core.engine.manifest as manifest_module
import backtest_core.engine.ports as ports_module
import backtest_core.engine.runtime as runtime_module
import pytest
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
from backtest_core.engine.runtime import (
    BacktestEngine,
    DeterministicEventQueue,
    DeterministicRandom,
    SimulationClock,
)
from quant_core.strategy import (
    STRATEGY_SDK_VERSION,
    FeatureValue,
    ParameterType,
    Signal,
    SignalDirection,
    StrategyContext,
    StrategyDescriptor,
    StrategyInputError,
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
        strategy_id="boundary.strategy",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Boundary test strategy",
        required_features=("feature.value",),
        parameter_specs=(
            StrategyParameterSpec(
                name="threshold",
                value_type=ParameterType.DECIMAL,
                required=True,
                description="Threshold",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
            ),
        ),
    )


DESCRIPTOR = _descriptor()
PARAMETERS = StrategyParameters(descriptor_version="1.0.0", values=(("threshold", Decimal("0.5")),))


def _context(at: datetime = START + timedelta(minutes=1)) -> StrategyContext:
    cutoff = at - timedelta(minutes=1)
    return StrategyContext(
        decision_time=at,
        data_cutoff_time=cutoff,
        snapshot_id="context:boundary",
        snapshot_version="1.0.0",
        universe=UniverseSnapshot(
            snapshot_id="universe:boundary",
            snapshot_version="1.0.0",
            as_of_time=cutoff - timedelta(minutes=1),
            available_time=cutoff - timedelta(seconds=2),
            processing_time=cutoff - timedelta(seconds=1),
            entity_ids=("600001.SH",),
        ),
        features=(
            FeatureValue(
                entity_id="600001.SH",
                feature_name="feature.value",
                feature_version="1.0.0",
                value=Decimal("0.7"),
                event_time=at - timedelta(days=1),
                available_time=cutoff - timedelta(seconds=2),
                processing_time=cutoff - timedelta(seconds=1),
                source_snapshot_id="features:boundary",
                source_snapshot_version="1.0.0",
            ),
        ),
    )


EVENT = ScheduledDecisionEvent(
    event_id="event:boundary",
    source_id="market",
    source_sequence=1,
    logical_time=START + timedelta(minutes=1),
    available_time=START - timedelta(minutes=1),
    context=_context(),
)


def _manifest(
    *,
    descriptor: StrategyDescriptor = DESCRIPTOR,
    parameters: StrategyParameters = PARAMETERS,
    strategy_fingerprint: str = "strategy:fingerprint:v1",
    policy_fingerprint: str = "policy:fingerprint:v1",
    events: object = (EVENT,),
) -> BacktestRunManifest:
    return BacktestRunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        engine_version=BACKTEST_ENGINE_VERSION,
        strategy_descriptor=descriptor,
        strategy_parameters=parameters,
        policy_id="boundary.policy",
        policy_version="1.0.0",
        strategy_implementation_fingerprint=strategy_fingerprint,
        policy_implementation_fingerprint=policy_fingerprint,
        dataset_id="dataset:boundary",
        dataset_version="1.0.0",
        dataset_digest="dataset:digest:v1",
        code_version="code:v1",
        config_version="config:v1",
        event_ordering_version=EVENT_ORDERING_VERSION,
        rng_algorithm=RNG_ALGORITHM,
        rng_seed="seed:boundary",
        start_time=START,
        end_time=START + timedelta(minutes=2),
        events=events,  # type: ignore[arg-type]
    )


class BoundaryStrategy:
    descriptor = DESCRIPTOR

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState:
        self.calls.append("initialize")
        return StrategyState(state_version="1.0.0", values=(("count", 0),))

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        self.calls.append("decision")
        return StrategyResult(signals=(_signal(),), next_state=state, diagnostics=("decision",))

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        self.calls.append("finalize")
        return StrategyResult(signals=(), next_state=state, diagnostics=("final",))


class ValidPolicy:
    policy_id = "boundary.policy"
    policy_version = "1.0.0"
    implementation_fingerprint = "policy:fingerprint:v1"

    def __init__(self, intent_factory: object | None = None) -> None:
        self.intent_factory = intent_factory

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
        if self.intent_factory is None:
            return ()
        return (
            self.intent_factory(signals, context.decision_time, manifest_digest),  # type: ignore[operator]
        )


class BoundaryProgram:
    strategy_implementation_fingerprint = "strategy:fingerprint:v1"
    policy_implementation_fingerprint = "policy:fingerprint:v1"

    def __init__(
        self,
        *,
        descriptor: StrategyDescriptor = DESCRIPTOR,
        parameters: StrategyParameters = PARAMETERS,
        strategy_fingerprint: str = "strategy:fingerprint:v1",
        policy_fingerprint: str = "policy:fingerprint:v1",
        policy: PortfolioIntentPolicy | None = None,
    ) -> None:
        self.descriptor = descriptor
        self.parameters = parameters
        self.strategy_implementation_fingerprint = strategy_fingerprint
        self.policy_implementation_fingerprint = policy_fingerprint
        self.calls: list[str] = []
        self.policy = policy

    def create_strategy_runner(self) -> StrategyRunner:
        strategy = BoundaryStrategy(self.calls)
        strategy.descriptor = self.descriptor
        return StrategyRunner(strategy, self.parameters)

    def create_portfolio_intent_policy(self) -> PortfolioIntentPolicy:
        return self.policy or ValidPolicy()


class WrongPolicyId(ValidPolicy):
    policy_id = "boundary.other-policy"


class WrongPolicyVersion(ValidPolicy):
    policy_version = "2.0.0"


class ListPolicy(ValidPolicy):
    def to_intents(  # type: ignore[override]
        self,
        signals: tuple[Signal, ...],
        *,
        context: StrategyContext,
        event_id: str,
        random_source: RandomSource,
        manifest_digest: str,
        domain: str,
    ) -> list[BacktestOrderIntent]:
        return list(
            super().to_intents(
                signals,
                context=context,
                event_id=event_id,
                random_source=random_source,
                manifest_digest=manifest_digest,
                domain=domain,
            )
        )


@pytest.mark.parametrize(
    "program_factory, manifest_factory, message",
    [
        (
            lambda: BoundaryProgram(descriptor=replace(DESCRIPTOR, strategy_id="other.strategy")),
            _manifest,
            "descriptor",
        ),
        (
            lambda: BoundaryProgram(
                parameters=StrategyParameters("1.0.0", (("threshold", Decimal("0.6")),))
            ),
            _manifest,
            "parameters",
        ),
        (lambda: BoundaryProgram(strategy_fingerprint="strategy:wrong"), _manifest, "fingerprint"),
        (lambda: BoundaryProgram(policy_fingerprint="policy:wrong"), _manifest, "fingerprint"),
    ],
)
def test_engine_rejects_program_manifest_mismatch_before_hooks(
    program_factory: Callable[[], BoundaryProgram],
    manifest_factory: Callable[[], BacktestRunManifest],
    message: str,
) -> None:
    program = program_factory()
    manifest = manifest_factory()

    with pytest.raises(StrategyInputError, match=message):
        BacktestEngine().run(manifest, program)  # type: ignore[arg-type]
    assert program.calls == []


@pytest.mark.parametrize("policy_type", [WrongPolicyId, WrongPolicyVersion])
def test_engine_rejects_policy_identity_before_strategy_hooks(
    policy_type: type[ValidPolicy],
) -> None:
    program = BoundaryProgram(policy=policy_type())

    with pytest.raises(StrategyInputError, match="policy identity"):
        BacktestEngine().run(_manifest(), program)
    assert program.calls == []


def test_engine_rejects_mutable_policy_output() -> None:
    program = BoundaryProgram(
        policy=cast(PortfolioIntentPolicy, ListPolicy(intent_factory=_bad_intent))
    )

    with pytest.raises(StrategyInputError, match="tuple"):
        BacktestEngine().run(_manifest(), program)


def _signal() -> Signal:
    context = EVENT.context
    return Signal(
        signal_id="signal:boundary",
        schema_version="signal-v1",
        strategy_id=DESCRIPTOR.strategy_id,
        strategy_version=DESCRIPTOR.strategy_version,
        algorithm_version=DESCRIPTOR.algorithm_version,
        entity_id="600001.SH",
        decision_time=context.decision_time,
        data_cutoff_time=context.data_cutoff_time,
        direction=SignalDirection.LONG,
        score=Decimal("0.7"),
        confidence=Decimal("0.8"),
        horizon_sessions=2,
        rationale="boundary signal",
        input_snapshot_id=context.snapshot_id,
        input_snapshot_version=context.snapshot_version,
        evidence_ids=("evidence:boundary",),
    )


class TwoSignalStrategy(BoundaryStrategy):
    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        first = _signal()
        second = replace(
            first,
            signal_id="signal:boundary-2",
            evidence_ids=("evidence:boundary-2",),
        )
        return StrategyResult(
            signals=(first, second),
            next_state=state,
            diagnostics=("two-signals",),
        )


class DuplicateIntentPolicy(ValidPolicy):
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
        return tuple(
            BacktestOrderIntent(
                intent_id="intent:duplicate",
                source_signal_id=signal.signal_id,
                entity_id=signal.entity_id,
                logical_time=context.decision_time,
                side=IntentSide.BUY,
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                policy_fingerprint=self.implementation_fingerprint,
                manifest_digest=manifest_digest,
            )
            for signal in signals
        )


class DuplicateIntentProgram(BoundaryProgram):
    def create_strategy_runner(self) -> StrategyRunner:
        strategy = TwoSignalStrategy(self.calls)
        strategy.descriptor = self.descriptor
        return StrategyRunner(strategy, self.parameters)


def _bad_intent(
    signals: tuple[Signal, ...], logical_time: datetime, digest: str
) -> BacktestOrderIntent:
    signal = signals[0]
    return BacktestOrderIntent(
        intent_id="intent:boundary",
        source_signal_id=signal.signal_id,
        entity_id=signal.entity_id,
        logical_time=logical_time,
        side=IntentSide.BUY,
        policy_id="boundary.policy",
        policy_version="1.0.0",
        policy_fingerprint="policy:fingerprint:v1",
        manifest_digest=digest,
    )


def test_intent_id_must_be_globally_unique_across_signals() -> None:
    program = DuplicateIntentProgram(policy=DuplicateIntentPolicy())

    with pytest.raises(StrategyInputError, match="intent_id.*unique"):
        BacktestEngine().run(_manifest(), program)


def test_intent_is_bound_to_signal_and_manifest_policy() -> None:
    def wrong_source(
        signals: tuple[Signal, ...], logical_time: datetime, digest: str
    ) -> BacktestOrderIntent:
        intent = _bad_intent(signals, logical_time, digest)
        return replace(intent, source_signal_id="signal:missing")

    with pytest.raises(StrategyInputError, match="source Signal"):
        BacktestEngine().run(_manifest(), BoundaryProgram(policy=ValidPolicy(wrong_source)))

    def wrong_entity(
        signals: tuple[Signal, ...], logical_time: datetime, digest: str
    ) -> BacktestOrderIntent:
        intent = _bad_intent(signals, logical_time, digest)
        return replace(intent, entity_id="600002.SH")

    with pytest.raises(StrategyInputError, match="entity"):
        BacktestEngine().run(_manifest(), BoundaryProgram(policy=ValidPolicy(wrong_entity)))

    def wrong_time(
        signals: tuple[Signal, ...], logical_time: datetime, digest: str
    ) -> BacktestOrderIntent:
        intent = _bad_intent(signals, logical_time, digest)
        return replace(intent, logical_time=logical_time + timedelta(seconds=1))

    with pytest.raises(StrategyInputError, match="logical time"):
        BacktestEngine().run(_manifest(), BoundaryProgram(policy=ValidPolicy(wrong_time)))

    def wrong_manifest(
        signals: tuple[Signal, ...], logical_time: datetime, digest: str
    ) -> BacktestOrderIntent:
        return replace(_bad_intent(signals, logical_time, digest), manifest_digest="wrong")

    with pytest.raises(StrategyInputError, match="manifest"):
        BacktestEngine().run(_manifest(), BoundaryProgram(policy=ValidPolicy(wrong_manifest)))

    def wrong_policy(
        signals: tuple[Signal, ...], logical_time: datetime, digest: str
    ) -> BacktestOrderIntent:
        return replace(_bad_intent(signals, logical_time, digest), policy_fingerprint="wrong")

    with pytest.raises(StrategyInputError, match="policy fingerprint"):
        BacktestEngine().run(_manifest(), BoundaryProgram(policy=ValidPolicy(wrong_policy)))


def test_intent_is_permanently_non_executable_and_has_no_order_fields() -> None:
    intent = _bad_intent((_signal(),), EVENT.logical_time, "0" * 64)
    names = {field.name for field in fields(intent)}

    assert intent.is_executable is False
    assert intent.execution_capability == "BACKTEST_ONLY"
    assert {
        "account",
        "broker",
        "client_order_id",
        "fill",
        "fee",
        "order",
        "price",
        "quantity",
        "slippage",
    }.isdisjoint(names)


def test_clock_is_logical_only_and_monotonic() -> None:
    clock = SimulationClock(START)
    assert clock.current_time == START
    clock.advance(START + timedelta(seconds=1))
    with pytest.raises(StrategyInputError, match="monotonic"):
        clock.advance(START)
    assert "datetime.now" not in inspect.getsource(SimulationClock)
    assert "time.time" not in inspect.getsource(SimulationClock)


def test_engine_modules_have_no_wall_clock_global_random_or_live_execution_dependency() -> None:
    source = "\n".join(
        inspect.getsource(module) for module in (runtime_module, manifest_module, ports_module)
    )
    forbidden = (
        "datetime.now",
        "time.time",
        "random.seed",
        "random.random",
        "uuid4",
        "os.urandom",
        "import random",
        "import uuid",
        "broker",
        "qmt",
        "execution",
    )
    assert all(token not in source.lower() for token in forbidden)


def test_logical_queue_and_random_boundaries_fail_closed() -> None:
    with pytest.raises(StrategyInputError, match="timezone-aware"):
        SimulationClock(START.replace(tzinfo=None))
    with pytest.raises(StrategyInputError, match="must not be empty"):
        DeterministicEventQueue(())

    queue = DeterministicEventQueue((EVENT,))
    assert queue.pop_next() == EVENT
    with pytest.raises(StrategyInputError, match="exhausted"):
        queue.pop_next()

    random_source = DeterministicRandom("0" * 64, "seed:one", domain="decision")
    with pytest.raises(StrategyInputError, match="length"):
        random_source.bytes("event", "purpose", 0, length=0)
    with pytest.raises(StrategyInputError, match="index"):
        random_source.bytes("event", "purpose", -1)
    with pytest.raises(StrategyInputError, match="upper_bound"):
        random_source.integer("event", "purpose", 0, 0)
    with pytest.raises(StrategyInputError, match="algorithm"):
        DeterministicRandom("0" * 64, "seed:one", domain="decision", algorithm="unsupported")


def test_result_trace_manifest_events_and_intents_are_deeply_immutable() -> None:
    result = BacktestEngine().run(_manifest(), BoundaryProgram())

    with pytest.raises((TypeError, FrozenInstanceError)):
        result.trace[0].intents += ()  # type: ignore[misc]
    with pytest.raises((TypeError, FrozenInstanceError)):
        result.manifest.events += ()  # type: ignore[misc]
