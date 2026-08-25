from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from backtest_core.engine.manifest import (
    BACKTEST_ENGINE_VERSION,
    EVENT_ORDERING_VERSION,
    MANIFEST_SCHEMA_VERSION,
    RNG_ALGORITHM,
    BacktestRunManifest,
    canonical_digest,
)
from backtest_core.engine.models import (
    BacktestOrderIntent,
    BacktestRunResult,
    IntentSide,
    ScheduledDecisionEvent,
)
from backtest_core.engine.ports import PortfolioIntentPolicy, RandomSource
from backtest_core.engine.runtime import BacktestEngine, DeterministicRandom
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
        strategy_id="determinism.strategy",
        strategy_version="1.0.0",
        algorithm_version="1.0.0",
        sdk_version=STRATEGY_SDK_VERSION,
        lifecycle_version="1.0.0",
        description="Determinism test strategy",
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


def _context(at: datetime, snapshot_id: str) -> StrategyContext:
    cutoff = at - timedelta(minutes=1)
    return StrategyContext(
        decision_time=at,
        data_cutoff_time=cutoff,
        snapshot_id=snapshot_id,
        snapshot_version="1.0.0",
        universe=UniverseSnapshot(
            snapshot_id=f"universe:{snapshot_id}",
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
                source_snapshot_id=f"features:{snapshot_id}",
                source_snapshot_version="1.0.0",
            ),
        ),
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


def _manifest(
    events: object,
    seed: str = "seed:one",
    *,
    descriptor: StrategyDescriptor = DESCRIPTOR,
    parameters: StrategyParameters = PARAMETERS,
) -> BacktestRunManifest:
    return BacktestRunManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        engine_version=BACKTEST_ENGINE_VERSION,
        strategy_descriptor=descriptor,
        strategy_parameters=parameters,
        policy_id="determinism.policy",
        policy_version="1.0.0",
        strategy_implementation_fingerprint="strategy:fingerprint:v1",
        policy_implementation_fingerprint="policy:fingerprint:v1",
        dataset_id="dataset:determinism",
        dataset_version="1.0.0",
        dataset_digest="dataset:digest:v1",
        code_version="code:v1",
        config_version="config:v1",
        event_ordering_version=EVENT_ORDERING_VERSION,
        rng_algorithm=RNG_ALGORITHM,
        rng_seed=seed,
        start_time=START,
        end_time=START + timedelta(minutes=10),
        events=events,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("parameters", "message"),
    (
        (
            StrategyParameters(
                descriptor_version="1.0.0",
                values=(
                    ("extra", Decimal("0.5")),
                    ("threshold", Decimal("0.5")),
                ),
            ),
            "unknown parameter",
        ),
        (
            StrategyParameters(descriptor_version="1.0.0", values=()),
            "missing required parameter",
        ),
        (
            StrategyParameters(descriptor_version="1.0.0", values=(("threshold", 1),)),
            "must be a finite DECIMAL",
        ),
        (
            StrategyParameters(descriptor_version="1.0.0", values=(("threshold", Decimal("2")),)),
            "exceeds maximum",
        ),
    ),
)
def test_manifest_rejects_parameters_outside_descriptor_specs(
    parameters: StrategyParameters, message: str
) -> None:
    with pytest.raises(StrategyInputError, match=message):
        _manifest((_event("event-parameter-spec", 1, 1),), parameters=parameters)


def _signal(context: StrategyContext) -> Signal:
    return Signal(
        signal_id=f"signal:{context.snapshot_id}",
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
        rationale="deterministic signal",
        input_snapshot_id=context.snapshot_id,
        input_snapshot_version=context.snapshot_version,
        evidence_ids=(f"evidence:{context.snapshot_id}",),
    )


class DeterministicStrategy:
    descriptor = DESCRIPTOR

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState:
        return StrategyState(state_version="1.0.0", values=(("count", 0),))

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        return StrategyResult(
            signals=(_signal(context),),
            next_state=StrategyState(
                state_version="1.0.0",
                values=(("count", int(state.get("count") or 0) + 1),),
            ),
            diagnostics=("stable",),
        )

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult:
        return StrategyResult(signals=(), next_state=state, diagnostics=("final",))


class DeterministicPolicy:
    policy_id = "determinism.policy"
    policy_version = "1.0.0"
    implementation_fingerprint = "policy:fingerprint:v1"

    observed_random_domains: list[tuple[str, str, bytes]] = []

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
        self.observed_random_domains.append(
            (domain, random_source.domain_name, random_source.bytes(event_id, "side", 0))
        )
        return tuple(
            BacktestOrderIntent(
                intent_id=(
                    f"intent:{signal.signal_id}:"
                    f"{random_source.integer(event_id, 'intent-id', 0, 1_000_000_000_000):012d}"
                ),
                source_signal_id=signal.signal_id,
                entity_id=signal.entity_id,
                logical_time=context.decision_time,
                side=(
                    IntentSide.BUY
                    if random_source.integer(event_id, "side", 0, 2) == 0
                    else IntentSide.SELL
                ),
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                policy_fingerprint=self.implementation_fingerprint,
                manifest_digest=manifest_digest,
            )
            for signal in signals
        )


class DeterministicProgram:
    strategy_implementation_fingerprint = "strategy:fingerprint:v1"
    policy_implementation_fingerprint = "policy:fingerprint:v1"

    def create_strategy_runner(self) -> StrategyRunner:
        return StrategyRunner(DeterministicStrategy(), PARAMETERS)

    def create_portfolio_intent_policy(self) -> PortfolioIntentPolicy:
        return DeterministicPolicy()


def test_repeated_runs_are_equal_even_when_interleaved_with_another_manifest() -> None:
    events = (_event("event-2", 2, 2), _event("event-1", 1, 1))
    manifest = _manifest(events)
    equivalent_manifest = _manifest(tuple(reversed(events)))
    other_manifest = _manifest(events, seed="seed:other")
    engine = BacktestEngine()
    program = DeterministicProgram()

    first = engine.run(manifest, program)
    interleaved = engine.run(other_manifest, program)
    second = engine.run(equivalent_manifest, program)

    assert first == second
    assert first.result_digest == second.result_digest
    assert first.manifest.manifest_digest == second.manifest.manifest_digest
    assert interleaved.result_digest != first.result_digest


def test_policy_rng_is_per_run_and_seed_changes_observable_intent_side() -> None:
    event = _event("event-rng", 1, 1)
    alpha_source = DeterministicRandom("0" * 64, "seed:alpha", domain="decision")
    three_source = DeterministicRandom("0" * 64, "seed:3", domain="decision")
    assert alpha_source.bytes("event-rng", "raw", 0) != three_source.bytes("event-rng", "raw", 0)

    first = BacktestEngine().run(_manifest((event,), seed="seed:alpha"), DeterministicProgram())
    second = BacktestEngine().run(_manifest((event,), seed="seed:3"), DeterministicProgram())

    assert first.trace[0].intents[0].intent_id != second.trace[0].intents[0].intent_id


def test_counter_random_is_local_and_purpose_index_are_domain_separated() -> None:
    source = DeterministicRandom("0" * 64, "seed:one", domain="decision")
    same = DeterministicRandom("0" * 64, "seed:one", domain="decision")
    different = DeterministicRandom("0" * 64, "seed:one", domain="decision")

    assert source.bytes("event-1", "slippage", 0) == same.bytes("event-1", "slippage", 0)
    assert source.unit_value("event-1", "slippage", 0) == same.unit_value("event-1", "slippage", 0)
    assert source.bytes("event-1", "slippage", 0) != different.bytes("event-1", "fees", 0)
    assert source.bytes("event-1", "slippage", 0) != different.bytes("event-1", "slippage", 1)
    assert source.integer("event-1", "slippage", 0, 10_000) == same.integer(
        "event-1", "slippage", 0, 10_000
    )


def test_random_domain_is_structural_and_lifecycle_domains_are_distinct() -> None:
    digest = "0" * 64
    decision = DeterministicRandom(digest, "seed:one", domain="decision")
    decision_again = DeterministicRandom(digest, "seed:one", domain="decision")
    finalize = DeterministicRandom(digest, "seed:one", domain="finalize")

    assert decision.manifest_digest == digest
    assert decision.domain_name == "decision"
    assert decision.bytes("event-1", "same-purpose", 0) == decision_again.bytes(
        "event-1", "same-purpose", 0
    )
    assert decision.bytes("event-1", "same-purpose", 0) != finalize.bytes(
        "event-1", "same-purpose", 0
    )


def test_engine_injects_lifecycle_domain_without_policy_domain_concatenation() -> None:
    DeterministicPolicy.observed_random_domains.clear()
    event = _event("event-domain", 1, 1)

    BacktestEngine().run(_manifest((event,)), DeterministicProgram())

    observations = DeterministicPolicy.observed_random_domains
    assert [(domain, random_domain) for domain, random_domain, _ in observations] == [
        ("decision", "decision"),
        ("finalize", "finalize"),
    ]
    assert observations[0][2] != observations[1][2]


def _valid_result() -> BacktestRunResult:
    events = (_event("event-result-1", 1, 1), _event("event-result-2", 2, 2))
    return BacktestEngine().run(_manifest(events), DeterministicProgram())


def _forged_strategy_result(
    result: StrategyResult,
    *,
    signals: object,
    diagnostics: object,
    next_state: object | None = None,
) -> StrategyResult:
    forged = object.__new__(StrategyResult)
    object.__setattr__(forged, "signals", signals)
    object.__setattr__(
        forged, "next_state", result.next_state if next_state is None else next_state
    )
    object.__setattr__(forged, "diagnostics", diagnostics)
    return forged


def test_trace_rejects_semantically_forged_signal_and_intent_members() -> None:
    result = _valid_result()
    trace = result.trace[0]

    with pytest.raises(Exception, match="Signal"):
        replace(trace, signals=(object(),))
    with pytest.raises(Exception, match="BacktestOrderIntent"):
        replace(trace, intents=(object(),))


def test_trace_rejects_intent_source_entity_and_time_mismatch() -> None:
    result = _valid_result()
    trace = result.trace[0]
    intent = trace.intents[0]

    cases = (
        (replace(intent, source_signal_id="signal:missing"), "source Signal"),
        (replace(intent, entity_id="000002.SZ"), "entity"),
        (
            replace(intent, logical_time=trace.logical_time + timedelta(minutes=1)),
            "logical time",
        ),
    )
    for bad_intent, message in cases:
        with pytest.raises(Exception, match=message):
            replace(trace, intents=(bad_intent,))


def test_result_rejects_trace_event_context_state_and_policy_binding_mismatches() -> None:
    result = _valid_result()
    first, second = result.trace
    forged_context = replace(first.context, snapshot_id="context:forged")
    coherent_time_forgery = replace(
        first,
        logical_time=second.logical_time,
        context=second.context,
        signals=second.signals,
        intents=second.intents,
    )

    cases = (
        ((replace(first, event_id="event:wrong"), second), "event_id"),
        ((coherent_time_forgery, second), "logical_time"),
        ((replace(first, context=forged_context), second), "context"),
        ((first, replace(second, state_before=first.state_before)), "state"),
        (
            (
                replace(first, intents=(replace(first.intents[0], manifest_digest="0" * 64),)),
                second,
            ),
            "manifest_digest",
        ),
        (
            (
                replace(first, intents=(replace(first.intents[0], policy_id="wrong.policy"),)),
                second,
            ),
            "policy",
        ),
    )
    for bad_trace, message in cases:
        with pytest.raises(Exception, match=message):
            replace(result, trace=bad_trace)


def test_result_rejects_forged_finalize_intent_and_finalize_result() -> None:
    result = _valid_result()
    first = result.trace[0]
    bad_finalize_intent = BacktestOrderIntent(
        intent_id="intent:finalize",
        source_signal_id=first.signals[0].signal_id,
        entity_id=first.signals[0].entity_id,
        logical_time=first.logical_time,
        side=IntentSide.BUY,
        policy_id=result.manifest.policy_id,
        policy_version=result.manifest.policy_version,
        policy_fingerprint=result.manifest.policy_implementation_fingerprint,
        manifest_digest=result.manifest.manifest_digest,
    )
    with pytest.raises(Exception, match="finalize"):
        replace(result, finalize_intents=(bad_finalize_intent,))

    forged_finalize = _forged_strategy_result(
        result.finalize_result,
        signals=[first.signals[0]],
        diagnostics=["final"],
        next_state=object(),
    )
    with pytest.raises(Exception, match="finalize_result"):
        replace(result, finalize_result=forged_finalize)


def test_result_rejects_forged_members_state_and_digest() -> None:
    result = _valid_result()
    with pytest.raises(Exception, match="BacktestDecisionTrace"):
        replace(result, trace=(object(), result.trace[1]))
    with pytest.raises(Exception, match="BacktestOrderIntent"):
        replace(result, finalize_intents=(object(),))
    with pytest.raises(Exception, match="final_state"):
        replace(result, final_state=StrategyState(state_version="1.0.0", values=()))
    with pytest.raises(Exception, match="result_digest"):
        replace(result, result_digest="0" * 64)


def test_result_digest_must_match_canonical_payload() -> None:
    result = _valid_result()
    expected = canonical_digest(
        {
            "manifest": result.manifest,
            "trace": result.trace,
            "finalize_result": result.finalize_result,
            "finalize_intents": result.finalize_intents,
            "final_state": result.final_state,
        }
    )
    assert result.result_digest == expected


class _FactoryProbe:
    strategy_implementation_fingerprint = "strategy:fingerprint:v1"
    policy_implementation_fingerprint = "policy:fingerprint:v1"

    def __init__(self) -> None:
        self.factory_calls = 0

    def create_strategy_runner(self) -> StrategyRunner:
        self.factory_calls += 1
        raise AssertionError("factory must not be called")

    def create_portfolio_intent_policy(self) -> PortfolioIntentPolicy:
        self.factory_calls += 1
        raise AssertionError("factory must not be called")


def test_engine_revalidates_manifest_before_any_program_factory() -> None:
    manifest = _manifest((_event("event-integrity", 1, 1),))
    object.__setattr__(manifest, "manifest_digest", "0" * 64)
    program = _FactoryProbe()

    with pytest.raises(Exception, match="manifest"):
        BacktestEngine().run(manifest, program)  # type: ignore[arg-type]
    assert program.factory_calls == 0


def test_engine_rejects_rehashed_parameter_spec_forgery_before_any_program_factory() -> None:
    manifest = _manifest(
        (_event("event-integrity-parameters-rehashed", 1, 1),),
        parameters=replace(PARAMETERS),
    )
    object.__setattr__(manifest.strategy_parameters, "values", (("threshold", Decimal("2")),))
    object.__setattr__(
        manifest,
        "manifest_digest",
        hashlib.sha256(manifest.to_canonical_json().encode("utf-8")).hexdigest(),
    )
    program = _FactoryProbe()

    with pytest.raises(StrategyInputError, match="exceeds maximum"):
        BacktestEngine().run(manifest, program)  # type: ignore[arg-type]
    assert program.factory_calls == 0


def test_engine_revalidates_forged_context_and_event_before_any_program_factory() -> None:
    manifest = _manifest((_event("event-integrity-context", 1, 1),))
    object.__setattr__(manifest.events[0].context, "data_cutoff_time", START + timedelta(hours=1))
    program = _FactoryProbe()

    with pytest.raises(Exception, match="context|cutoff"):
        BacktestEngine().run(manifest, program)  # type: ignore[arg-type]
    assert program.factory_calls == 0

    manifest = _manifest((_event("event-integrity-event", 1, 1),))
    object.__setattr__(manifest.events[0], "available_time", START + timedelta(hours=1))
    program = _FactoryProbe()

    with pytest.raises(Exception, match="event|available"):
        BacktestEngine().run(manifest, program)  # type: ignore[arg-type]
    assert program.factory_calls == 0


def test_manifest_integrity_rejects_forged_descriptor_parameters_and_event_order() -> None:
    manifest = _manifest(
        (_event("event-integrity-2", 2, 2), _event("event-integrity-1", 1, 1)),
        descriptor=replace(DESCRIPTOR),
    )
    object.__setattr__(manifest.strategy_descriptor, "strategy_id", "forged.strategy")
    with pytest.raises(Exception, match="manifest_digest|descriptor|strategy"):
        manifest.validate_integrity()

    manifest = _manifest(
        (_event("event-integrity-parameters", 1, 1),),
        parameters=replace(PARAMETERS),
    )
    object.__setattr__(manifest.strategy_parameters, "descriptor_version", "9.0.0")
    with pytest.raises(Exception, match="parameter|descriptor"):
        manifest.validate_integrity()

    manifest = _manifest(
        (_event("event-integrity-order-2", 2, 2), _event("event-integrity-order-1", 1, 1))
    )
    object.__setattr__(manifest, "events", tuple(reversed(manifest.events)))
    with pytest.raises(Exception, match="canonical|order"):
        manifest.validate_integrity()


def _rehashed_result(
    result: BacktestRunResult,
    *,
    trace: tuple[object, ...] | None = None,
    finalize_result: StrategyResult | None = None,
    final_state: object | None = None,
) -> BacktestRunResult:
    changed_trace = result.trace if trace is None else trace
    changed_finalize = result.finalize_result if finalize_result is None else finalize_result
    changed_final_state = result.final_state if final_state is None else final_state
    digest = canonical_digest(
        {
            "manifest": result.manifest,
            "trace": changed_trace,
            "finalize_result": changed_finalize,
            "finalize_intents": result.finalize_intents,
            "final_state": changed_final_state,
        }
    )
    return replace(
        result,
        trace=changed_trace,  # type: ignore[arg-type]
        finalize_result=changed_finalize,
        final_state=changed_final_state,  # type: ignore[arg-type]
        result_digest=digest,
    )


def test_trace_revalidates_nominally_forged_context_signal_and_intent() -> None:
    result = _valid_result()
    trace = result.trace[0]

    forged_context = replace(trace.context)
    object.__setattr__(
        forged_context, "data_cutoff_time", trace.logical_time + timedelta(seconds=1)
    )
    with pytest.raises(Exception, match="context|cutoff"):
        replace(trace, context=forged_context)

    forged_signal = replace(trace.signals[0])
    object.__setattr__(forged_signal, "score", Decimal("2"))
    with pytest.raises(Exception, match="signal|score"):
        replace(trace, signals=(forged_signal, *trace.signals[1:]))

    forged_intent = replace(trace.intents[0])
    object.__setattr__(forged_intent, "is_executable", True)
    with pytest.raises(Exception, match="executable|intent"):
        replace(trace, intents=(forged_intent,))


def test_result_rejects_rehashed_signal_state_and_finalize_semantic_forgery() -> None:
    result = _valid_result()
    first, second = result.trace

    forged_signal = replace(first.signals[0])
    object.__setattr__(forged_signal, "strategy_version", "2.0.0")
    forged_first = replace(first, signals=(forged_signal, *first.signals[1:]))
    with pytest.raises(Exception, match="strategy|signal"):
        _rehashed_result(result, trace=(forged_first, second))

    forged_state = replace(first.state_after)
    object.__setattr__(forged_state, "state_version", "2.0.0")
    forged_first = replace(first, state_after=forged_state)
    forged_second = replace(second, state_before=forged_state)
    with pytest.raises(Exception, match="state|lifecycle"):
        _rehashed_result(result, trace=(forged_first, forged_second))

    final_signal = replace(second.signals[0], signal_id="signal:finalize")
    object.__setattr__(final_signal, "strategy_id", "forged.strategy")
    forged_finalize = StrategyResult(
        signals=(final_signal,),
        next_state=result.final_state,
        diagnostics=("finalized",),
    )
    with pytest.raises(Exception, match="finalize|strategy|signal"):
        _rehashed_result(result, finalize_result=forged_finalize)


def test_rng_v2_is_length_prefixed_typed_and_rejects_before_modulo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = DeterministicRandom("0" * 64, "1", domain="decision")
    integer_seed = DeterministicRandom("0" * 64, 1, domain="decision")
    assert source.bytes("event", "purpose", 0) != integer_seed.bytes("event", "purpose", 0)
    assert source.bytes("a\x00b", "c", 0) != source.bytes("a", "b\x00c", 0)

    blocks = [((1 << 256) - 1).to_bytes(32, "big"), (7).to_bytes(32, "big")]
    observed_blocks: list[int] = []

    def fake_block(
        self: DeterministicRandom,
        event_id: str,
        purpose: str,
        index: int,
        block: int,
    ) -> bytes:
        observed_blocks.append(block)
        return blocks.pop(0)

    monkeypatch.setattr(DeterministicRandom, "_block", fake_block)
    assert source.integer("event", "purpose", 0, 10) == 7
    assert observed_blocks == [0, 1]


def test_rng_v2_fixed_vector() -> None:
    source = DeterministicRandom(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "seed:vector",
        domain="decision",
    )

    assert source.bytes("event:vector", "purpose:vector", 0).hex() == (
        "5c18614c9cff95f885702493caa132a5630562a72ea2f2308153a8538602fea3"
    )
