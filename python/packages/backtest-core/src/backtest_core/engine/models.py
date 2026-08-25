from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from quant_core.strategy import (
    FeatureValue,
    Signal,
    StrategyContext,
    StrategyDescriptor,
    StrategyInputError,
    StrategyResult,
    StrategyState,
    UniverseSnapshot,
    validate_strategy_result,
)

if TYPE_CHECKING:
    from .manifest import BacktestRunManifest


class BacktestValidationError(StrategyInputError):
    """Raised when a deterministic backtest boundary is invalid."""


DECISION_PHASE = 0
_LOWER_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_T = TypeVar("_T")


def require_non_empty(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BacktestValidationError(f"{field_name} must be a non-empty string")
    return value


def require_aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BacktestValidationError(f"{field_name} must be timezone-aware")
    return value


def require_hex_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _LOWER_HEX_DIGEST.fullmatch(value) is None:
        raise BacktestValidationError(f"{field_name} must be a 64-character lowercase hex digest")
    return value


def _revalidate_dataclass(
    value: object,
    expected_type: type[_T],
    post_init: Callable[[_T], None],
    field_name: str,
) -> _T:
    if not isinstance(value, expected_type):
        raise BacktestValidationError(f"{field_name} must be a {expected_type.__name__}")
    typed_value = value
    try:
        post_init(typed_value)
    except BacktestValidationError:
        raise
    except (AttributeError, TypeError) as error:
        raise BacktestValidationError(f"{field_name} contains a forged value") from error
    except StrategyInputError as error:
        raise BacktestValidationError(f"{field_name} is invalid: {error}") from error
    return typed_value


def revalidate_strategy_context(value: object, field_name: str = "context") -> StrategyContext:
    context = _revalidate_dataclass(
        value, StrategyContext, StrategyContext.__post_init__, field_name
    )
    _revalidate_dataclass(
        context.universe,
        UniverseSnapshot,
        UniverseSnapshot.__post_init__,
        f"{field_name}.universe",
    )
    for index, feature in enumerate(context.features):
        _revalidate_dataclass(
            feature,
            FeatureValue,
            FeatureValue.__post_init__,
            f"{field_name}.features[{index}]",
        )
    return context


def revalidate_signal(value: object, field_name: str = "signal") -> Signal:
    signal = _revalidate_dataclass(value, Signal, Signal.__post_init__, field_name)
    if signal.is_executable is not False:
        raise BacktestValidationError(f"{field_name}.is_executable must be False")
    if signal.execution_capability != "NONE":
        raise BacktestValidationError(f"{field_name}.execution_capability must be NONE")
    return signal


def revalidate_strategy_state(value: object, field_name: str = "state") -> StrategyState:
    return _revalidate_dataclass(value, StrategyState, StrategyState.__post_init__, field_name)


def revalidate_strategy_result(
    value: object, field_name: str = "strategy_result"
) -> StrategyResult:
    result = _revalidate_dataclass(value, StrategyResult, StrategyResult.__post_init__, field_name)
    for index, signal in enumerate(result.signals):
        revalidate_signal(signal, f"{field_name}.signals[{index}]")
    revalidate_strategy_state(result.next_state, f"{field_name}.next_state")
    return result


def validate_strategy_result_binding(
    descriptor: StrategyDescriptor,
    context: StrategyContext,
    result: StrategyResult,
    field_name: str,
) -> StrategyResult:
    revalidate_strategy_context(context, f"{field_name}.context")
    revalidated = revalidate_strategy_result(result, field_name)
    try:
        canonical = validate_strategy_result(descriptor, context, revalidated)
    except (AttributeError, TypeError) as error:
        raise BacktestValidationError(f"{field_name} has forged strategy binding") from error
    except StrategyInputError as error:
        raise BacktestValidationError(
            f"{field_name} has invalid strategy binding: {error}"
        ) from error
    if canonical != revalidated:
        raise BacktestValidationError(f"{field_name} has non-canonical strategy binding")
    return revalidated


def _validate_strategy_result(value: object, field_name: str) -> StrategyResult:
    result = revalidate_strategy_result(value, field_name)
    signal_ids = tuple(signal.signal_id for signal in result.signals)
    if len(signal_ids) != len(set(signal_ids)):
        raise BacktestValidationError(f"{field_name}.signals signal_id values must be unique")
    if signal_ids != tuple(sorted(signal_ids)):
        raise BacktestValidationError(f"{field_name}.signals must be sorted by signal_id")
    return result


class IntentSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionCapability(str, Enum):
    BACKTEST_ONLY = "BACKTEST_ONLY"


@dataclass(frozen=True, slots=True)
class ScheduledDecisionEvent:
    """An immutable strategy decision input scheduled on logical time."""

    event_id: str
    source_id: str
    source_sequence: int
    logical_time: datetime
    available_time: datetime
    context: StrategyContext
    phase: int = field(default=DECISION_PHASE, init=False)

    def __post_init__(self) -> None:
        require_non_empty(self.event_id, "event_id")
        require_non_empty(self.source_id, "source_id")
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise BacktestValidationError("source_sequence must be a non-negative integer")
        if self.phase != DECISION_PHASE:
            raise BacktestValidationError("phase must be the fixed decision phase")
        logical_time = require_aware(self.logical_time, "logical_time")
        available_time = require_aware(self.available_time, "available_time")
        context = revalidate_strategy_context(self.context)
        if logical_time != context.decision_time:
            raise BacktestValidationError("logical_time must match context decision_time")
        if available_time > context.data_cutoff_time:
            raise BacktestValidationError("available_time must not exceed context data_cutoff_time")

    @property
    def strategy_context(self) -> StrategyContext:
        """Alias that makes the scheduled input boundary explicit."""

        return self.context


def revalidate_scheduled_decision_event(
    value: object, field_name: str = "event"
) -> ScheduledDecisionEvent:
    if not isinstance(value, ScheduledDecisionEvent):
        raise BacktestValidationError(f"{field_name} must be a ScheduledDecisionEvent")
    try:
        ScheduledDecisionEvent.__post_init__(value)
    except BacktestValidationError as error:
        raise BacktestValidationError(f"{field_name} is invalid: {error}") from error
    except (AttributeError, TypeError) as error:
        raise BacktestValidationError(f"{field_name} contains a forged event") from error
    return value


@dataclass(frozen=True, slots=True)
class BacktestOrderIntent:
    """A policy-created, permanently non-executable backtest intent."""

    intent_id: str
    source_signal_id: str
    entity_id: str
    logical_time: datetime
    side: IntentSide
    policy_id: str
    policy_version: str
    policy_fingerprint: str
    manifest_digest: str
    is_executable: Literal[False] = field(default=False, init=False)
    execution_capability: ExecutionCapability = field(
        default=ExecutionCapability.BACKTEST_ONLY, init=False
    )

    def __post_init__(self) -> None:
        require_non_empty(self.intent_id, "intent_id")
        require_non_empty(self.source_signal_id, "source_signal_id")
        require_non_empty(self.entity_id, "entity_id")
        require_aware(self.logical_time, "logical_time")
        if not isinstance(self.side, IntentSide):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise BacktestValidationError("side must be BUY or SELL")
        require_non_empty(self.policy_id, "policy_id")
        require_non_empty(self.policy_version, "policy_version")
        require_non_empty(self.policy_fingerprint, "policy_fingerprint")
        require_hex_digest(self.manifest_digest, "manifest_digest")
        if self.is_executable is not False:
            raise BacktestValidationError("is_executable must be False")
        if self.execution_capability is not ExecutionCapability.BACKTEST_ONLY:
            raise BacktestValidationError("execution_capability must be BACKTEST_ONLY")


def revalidate_backtest_order_intent(
    value: object, field_name: str = "intent"
) -> BacktestOrderIntent:
    if not isinstance(value, BacktestOrderIntent):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise BacktestValidationError(f"{field_name} must contain BacktestOrderIntent values")
    try:
        BacktestOrderIntent.__post_init__(value)
    except BacktestValidationError as error:
        raise BacktestValidationError(f"{field_name} contains an invalid intent") from error
    except (AttributeError, TypeError) as error:
        raise BacktestValidationError(f"{field_name} contains a forged intent") from error
    return value


_revalidate_intent = revalidate_backtest_order_intent


@dataclass(frozen=True, slots=True)
class BacktestDecisionTrace:
    """Canonical output of one decision event."""

    event_id: str
    logical_time: datetime
    context: StrategyContext
    signals: tuple[Signal, ...]
    intents: tuple[BacktestOrderIntent, ...]
    state_before: StrategyState
    state_after: StrategyState
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        require_non_empty(self.event_id, "event_id")
        require_aware(self.logical_time, "logical_time")
        context = revalidate_strategy_context(self.context, "trace context")
        if self.logical_time != context.decision_time:
            raise BacktestValidationError("trace logical_time must match context decision_time")
        if type(self.signals) is not tuple:
            raise BacktestValidationError("trace signals must be a tuple")
        if type(self.intents) is not tuple:
            raise BacktestValidationError("trace intents must be a tuple")
        if type(self.diagnostics) is not tuple:
            raise BacktestValidationError("trace diagnostics must be a tuple")
        for index, signal in enumerate(self.signals):
            revalidate_signal(signal, f"trace signals[{index}]")
            if signal.decision_time != self.logical_time:
                raise BacktestValidationError("trace signal decision_time must match trace")
        signal_ids = tuple(signal.signal_id for signal in self.signals)
        if len(signal_ids) != len(set(signal_ids)):
            raise BacktestValidationError("trace signal_id values must be unique")
        if signal_ids != tuple(sorted(signal_ids)):
            raise BacktestValidationError("trace signals must be sorted by signal_id")
        for index, intent in enumerate(self.intents):
            revalidate_backtest_order_intent(intent, f"trace intents[{index}]")
        signals_by_id = {signal.signal_id: signal for signal in self.signals}
        for intent in self.intents:
            source_signal = signals_by_id.get(intent.source_signal_id)
            if source_signal is None:
                raise BacktestValidationError(
                    "trace intent source Signal must be present in signals"
                )
            if intent.entity_id != source_signal.entity_id:
                raise BacktestValidationError("trace intent entity must match source Signal")
            if (
                intent.logical_time != source_signal.decision_time
                or intent.logical_time != self.logical_time
            ):
                raise BacktestValidationError(
                    "trace intent logical time must match trace and source Signal"
                )
        intent_ids = tuple(intent.intent_id for intent in self.intents)
        if len(intent_ids) != len(set(intent_ids)):
            raise BacktestValidationError("trace intent_id values must be unique")
        intent_keys = tuple((intent.source_signal_id, intent.intent_id) for intent in self.intents)
        if intent_keys != tuple(sorted(intent_keys)):
            raise BacktestValidationError("trace intents must be sorted")
        revalidate_strategy_state(self.state_before, "trace state_before")
        revalidate_strategy_state(self.state_after, "trace state_after")
        if any(not isinstance(cast(object, item), str) for item in self.diagnostics):
            raise BacktestValidationError("trace diagnostics must contain strings")


def revalidate_decision_trace(value: object, field_name: str = "trace") -> BacktestDecisionTrace:
    if not isinstance(value, BacktestDecisionTrace):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise BacktestValidationError(f"{field_name} must contain BacktestDecisionTrace values")
    try:
        BacktestDecisionTrace.__post_init__(value)
    except BacktestValidationError as error:
        raise BacktestValidationError(f"{field_name} contains an invalid trace") from error
    except (AttributeError, TypeError) as error:
        raise BacktestValidationError(f"{field_name} contains a forged trace") from error
    return value


_revalidate_trace = revalidate_decision_trace


@dataclass(frozen=True, slots=True)
class BacktestRunResult:
    """Deeply immutable canonical result of one complete run."""

    manifest: BacktestRunManifest
    trace: tuple[BacktestDecisionTrace, ...]
    finalize_result: StrategyResult
    finalize_intents: tuple[BacktestOrderIntent, ...]
    final_state: StrategyState
    result_digest: str

    def __post_init__(self) -> None:
        from .manifest import BacktestRunManifest, canonical_digest

        manifest_value = cast(object, self.manifest)
        if not isinstance(manifest_value, BacktestRunManifest):
            raise BacktestValidationError("manifest must be a BacktestRunManifest")
        manifest = manifest_value
        try:
            manifest.validate_integrity()
        except BacktestValidationError:
            raise
        except (AttributeError, TypeError) as error:
            raise BacktestValidationError("manifest integrity is invalid") from error

        trace_value = cast(object, self.trace)
        if type(trace_value) is not tuple:
            raise BacktestValidationError("trace must be a tuple")
        trace_values = cast(tuple[object, ...], trace_value)
        traces = tuple(
            revalidate_decision_trace(trace_value, f"trace[{index}]")
            for index, trace_value in enumerate(trace_values)
        )
        if len(traces) != len(manifest.events):
            raise BacktestValidationError("trace length must match manifest events")
        for trace, event in zip(traces, manifest.events, strict=True):
            if trace.event_id != event.event_id:
                raise BacktestValidationError("trace event_id must match manifest event")
            if trace.logical_time != event.logical_time:
                raise BacktestValidationError("trace logical_time must match manifest event")
            if trace.context != event.context:
                raise BacktestValidationError("trace context must match manifest event")
        for previous, current in zip(traces, traces[1:], strict=False):
            if previous.state_after != current.state_before:
                raise BacktestValidationError("adjacent trace states must match")

        for index, trace in enumerate(traces):
            validate_strategy_result_binding(
                manifest.strategy_descriptor,
                trace.context,
                StrategyResult(
                    signals=trace.signals,
                    next_state=trace.state_after,
                    diagnostics=trace.diagnostics,
                ),
                f"trace[{index}]",
            )
            for state_name, state in (
                ("state_before", trace.state_before),
                ("state_after", trace.state_after),
            ):
                if state.state_version != manifest.strategy_descriptor.lifecycle_version:
                    raise BacktestValidationError(
                        f"trace[{index}].{state_name} state_version must match strategy lifecycle"
                    )

        finalize_result = _validate_strategy_result(self.finalize_result, "finalize_result")
        validate_strategy_result_binding(
            manifest.strategy_descriptor,
            manifest.events[-1].context,
            finalize_result,
            "finalize_result",
        )
        final_state = revalidate_strategy_state(self.final_state, "final_state")
        if final_state.state_version != manifest.strategy_descriptor.lifecycle_version:
            raise BacktestValidationError("final_state state_version must match strategy lifecycle")
        if final_state != finalize_result.next_state:
            raise BacktestValidationError("final_state must equal finalize_result.next_state")

        finalize_intents_value = cast(object, self.finalize_intents)
        if type(finalize_intents_value) is not tuple:
            raise BacktestValidationError("finalize_intents must be a tuple")
        finalize_intent_values = cast(tuple[object, ...], finalize_intents_value)
        finalize_intents = tuple(
            revalidate_backtest_order_intent(intent_value, f"finalize_intents[{index}]")
            for index, intent_value in enumerate(finalize_intent_values)
        )
        finalize_keys = tuple(
            (intent.source_signal_id, intent.intent_id) for intent in finalize_intents
        )
        if finalize_keys != tuple(sorted(finalize_keys)):
            raise BacktestValidationError("finalize_intents must be sorted")

        expected_intent_ids: list[str] = []
        all_trace_intents = tuple(intent for trace in traces for intent in trace.intents)
        all_intents = all_trace_intents + finalize_intents
        for intent in all_intents:
            if intent.intent_id in expected_intent_ids:
                raise BacktestValidationError("intent_id values must be globally unique")
            expected_intent_ids.append(intent.intent_id)
            if intent.manifest_digest != manifest.manifest_digest:
                raise BacktestValidationError("intent manifest_digest must match manifest")
            if intent.policy_id != manifest.policy_id:
                raise BacktestValidationError("intent policy_id must match manifest")
            if intent.policy_version != manifest.policy_version:
                raise BacktestValidationError("intent policy_version must match manifest")
            if intent.policy_fingerprint != manifest.policy_implementation_fingerprint:
                raise BacktestValidationError("intent policy_fingerprint must match manifest")

        finalize_signals = {signal.signal_id: signal for signal in finalize_result.signals}
        last_event_time = manifest.events[-1].logical_time
        for intent in finalize_intents:
            source_signal = finalize_signals.get(intent.source_signal_id)
            if source_signal is None:
                raise BacktestValidationError(
                    "finalize intent source Signal must be present in finalize_result"
                )
            if intent.entity_id != source_signal.entity_id:
                raise BacktestValidationError("finalize intent entity must match source Signal")
            if (
                intent.logical_time != source_signal.decision_time
                or intent.logical_time != last_event_time
            ):
                raise BacktestValidationError(
                    "finalize intent logical time must match finalize result and last event"
                )

        require_hex_digest(self.result_digest, "result_digest")
        expected_digest = canonical_digest(
            {
                "manifest": manifest,
                "trace": traces,
                "finalize_result": finalize_result,
                "finalize_intents": finalize_intents,
                "final_state": final_state,
            }
        )
        if self.result_digest != expected_digest:
            raise BacktestValidationError("result_digest does not match canonical result")

    @property
    def digest(self) -> str:
        return self.result_digest


DecisionTrace = BacktestDecisionTrace
BacktestOrderSide = IntentSide
