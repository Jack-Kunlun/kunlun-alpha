from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable

from .models import (
    STRATEGY_SDK_VERSION,
    Signal,
    StrategyContext,
    StrategyDescriptor,
    StrategyFutureDataError,
    StrategyInputError,
    StrategyParameters,
    StrategyResult,
    StrategyState,
)


def _require_instance[T](value: object, expected_type: type[T], message: str) -> T:
    if not isinstance(value, expected_type):
        raise StrategyInputError(message)
    return value


@runtime_checkable
class Strategy(Protocol):
    """Research strategy implementation protocol with non-public lifecycle hooks."""

    descriptor: StrategyDescriptor

    def _initialize(
        self, context: StrategyContext, parameters: StrategyParameters
    ) -> StrategyState: ...

    def _on_decision(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult: ...

    def _finalize(
        self,
        context: StrategyContext,
        parameters: StrategyParameters,
        state: StrategyState,
    ) -> StrategyResult: ...


def _validate_context_requirements(
    descriptor: StrategyDescriptor, context: StrategyContext
) -> None:
    context = _require_instance(context, StrategyContext, "context must be a StrategyContext")
    available_names = {item.feature_name for item in context.features}
    missing = sorted(set(descriptor.required_features) - available_names)
    if missing:
        raise StrategyInputError(f"context is missing required feature: {missing[0]}")


def _canonical_state(descriptor: StrategyDescriptor, state: StrategyState) -> StrategyState:
    state = _require_instance(state, StrategyState, "strategy hook must return a StrategyState")
    if state.state_version != descriptor.lifecycle_version:
        raise StrategyInputError("state_version must match descriptor lifecycle_version")
    return replace(state, values=tuple(tuple(item) for item in state.values))


def _validate_signal(
    descriptor: StrategyDescriptor, context: StrategyContext, signal: Signal
) -> Signal:
    if signal.strategy_id != descriptor.strategy_id:
        raise StrategyInputError("signal strategy_id must match descriptor")
    if signal.strategy_version != descriptor.strategy_version:
        raise StrategyInputError("signal strategy_version must match descriptor")
    if signal.algorithm_version != descriptor.algorithm_version:
        raise StrategyInputError("signal algorithm_version must match descriptor")
    if signal.schema_version != descriptor.signal_schema_version:
        raise StrategyInputError("signal schema_version must match descriptor")
    if signal.decision_time != context.decision_time:
        raise StrategyFutureDataError("signal decision_time must match context")
    if signal.data_cutoff_time != context.data_cutoff_time:
        raise StrategyFutureDataError("signal data_cutoff_time must match context")
    if signal.input_snapshot_id != context.snapshot_id:
        raise StrategyInputError("signal input_snapshot_id must match context")
    if signal.input_snapshot_version != context.snapshot_version:
        raise StrategyInputError("signal input_snapshot_version must match context")
    if signal.entity_id not in context.entity_ids:
        raise StrategyInputError("signal entity is outside context universe")
    for feature_name in descriptor.required_features:
        if context.get_feature(signal.entity_id, feature_name) is None:
            raise StrategyInputError(f"signal entity is missing required feature: {feature_name}")
    return replace(signal, evidence_ids=tuple(signal.evidence_ids))


def validate_strategy_result(
    descriptor: StrategyDescriptor,
    context: StrategyContext,
    result: StrategyResult,
) -> StrategyResult:
    """Validate and canonicalize hook output before any consumer can observe it."""

    descriptor = _require_instance(
        descriptor, StrategyDescriptor, "descriptor must be a StrategyDescriptor"
    )
    _validate_context_requirements(descriptor, context)
    result = _require_instance(result, StrategyResult, "strategy hook must return a StrategyResult")

    signals = tuple(_validate_signal(descriptor, context, signal) for signal in result.signals)
    next_state = _canonical_state(descriptor, result.next_state)
    return StrategyResult(
        signals=signals,
        next_state=next_state,
        diagnostics=tuple(result.diagnostics),
    )


@dataclass(frozen=True, slots=True)
class StrategyRunner:
    """The sole supported lifecycle entry; every hook result crosses validation."""

    strategy: Strategy
    parameters: StrategyParameters
    descriptor: StrategyDescriptor = field(init=False)

    def __post_init__(self) -> None:
        strategy = _require_instance(
            self.strategy, Strategy, "strategy must implement the Strategy protocol"
        )
        descriptor = _require_instance(
            strategy.descriptor,
            StrategyDescriptor,
            "strategy descriptor must be a StrategyDescriptor",
        )
        parameters = _require_instance(
            self.parameters,
            StrategyParameters,
            "parameters must be StrategyParameters",
        )
        if parameters.descriptor_version != descriptor.strategy_version:
            raise StrategyInputError("parameter descriptor_version must match strategy_version")
        if descriptor.sdk_version != STRATEGY_SDK_VERSION:
            raise StrategyInputError("descriptor sdk_version must match the installed strategy SDK")
        object.__setattr__(self, "descriptor", descriptor)

    def initialize(self, context: StrategyContext) -> StrategyState:
        _validate_context_requirements(self.descriptor, context)
        # StrategyRunner is the sole SDK owner allowed to invoke implementation hooks.
        state = self.strategy._initialize(  # pyright: ignore[reportPrivateUsage]
            context, self.parameters
        )
        return _canonical_state(self.descriptor, state)

    def on_decision(self, context: StrategyContext, state: StrategyState) -> StrategyResult:
        _validate_context_requirements(self.descriptor, context)
        canonical_state = _canonical_state(self.descriptor, state)
        result = self.strategy._on_decision(  # pyright: ignore[reportPrivateUsage]
            context, self.parameters, canonical_state
        )
        return validate_strategy_result(self.descriptor, context, result)

    def finalize(self, context: StrategyContext, state: StrategyState) -> StrategyResult:
        _validate_context_requirements(self.descriptor, context)
        canonical_state = _canonical_state(self.descriptor, state)
        result = self.strategy._finalize(  # pyright: ignore[reportPrivateUsage]
            context, self.parameters, canonical_state
        )
        return validate_strategy_result(self.descriptor, context, result)
