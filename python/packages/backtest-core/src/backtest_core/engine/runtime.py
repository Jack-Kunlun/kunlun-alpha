from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Protocol, cast

from quant_core.strategy import (
    Signal,
    StrategyContext,
    StrategyInputError,
    StrategyResult,
    StrategyRunner,
)

from .manifest import (
    RNG_ALGORITHM,
    BacktestRunManifest,
    canonical_digest,
    event_sort_key,
)
from .models import (
    BacktestDecisionTrace,
    BacktestOrderIntent,
    BacktestRunResult,
    BacktestValidationError,
    ScheduledDecisionEvent,
    require_aware,
    require_hex_digest,
    require_non_empty,
    revalidate_backtest_order_intent,
    revalidate_scheduled_decision_event,
    revalidate_strategy_context,
    revalidate_strategy_result,
    revalidate_strategy_state,
    validate_strategy_result_binding,
)
from .ports import BacktestProgram, PortfolioIntentPolicy, RandomSource


class SimulationClock:
    """Monotonic logical clock initialized solely from a manifest boundary."""

    __slots__ = ("_current_time",)

    def __init__(self, start_time: datetime) -> None:
        self._current_time = require_aware(start_time, "start_time")

    @property
    def current_time(self) -> datetime:
        return self._current_time

    def advance(self, logical_time: datetime) -> None:
        value = require_aware(logical_time, "logical_time")
        if value < self._current_time:
            raise BacktestValidationError("logical clock must be monotonic")
        self._current_time = value


def _length_prefix(value: bytes) -> bytes:
    if len(value) >= 1 << 64:
        raise BacktestValidationError("random field is too large")
    return len(value).to_bytes(8, byteorder="big") + value


class DeterministicEventQueue:
    """Per-run queue with a fixed total order and no wall-clock behavior."""

    __slots__ = ("_events", "_position")

    def __init__(self, events: tuple[ScheduledDecisionEvent, ...]) -> None:
        if type(events) is not tuple:
            raise BacktestValidationError("event queue events must be an exact tuple")
        normalized = cast(tuple[object, ...], events)
        if not normalized:
            raise BacktestValidationError("event queue must not be empty")
        typed_events = [
            revalidate_scheduled_decision_event(event_value, f"event queue[{index}]")
            for index, event_value in enumerate(normalized)
        ]
        self._events = tuple(sorted(typed_events, key=event_sort_key))
        self._position = 0

    @property
    def has_next(self) -> bool:
        return self._position < len(self._events)

    def pop_next(self) -> ScheduledDecisionEvent:
        if not self.has_next:
            raise BacktestValidationError("event queue is exhausted")
        event = self._events[self._position]
        self._position += 1
        return event


class DeterministicRandom:
    """Local SHA-256 counter source keyed by a structured run and event domain."""

    __slots__ = ("_manifest_digest", "_seed", "_algorithm_name", "_domain_name")
    algorithm = RNG_ALGORITHM

    def __init__(
        self,
        manifest_digest: str,
        seed: str | int,
        *,
        domain: str,
        algorithm: str = algorithm,
    ) -> None:
        manifest_digest = require_hex_digest(manifest_digest, "manifest_digest")
        if type(seed) not in (str, int) or (isinstance(seed, str) and not seed.strip()):
            raise BacktestValidationError("seed must be a non-empty string or integer")
        domain = require_non_empty(domain, "domain")
        if algorithm != self.algorithm:
            raise BacktestValidationError(f"unsupported random algorithm: {algorithm}")
        object.__setattr__(self, "_manifest_digest", manifest_digest)
        object.__setattr__(self, "_seed", seed)
        object.__setattr__(self, "_algorithm_name", algorithm)
        object.__setattr__(self, "_domain_name", domain)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("DeterministicRandom is immutable")

    @property
    def manifest_digest(self) -> str:
        return self._manifest_digest

    @property
    def seed(self) -> str | int:
        return self._seed

    @property
    def algorithm_name(self) -> str:
        return self._algorithm_name

    @property
    def domain_name(self) -> str:
        return self._domain_name

    def _block(self, event_id: str, purpose: str, index: int, block: int) -> bytes:
        require_non_empty(event_id, "event_id")
        require_non_empty(purpose, "purpose")
        if type(index) is not int or index < 0:
            raise BacktestValidationError("random index must be non-negative")
        if type(block) is not int or block < 0:
            raise BacktestValidationError("random block must be non-negative")
        seed_tag = b"I" if type(self.seed) is int else b"S"
        seed_payload = seed_tag + _length_prefix(str(self.seed).encode("utf-8"))
        fields = (
            b"backtest-rng-v2",
            b"algorithm",
            self.algorithm_name.encode("utf-8"),
            b"domain",
            self.domain_name.encode("utf-8"),
            b"manifest_digest",
            self.manifest_digest.encode("ascii"),
            b"seed",
            seed_payload,
            b"event_id",
            event_id.encode("utf-8"),
            b"purpose",
            purpose.encode("utf-8"),
            b"index",
            str(index).encode("ascii"),
            b"block",
            str(block).encode("ascii"),
        )
        payload = b"".join(_length_prefix(value) for value in fields)
        return hashlib.sha256(payload).digest()

    def bytes(self, event_id: str, purpose: str, index: int, length: int = 32) -> bytes:
        if type(length) is not int or length <= 0:
            raise BacktestValidationError("random byte length must be positive")
        blocks = tuple(
            self._block(event_id, purpose, index, block) for block in range((length + 31) // 32)
        )
        return b"".join(blocks)[:length]

    def unit_value(self, event_id: str, purpose: str, index: int) -> Decimal:
        raw = self.bytes(event_id, purpose, index, 32)
        with localcontext() as context:
            context.prec = 80
            return Decimal(int.from_bytes(raw, byteorder="big")) / Decimal(1 << 256)

    def unit_decimal(self, event_id: str, purpose: str, index: int) -> Decimal:
        return self.unit_value(event_id, purpose, index)

    def integer(self, event_id: str, purpose: str, index: int, upper_bound: int) -> int:
        if type(upper_bound) is not int or upper_bound <= 0:
            raise BacktestValidationError("random upper_bound must be positive")
        block_width = max(1, (upper_bound.bit_length() + 255) // 256)
        sample_space = 1 << (block_width * 256)
        acceptance_limit = sample_space - (sample_space % upper_bound)
        attempt = 0
        while True:
            raw = b"".join(
                self._block(event_id, purpose, index, attempt * block_width + offset)
                for offset in range(block_width)
            )
            if len(raw) != block_width * 32:
                raise BacktestValidationError("random block must contain exactly 32 bytes")
            candidate = int.from_bytes(raw, byteorder="big")
            if candidate < acceptance_limit:
                return candidate % upper_bound
            attempt += 1


class _PolicyLike(Protocol):
    policy_id: str
    policy_version: str
    implementation_fingerprint: str

    def to_intents(
        self,
        signals: tuple[Signal, ...],
        *,
        context: StrategyContext,
        event_id: str,
        random_source: RandomSource,
        manifest_digest: str,
        domain: str,
    ) -> tuple[BacktestOrderIntent, ...]: ...


def _program_fingerprint(program: BacktestProgram, name: str) -> str:
    value = getattr(program, name, None)
    if callable(value):
        value = value()
    if not isinstance(value, str) or not value.strip():
        raise StrategyInputError(f"program {name} must be a non-empty string")
    return value


def _canonical_result(result: object) -> StrategyResult:
    revalidated = revalidate_strategy_result(result, "strategy runner result")
    signal_ids = tuple(signal.signal_id for signal in revalidated.signals)
    if len(signal_ids) != len(set(signal_ids)):
        raise StrategyInputError("strategy result signal_id values must be unique")
    return replace(
        revalidated,
        signals=tuple(sorted(revalidated.signals, key=lambda signal: signal.signal_id)),
        diagnostics=revalidated.diagnostics,
    )


def _call_policy(
    policy: _PolicyLike,
    signals: tuple[Signal, ...],
    *,
    context: StrategyContext,
    event_id: str,
    random_source: RandomSource,
    manifest_digest: str,
    domain: str,
) -> tuple[BacktestOrderIntent, ...]:
    if type(signals) is not tuple:
        raise StrategyInputError("policy signals must be an exact tuple")
    revalidate_strategy_context(context, "policy context")
    if domain != random_source.domain_name:
        raise StrategyInputError("policy domain must match random source domain")
    raw_intents: object = policy.to_intents(
        signals,
        context=context,
        event_id=event_id,
        random_source=random_source,
        manifest_digest=manifest_digest,
        domain=domain,
    )
    if type(raw_intents) is not tuple:
        raise StrategyInputError("policy must return an exact tuple of intents")
    for index, intent in enumerate(cast(tuple[object, ...], raw_intents)):
        revalidate_backtest_order_intent(intent, f"policy intents[{index}]")
    return raw_intents


def _canonical_intents(
    intents: tuple[BacktestOrderIntent, ...],
    signals: tuple[Signal, ...],
    event: ScheduledDecisionEvent,
    manifest: BacktestRunManifest,
    policy: _PolicyLike,
    seen_intent_ids: list[str],
) -> tuple[BacktestOrderIntent, ...]:
    ordered_signals = {signal.signal_id: signal for signal in signals}
    expected_policy_fingerprint = policy.implementation_fingerprint
    for index, raw_intent in enumerate(intents):
        intent = revalidate_backtest_order_intent(raw_intent, f"policy intents[{index}]")
        signal = ordered_signals.get(intent.source_signal_id)
        if signal is None:
            raise StrategyInputError("intent source Signal is not present in the decision result")
        if intent.entity_id != signal.entity_id:
            raise StrategyInputError("intent entity must match source Signal")
        if intent.logical_time != signal.decision_time or intent.logical_time != event.logical_time:
            raise StrategyInputError("intent logical time must match source Signal")
        if intent.manifest_digest != manifest.manifest_digest:
            raise StrategyInputError("intent manifest digest must match manifest")
        if intent.policy_id != policy.policy_id or intent.policy_version != policy.policy_version:
            raise StrategyInputError("intent policy/version must match policy")
        if intent.policy_fingerprint != expected_policy_fingerprint:
            raise StrategyInputError("intent policy fingerprint must match policy")
        if intent.intent_id in seen_intent_ids:
            raise StrategyInputError("intent_id values must be globally unique")
        seen_intent_ids.append(intent.intent_id)
    ordered = tuple(sorted(intents, key=lambda intent: (intent.source_signal_id, intent.intent_id)))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if (previous.source_signal_id, previous.intent_id) == (
            current.source_signal_id,
            current.intent_id,
        ):
            raise StrategyInputError("intent ordering key must be unique")
    return ordered


class BacktestEngine:
    """Run conforming trusted programs with isolated per-run engine state.

    Program fingerprints are provenance declarations supplied by trusted
    orchestration; this engine does not prove Python artifact identity or
    freshness. A factory must return run-local strategy and policy objects.
    """

    def run(self, manifest: BacktestRunManifest, program: BacktestProgram) -> BacktestRunResult:
        manifest_value = cast(object, manifest)
        if not isinstance(manifest_value, BacktestRunManifest):
            raise StrategyInputError("manifest must be a BacktestRunManifest")
        manifest = manifest_value
        manifest.validate_integrity()

        runner_value = cast(object, program.create_strategy_runner())
        policy_value = cast(object, program.create_portfolio_intent_policy())
        if not isinstance(runner_value, StrategyRunner):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise StrategyInputError("program must create a StrategyRunner")
        if not isinstance(policy_value, PortfolioIntentPolicy):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise StrategyInputError("program must create a PortfolioIntentPolicy")
        runner = runner_value
        policy = policy_value
        if runner.descriptor != manifest.strategy_descriptor:
            raise StrategyInputError("runner descriptor does not match manifest descriptor")
        if runner.parameters != manifest.strategy_parameters:
            raise StrategyInputError("runner parameters do not match manifest parameters")
        if _program_fingerprint(program, "strategy_implementation_fingerprint") != (
            manifest.strategy_implementation_fingerprint
        ):
            raise StrategyInputError("strategy implementation fingerprint does not match manifest")
        if _program_fingerprint(program, "policy_implementation_fingerprint") != (
            manifest.policy_implementation_fingerprint
        ):
            raise StrategyInputError("policy implementation fingerprint does not match manifest")
        if (
            policy.policy_id != manifest.policy_id
            or policy.policy_version != manifest.policy_version
        ):
            raise StrategyInputError("policy identity does not match manifest policy identity")
        if policy.implementation_fingerprint != manifest.policy_implementation_fingerprint:
            raise StrategyInputError("policy implementation fingerprint does not match manifest")

        queue = DeterministicEventQueue(manifest.events)
        clock = SimulationClock(manifest.start_time)
        decision_random_source = DeterministicRandom(
            manifest.manifest_digest,
            manifest.rng_seed,
            domain="decision",
            algorithm=manifest.rng_algorithm,
        )
        finalize_random_source = DeterministicRandom(
            manifest.manifest_digest,
            manifest.rng_seed,
            domain="finalize",
            algorithm=manifest.rng_algorithm,
        )
        seen_intent_ids: list[str] = []

        first_event = queue.pop_next()
        clock.advance(first_event.logical_time)
        state = revalidate_strategy_state(
            runner.initialize(first_event.context), "initialize state"
        )
        if state.state_version != manifest.strategy_descriptor.lifecycle_version:
            raise StrategyInputError("initialize state_version must match strategy lifecycle")
        trace_values: list[BacktestDecisionTrace] = []
        current_event = first_event
        while True:
            clock.advance(current_event.logical_time)
            state_before = state
            result = _canonical_result(runner.on_decision(current_event.context, state_before))
            validate_strategy_result_binding(
                manifest.strategy_descriptor,
                current_event.context,
                result,
                f"decision result {current_event.event_id}",
            )
            intents = _canonical_intents(
                _call_policy(
                    policy,
                    result.signals,
                    context=current_event.context,
                    event_id=current_event.event_id,
                    random_source=decision_random_source,
                    manifest_digest=manifest.manifest_digest,
                    domain="decision",
                ),
                result.signals,
                current_event,
                manifest,
                policy,
                seen_intent_ids,
            )
            state = result.next_state
            if state.state_version != manifest.strategy_descriptor.lifecycle_version:
                raise StrategyInputError("decision state_version must match strategy lifecycle")
            trace_values.append(
                BacktestDecisionTrace(
                    event_id=current_event.event_id,
                    logical_time=current_event.logical_time,
                    context=current_event.context,
                    signals=result.signals,
                    intents=intents,
                    state_before=state_before,
                    state_after=state,
                    diagnostics=result.diagnostics,
                )
            )
            if not queue.has_next:
                break
            current_event = queue.pop_next()

        finalize_result = _canonical_result(runner.finalize(current_event.context, state))
        validate_strategy_result_binding(
            manifest.strategy_descriptor,
            current_event.context,
            finalize_result,
            "finalize result",
        )
        finalize_intents = _canonical_intents(
            _call_policy(
                policy,
                finalize_result.signals,
                context=current_event.context,
                event_id=current_event.event_id,
                random_source=finalize_random_source,
                manifest_digest=manifest.manifest_digest,
                domain="finalize",
            ),
            finalize_result.signals,
            current_event,
            manifest,
            policy,
            seen_intent_ids,
        )
        final_state = revalidate_strategy_state(finalize_result.next_state, "finalize state")
        if final_state.state_version != manifest.strategy_descriptor.lifecycle_version:
            raise StrategyInputError("finalize state_version must match strategy lifecycle")
        trace = tuple(trace_values)
        result_digest = canonical_digest(
            {
                "manifest": manifest,
                "trace": trace,
                "finalize_result": finalize_result,
                "finalize_intents": finalize_intents,
                "final_state": final_state,
            }
        )
        return BacktestRunResult(
            manifest=manifest,
            trace=trace,
            finalize_result=finalize_result,
            finalize_intents=finalize_intents,
            final_state=final_state,
            result_digest=result_digest,
        )


EventDrivenBacktestEngine = BacktestEngine


__all__ = [
    "BacktestEngine",
    "DeterministicEventQueue",
    "DeterministicRandom",
    "EventDrivenBacktestEngine",
    "SimulationClock",
]
