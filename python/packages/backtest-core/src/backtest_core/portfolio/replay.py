"""Trusted append-only replay ports and checkpoint verification."""

from __future__ import annotations

from typing import Protocol

from backtest_core.execution import verify_batch_match_result_against_inputs

from .models import (
    ExecutionArtifactRef,
    ExecutionReplayBundle,
    PortfolioEvent,
    PortfolioHistoryRef,
    PortfolioState,
    PortfolioValidationError,
    TrustedExecutionInputs,
    TrustedReplayError,
    event_tape_digest,
    revalidate_portfolio_event,
    revalidate_portfolio_state,
)


class TrustedPortfolioEventSource(Protocol):
    """Read-only port owned by the orchestrator's durable event-tape store."""

    def resolve_portfolio_history(
        self, history_ref: PortfolioHistoryRef
    ) -> tuple[PortfolioEvent, ...]: ...


class TrustedExecutionArtifactSource(Protocol):
    """Read-only port for the engine-owned P5-N11 execution artifact store."""

    def resolve_execution_artifact(
        self, artifact_ref: ExecutionArtifactRef
    ) -> TrustedExecutionInputs: ...


def _resolve_history(
    source: TrustedPortfolioEventSource, history_ref: PortfolioHistoryRef
) -> tuple[PortfolioEvent, ...]:
    try:
        events = source.resolve_portfolio_history(history_ref)
    except TrustedReplayError:
        raise
    except Exception as error:
        raise TrustedReplayError("trusted portfolio event source failed") from error
    if type(events) is not tuple:
        raise TrustedReplayError("trusted portfolio event source must return an exact tuple")
    typed: list[PortfolioEvent] = []
    for index, event in enumerate(events):
        try:
            typed.append(revalidate_portfolio_event(event, f"trusted_events[{index}]"))
        except Exception as error:
            raise TrustedReplayError("trusted event tape contains an invalid event") from error
    typed_tuple = tuple(typed)
    if len(typed_tuple) != history_ref.expected_event_count:
        raise TrustedReplayError("trusted event tape count does not match history ref")
    if event_tape_digest(tuple(item.event_digest for item in typed_tuple)) != (
        history_ref.expected_event_tape_digest
    ):
        raise TrustedReplayError("trusted event tape digest does not match history ref")
    return typed_tuple


def verify_execution_bundle_against_source(
    bundle: ExecutionReplayBundle,
    source: TrustedExecutionArtifactSource,
) -> TrustedExecutionInputs:
    """Resolve an artifact externally, then replay the candidate against it."""

    if type(bundle) is not ExecutionReplayBundle:
        raise TrustedReplayError("execution settlement requires an execution artifact bundle")
    bundle.validate_integrity()
    try:
        inputs = source.resolve_execution_artifact(bundle.artifact_ref)
    except TrustedReplayError:
        raise
    except Exception as error:
        raise TrustedReplayError("trusted execution artifact source failed") from error
    if type(inputs) is not TrustedExecutionInputs:
        raise TrustedReplayError("execution artifact source returned an invalid input object")
    try:
        inputs.validate_integrity()
    except Exception as error:
        raise TrustedReplayError("trusted execution inputs failed integrity validation") from error
    if inputs.artifact_id != bundle.artifact_ref.artifact_id:
        raise TrustedReplayError("execution artifact id does not match artifact ref")
    if inputs.input_digest != bundle.artifact_ref.expected_input_digest:
        raise TrustedReplayError("execution input digest does not match artifact ref")
    try:
        verify_batch_match_result_against_inputs(
            bundle.candidate,
            inputs.orders,
            inputs.snapshot,
            inputs.rules,
            inputs.sellability,
            inputs.fee_schedule,
            inputs.slippage_model,
        )
    except Exception as error:
        raise TrustedReplayError("candidate does not match trusted execution artifact") from error
    if bundle.candidate.source_dataset_digest != inputs.external_source_digest:
        raise TrustedReplayError("candidate source digest does not match trusted artifact")
    if bundle.candidate.code_config_digest != inputs.external_config_digest:
        raise TrustedReplayError("candidate config digest does not match trusted artifact")
    return inputs


def _replay_portfolio(
    events: tuple[PortfolioEvent, ...],
    *,
    initial_state: PortfolioState | None = None,
    tape_id: str | None = None,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioState:
    """Replay an externally supplied event tape without sorting or trusting a checkpoint."""

    if type(events) is not tuple:
        raise PortfolioValidationError("replay events must be an exact tuple")
    if initial_state is None:
        state = PortfolioState.empty(tape_id or "portfolio-replay")
    else:
        state = revalidate_portfolio_state(initial_state)
    from .accounting import _apply_portfolio_event_unchecked  # pyright: ignore[reportPrivateUsage]

    for index, event in enumerate(events):
        typed = revalidate_portfolio_event(event, f"events[{index}]")
        state = _apply_portfolio_event_unchecked(state, typed, execution_source=execution_source)
    return state


def verify_portfolio_state_from_source(
    state: PortfolioState,
    source: TrustedPortfolioEventSource,
    *,
    execution_source: TrustedExecutionArtifactSource | None = None,
) -> PortfolioState:
    """Rebuild a state from the externally anchored tape and compare every field."""

    expected = revalidate_portfolio_state(state)
    events = _resolve_history(source, expected.history_ref)
    replayed = _replay_portfolio(
        events,
        tape_id=expected.history_ref.tape_id,
        execution_source=execution_source,
    )
    if replayed != expected:
        raise TrustedReplayError(
            "portfolio state does not equal the full state reconstructed from trusted events"
        )
    return replayed


__all__ = [
    "TrustedExecutionArtifactSource",
    "TrustedPortfolioEventSource",
    "verify_execution_bundle_against_source",
    "verify_portfolio_state_from_source",
]
