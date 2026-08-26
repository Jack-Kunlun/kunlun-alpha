from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from feature_core.batch.models import (
    CalculatorIdentity,
    JsonValue,
    RegisteredFeature,
    canonical_checksum,
    canonical_decimal_string,
    freeze_json_value,
)
from feature_core.registry import AvailabilityPolicy, FeatureSpec, FeatureValueType

from .models import (
    EventTimeWindow,
    OnlineCalculationDisposition,
    OnlineCalculationResult,
    OnlineCasResult,
    OnlineCasStatus,
    OnlineConflictError,
    OnlineEventDisposition,
    OnlineEventReceipt,
    OnlineEventSource,
    OnlineFeatureEvent,
    OnlineFeatureValue,
    OnlineFreshness,
    OnlineInputLineage,
    OnlineIntegrityError,
    OnlineProcessDisposition,
    OnlineProcessResult,
    OnlineReadResult,
    OnlineRejection,
    OnlineStateEnvelope,
    OnlineStreamState,
    OnlineTerminalOutcome,
    OnlineValidationError,
    OnlineWindowPolicy,
    duration_microseconds,
)
from .ports import (
    OnlineCalculator,
    OnlineCalculatorArtifact,
    OnlineCalculatorTrust,
    OnlineContextualCalculator,
    OnlineStateIntegrity,
    OnlineStateStore,
)

_WINDOW = re.compile(
    r"^EVENT_TIME_TUMBLING:P"
    r"(?:(?P<days>[0-9]+)D)?"
    r"(?:T(?:(?P<hours>[0-9]+)H)?(?:(?P<minutes>[0-9]+)M)?"
    r"(?:(?P<seconds>[0-9]+)S)?)?$"
)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise OnlineValidationError(f"{field} must be timezone-aware")
    return value


def _window_duration(definition: str) -> timedelta:
    match = _WINDOW.fullmatch(definition)
    if match is None or not any(match.groupdict().values()):
        raise OnlineValidationError(
            "online FeatureSpec window_definition must use EVENT_TIME_TUMBLING:ISO8601"
        )
    duration = timedelta(
        days=int(match.group("days") or 0),
        hours=int(match.group("hours") or 0),
        minutes=int(match.group("minutes") or 0),
        seconds=int(match.group("seconds") or 0),
    )
    if duration <= timedelta(0):
        raise OnlineValidationError("online FeatureSpec window duration must be positive")
    return duration


def _validate_policy(feature: RegisteredFeature, policy: OnlineWindowPolicy) -> None:
    if _window_duration(feature.spec.window_definition) != policy.size:
        raise OnlineValidationError(
            "OnlineWindowPolicy size does not match FeatureSpec window_definition"
        )


def _expected_source(contract_name: str) -> OnlineEventSource:
    if contract_name.startswith("market."):
        return OnlineEventSource.MARKET
    if contract_name.startswith("domain."):
        return OnlineEventSource.DOMAIN
    raise OnlineValidationError("online source contract must use a market. or domain. namespace")


def _stream_key(
    feature: RegisteredFeature,
    entity_id: str,
    identity: CalculatorIdentity,
) -> str:
    ref = feature.snapshot_ref
    return (
        f"online:{ref.namespace_id}:{ref.head_fingerprint}:"
        f"{ref.feature_name}:{ref.feature_version}:"
        f"{identity.implementation_fingerprint}:{entity_id}"
    )


def _window_for(event_time: datetime, policy: OnlineWindowPolicy) -> EventTimeWindow:
    utc_time = event_time.astimezone(UTC)
    size_microseconds = duration_microseconds(policy.size)
    epoch_microseconds = int(utc_time.timestamp() * 1_000_000)
    start_microseconds = epoch_microseconds - (epoch_microseconds % size_microseconds)
    start = datetime.fromtimestamp(start_microseconds / 1_000_000, tz=UTC)
    return EventTimeWindow(start=start, end=start + policy.size)


def _calculator_artifact(
    feature: RegisteredFeature,
    trust: OnlineCalculatorTrust,
) -> OnlineCalculatorArtifact:
    artifact = trust.resolve(feature.snapshot_ref)
    if type(artifact) is not OnlineCalculatorArtifact:
        raise OnlineValidationError("no trusted calculator artifact exists for this FeatureSpec")
    if type(artifact.identity) is not CalculatorIdentity:
        raise OnlineValidationError("trusted calculator identity type is invalid")
    if artifact.identity.algorithm_version != feature.spec.algorithm_version:
        raise OnlineValidationError("calculator algorithm_version does not match FeatureSpec")
    if not callable(artifact.calculator):
        raise OnlineValidationError("trusted calculator artifact is not callable")
    return artifact


def _normalize_value(spec: FeatureSpec, value: object) -> JsonValue | None:
    if value is None:
        return None
    kind = spec.value_type.name
    if kind == FeatureValueType.DECIMAL.name:
        if type(value) is float:
            raise OnlineValidationError("float values are not valid DECIMAL feature values")
        try:
            return canonical_decimal_string(value)
        except ValueError as error:
            raise OnlineValidationError(str(error)) from error
    if kind in {"INTEGER", "INT"}:
        if type(value) is not int:
            raise OnlineValidationError("INTEGER feature value must be an integer")
        return value
    if kind in {"BOOLEAN", "BOOL"}:
        if type(value) is not bool:
            raise OnlineValidationError("BOOLEAN feature value must be a boolean")
        return value
    if kind in {"STRING", "TEXT"}:
        if type(value) is not str:
            raise OnlineValidationError("STRING feature value must be a string")
        return value
    try:
        return freeze_json_value(value)
    except ValueError as error:
        raise OnlineValidationError(str(error)) from error


def _calculate(
    *,
    calculator: OnlineCalculator,
    contextual_calculator: OnlineContextualCalculator | None,
    identity: CalculatorIdentity,
    spec: FeatureSpec,
    window: EventTimeWindow,
    events: tuple[OnlineFeatureEvent, ...],
    processing_time: datetime,
) -> OnlineCalculationResult:
    if identity.algorithm_version != spec.algorithm_version:
        raise OnlineValidationError("calculator identity changed during processing")

    def calculate_once() -> object:
        if contextual_calculator is not None:
            return contextual_calculator(spec, window, events, processing_time)
        return calculator(spec, window, events)

    def normalize(result: object) -> OnlineCalculationResult:
        if type(result) is not OnlineCalculationResult:
            result = (
                OnlineCalculationResult.pending()
                if result is None
                else OnlineCalculationResult.materialized(result)
            )
        if result.disposition is not OnlineCalculationDisposition.MATERIALIZED:
            return result
        normalized_value = _normalize_value(spec, result.value)
        if normalized_value is None:
            raise OnlineValidationError("materialized online calculation normalized to no value")
        return OnlineCalculationResult.materialized(normalized_value)

    def checksum(result: OnlineCalculationResult) -> str:
        return canonical_checksum(
            {
                "disposition": result.disposition.value,
                "value": result.value,
                "status": result.status,
                "reason": result.reason,
            }
        )

    first = normalize(calculate_once())
    second = normalize(calculate_once())
    if checksum(first) != checksum(second):
        raise OnlineIntegrityError(
            "online calculator is non-deterministic for identical window input"
        )
    return first


def _verify_envelope(
    envelope: object,
    *,
    integrity: OnlineStateIntegrity,
) -> OnlineStateEnvelope:
    if type(envelope) is not OnlineStateEnvelope:
        raise OnlineIntegrityError("online store returned an invalid state envelope")
    if not integrity.verify(envelope):
        raise OnlineIntegrityError("online state envelope integrity verification failed")
    return envelope


def _expected_available_time(
    spec: FeatureSpec,
    lineage: tuple[OnlineInputLineage, ...],
    *,
    computed_at: datetime,
) -> datetime:
    if spec.availability_policy is AvailabilityPolicy.MATERIALIZATION_TIME:
        return computed_at
    if spec.availability_policy is AvailabilityPolicy.SOURCE_AVAILABLE_TIME:
        if len(lineage) != 1:
            raise OnlineIntegrityError("SOURCE_AVAILABLE_TIME requires exactly one window input")
        return lineage[0].available_time
    return max(item.available_time for item in lineage)


def _validate_state(
    state: object,
    *,
    stream_key: str,
    feature: RegisteredFeature,
    artifact: OnlineCalculatorArtifact,
    entity_id: str,
    policy: OnlineWindowPolicy,
) -> OnlineStreamState:
    if type(state) is not OnlineStreamState:
        raise OnlineIntegrityError("online envelope contains an invalid state")
    identity = artifact.identity
    if (
        state.stream_key != stream_key
        or state.registry_ref != feature.snapshot_ref
        or state.calculator_identity != identity
        or state.entity_id != entity_id
        or state.policy_checksum != policy.identity_checksum
    ):
        raise OnlineIntegrityError("online state context does not match the request")
    if state.max_event_time is None:
        if state.watermark is not None or state.watermark_anchor is not None:
            raise OnlineIntegrityError("empty watermark state has an anchor")
    else:
        if (
            state.watermark != state.max_event_time - policy.allowed_lateness
            or type(state.watermark_anchor) is not OnlineFeatureEvent
            or state.watermark_anchor.event_time != state.max_event_time
        ):
            raise OnlineIntegrityError("online state watermark anchor is inconsistent")

    evidence_by_id: dict[str, OnlineFeatureEvent] = {}
    for event in state.accepted_evidence:
        if type(event) is not OnlineFeatureEvent or event.event_id in evidence_by_id:
            raise OnlineIntegrityError(
                "online state contains duplicate or invalid accepted evidence"
            )
        evidence_by_id[event.event_id] = event

    event_by_id: dict[str, OnlineFeatureEvent] = {}
    for event in state.events:
        if type(event) is not OnlineFeatureEvent or event.event_id in event_by_id:
            raise OnlineIntegrityError("online state contains duplicate or invalid events")
        if evidence_by_id.get(event.event_id) != event:
            raise OnlineIntegrityError("active event does not match accepted evidence")
        event_by_id[event.event_id] = event

    receipt_by_id: dict[str, OnlineEventReceipt] = {}
    for receipt in state.receipts:
        if type(receipt) is not OnlineEventReceipt or receipt.event_id in receipt_by_id:
            raise OnlineIntegrityError("online state contains duplicate or invalid receipts")
        receipt_by_id[receipt.event_id] = receipt

    rejection_by_id: dict[str, OnlineRejection] = {}
    for rejection in state.rejections:
        if type(rejection) is not OnlineRejection or rejection.event_id in rejection_by_id:
            raise OnlineIntegrityError("online state contains duplicate or invalid rejections")
        rejection_by_id[rejection.event_id] = rejection

    terminal_by_event_id: dict[str, OnlineTerminalOutcome] = {}
    for outcome in state.terminal_outcomes:
        if type(outcome) is not OnlineTerminalOutcome or outcome.event_id in terminal_by_event_id:
            raise OnlineIntegrityError("online state contains duplicate or invalid terminals")
        terminal_by_event_id[outcome.event_id] = outcome
        receipt = receipt_by_id.get(outcome.event_id)
        trigger = evidence_by_id.get(outcome.event_id)
        if (
            receipt is None
            or receipt.disposition is not OnlineEventDisposition.ACCEPTED
            or receipt.retain_until < outcome.retain_until
            or receipt.processing_time != outcome.computed_at
            or receipt.state_revision != outcome.state_revision
            or trigger is None
            or rejection_by_id.get(outcome.event_id) is not None
        ):
            raise OnlineIntegrityError("terminal outcome lacks matching accepted evidence")
        if outcome.window != _window_for(trigger.event_time, policy):
            raise OnlineIntegrityError("terminal outcome window is not canonical")
        if outcome.retain_until != outcome.computed_at + policy.replay_horizon:
            raise OnlineIntegrityError("terminal outcome retain_until is inconsistent")
        if outcome.input_checksum != canonical_checksum(outcome.input_lineage):
            raise OnlineIntegrityError("terminal outcome input lineage checksum is invalid")
        terminal_inputs: list[OnlineFeatureEvent] = []
        for lineage in outcome.input_lineage:
            input_event = evidence_by_id.get(lineage.event_id)
            if input_event is None or OnlineInputLineage.from_event(input_event) != lineage:
                raise OnlineIntegrityError(
                    "terminal outcome lineage lacks matching accepted evidence"
                )
            if not outcome.window.start <= input_event.event_time < outcome.window.end:
                raise OnlineIntegrityError("terminal outcome lineage is outside its window")
            if input_event.available_time > outcome.computed_at:
                raise OnlineIntegrityError("terminal outcome used unavailable evidence")
            if input_event.ingest_time > outcome.computed_at:
                raise OnlineIntegrityError("terminal outcome used evidence before ingest_time")
            terminal_inputs.append(input_event)
        transition_inputs: list[OnlineFeatureEvent] = []
        for accepted in state.accepted_evidence:
            accepted_receipt = receipt_by_id.get(accepted.event_id)
            if accepted_receipt is None or accepted_receipt.state_revision is None:
                raise OnlineIntegrityError("accepted evidence lacks transition provenance")
            if (
                accepted_receipt.state_revision <= outcome.state_revision
                and outcome.window.start <= accepted.event_time < outcome.window.end
            ):
                transition_inputs.append(accepted)
        expected_lineage = tuple(
            OnlineInputLineage.from_event(item)
            for item in sorted(
                transition_inputs,
                key=lambda item: (item.event_time, item.available_time, item.event_id),
            )
        )
        if outcome.input_lineage != expected_lineage:
            raise OnlineIntegrityError("terminal outcome lineage is not transition-complete")
        expected_terminal = _calculate(
            calculator=artifact.calculator,
            contextual_calculator=artifact.contextual_calculator,
            identity=identity,
            spec=feature.spec,
            window=outcome.window,
            events=tuple(
                sorted(
                    terminal_inputs,
                    key=lambda item: (item.event_time, item.available_time, item.event_id),
                )
            ),
            processing_time=outcome.computed_at,
        )
        if (
            expected_terminal.disposition is not OnlineCalculationDisposition.TERMINAL
            or expected_terminal.status != outcome.status
            or expected_terminal.reason != outcome.reason
        ):
            raise OnlineIntegrityError("terminal outcome differs from trusted calculator output")
        if (
            state.last_processing_time is None
            or outcome.computed_at > state.last_processing_time
            or outcome.state_revision > state.revision
        ):
            raise OnlineIntegrityError("terminal outcome exceeds stream state")

    windows: set[tuple[datetime, datetime]] = set()
    for value in state.values:
        if type(value) is not OnlineFeatureValue:
            raise OnlineIntegrityError("online state contains an invalid value")
        window_identity = (value.window.start, value.window.end)
        if window_identity in windows:
            raise OnlineIntegrityError("online state contains duplicate window values")
        windows.add(window_identity)
        if (
            value.registry_ref != feature.snapshot_ref
            or value.calculator_identity != identity
            or value.entity_id != entity_id
            or value.policy_checksum != policy.identity_checksum
            or value.window.end - value.window.start != policy.size
        ):
            raise OnlineIntegrityError("online value context is inconsistent")
        if value.input_checksum != canonical_checksum(value.input_lineage):
            raise OnlineIntegrityError("online value input lineage checksum is invalid")
        input_events: list[OnlineFeatureEvent] = []
        for lineage in value.input_lineage:
            event = evidence_by_id.get(lineage.event_id)
            if event is None or OnlineInputLineage.from_event(event) != lineage:
                raise OnlineIntegrityError("online value lineage lacks matching accepted evidence")
            if not value.window.start <= event.event_time < value.window.end:
                raise OnlineIntegrityError("online value lineage is outside its window")
            input_events.append(event)
        ordered_inputs = tuple(
            sorted(
                input_events,
                key=lambda item: (item.event_time, item.available_time, item.event_id),
            ),
        )
        expected_result = _calculate(
            calculator=artifact.calculator,
            contextual_calculator=artifact.contextual_calculator,
            identity=identity,
            spec=feature.spec,
            window=value.window,
            events=ordered_inputs,
            processing_time=value.computed_at,
        )
        if (
            expected_result.disposition is not OnlineCalculationDisposition.MATERIALIZED
            or expected_result.value != value.value
        ):
            raise OnlineIntegrityError("online value differs from trusted calculator output")
        expected_available = _expected_available_time(
            feature.spec,
            value.input_lineage,
            computed_at=value.computed_at,
        )
        if (
            value.available_time != expected_available
            or value.stale_at != expected_available + policy.stale_after
            or value.expires_at != expected_available + policy.ttl
        ):
            raise OnlineIntegrityError("online value availability or TTL is inconsistent")
        if state.last_processing_time is None or value.computed_at > state.last_processing_time:
            raise OnlineIntegrityError("online value processing time exceeds stream state")

    for event_id, receipt in receipt_by_id.items():
        evidence = evidence_by_id.get(event_id)
        rejection = rejection_by_id.get(event_id)
        if receipt.disposition is OnlineEventDisposition.ACCEPTED:
            if (
                evidence is None
                or evidence.content_checksum != receipt.content_checksum
                or rejection is not None
            ):
                raise OnlineIntegrityError("accepted receipt lacks matching accepted evidence")
        elif (
            rejection is None
            or rejection.reason is not receipt.disposition
            or rejection.content_checksum != receipt.content_checksum
            or evidence is not None
        ):
            raise OnlineIntegrityError("rejected receipt lacks matching rejection evidence")

    receipt_revisions: set[int] = set()
    for event_id, receipt in receipt_by_id.items():
        if receipt.processing_time is None or receipt.state_revision is None:
            raise OnlineIntegrityError("receipt lacks transition provenance")
        if receipt.state_revision in receipt_revisions or receipt.state_revision > state.revision:
            raise OnlineIntegrityError("receipt state_revision is inconsistent")
        receipt_revisions.add(receipt.state_revision)
        if receipt.retain_until < receipt.processing_time + policy.replay_horizon:
            raise OnlineIntegrityError("receipt retain_until is shorter than replay horizon")
        if (
            state.last_processing_time is None
            or receipt.processing_time > state.last_processing_time
        ):
            raise OnlineIntegrityError("receipt processing_time exceeds stream state")
        evidence = evidence_by_id.get(event_id)
        rejection = rejection_by_id.get(event_id)
        if evidence is not None and (
            evidence.available_time > receipt.processing_time
            or evidence.ingest_time > receipt.processing_time
        ):
            raise OnlineIntegrityError("accepted evidence predates receipt processing_time")
        if rejection is not None and rejection.processing_time != receipt.processing_time:
            raise OnlineIntegrityError("rejection and receipt processing_time differ")

    if set(evidence_by_id) != {
        receipt.event_id
        for receipt in state.receipts
        if receipt.disposition is OnlineEventDisposition.ACCEPTED
    }:
        raise OnlineIntegrityError("accepted evidence and receipts are not bidirectional")
    if set(rejection_by_id) != {
        receipt.event_id
        for receipt in state.receipts
        if receipt.disposition is not OnlineEventDisposition.ACCEPTED
    }:
        raise OnlineIntegrityError("rejections and receipts are not bidirectional")

    if state.last_processing_time is not None:
        if any(
            event.available_time > state.last_processing_time for event in state.accepted_evidence
        ):
            raise OnlineIntegrityError("accepted evidence was unavailable at last_processing_time")
        if any(
            rejection.processing_time > state.last_processing_time for rejection in state.rejections
        ):
            raise OnlineIntegrityError("rejection processing time exceeds stream state")
    return state


def _latest_value(
    state: OnlineStreamState,
    *,
    as_of: datetime,
) -> OnlineFeatureValue | None:
    visible = [
        value
        for value in state.values
        if value.available_time <= as_of and value.computed_at <= as_of
    ]
    if not visible:
        return None
    return max(visible, key=lambda value: (value.window.end, value.state_revision))


def _terminal_outcome_for_event(
    state: OnlineStreamState,
    event_id: str,
) -> OnlineTerminalOutcome | None:
    return next(
        (outcome for outcome in state.terminal_outcomes if outcome.event_id == event_id),
        None,
    )


def _prune_state(
    state: OnlineStreamState,
    *,
    processing_time: datetime,
) -> OnlineStreamState:
    receipts = tuple(
        receipt for receipt in state.receipts if receipt.retain_until > processing_time
    )
    retained_ids = {receipt.event_id for receipt in receipts}
    accepted_ids = {
        receipt.event_id
        for receipt in receipts
        if receipt.disposition is OnlineEventDisposition.ACCEPTED
    }
    return replace(
        state,
        events=tuple(event for event in state.events if event.event_id in retained_ids),
        accepted_evidence=tuple(
            event for event in state.accepted_evidence if event.event_id in accepted_ids
        ),
        receipts=receipts,
        values=tuple(value for value in state.values if value.expires_at > processing_time),
        rejections=tuple(
            rejection for rejection in state.rejections if rejection.event_id in retained_ids
        ),
        terminal_outcomes=tuple(
            outcome
            for outcome in state.terminal_outcomes
            if outcome.event_id in retained_ids and outcome.retain_until > processing_time
        ),
    )


def _rejection_transition(
    *,
    state: OnlineStreamState,
    event: OnlineFeatureEvent,
    reason: OnlineEventDisposition,
    policy: OnlineWindowPolicy,
    processing_time: datetime,
) -> tuple[OnlineStreamState, OnlineRejection]:
    rejection = OnlineRejection(
        event_id=event.event_id,
        content_checksum=event.content_checksum,
        reason=reason,
        event_time=event.event_time,
        observed_watermark=state.watermark,
        processing_time=processing_time,
    )
    candidate = replace(
        state,
        revision=state.revision + 1,
        last_processing_time=processing_time,
        receipts=(
            *state.receipts,
            OnlineEventReceipt(
                event_id=event.event_id,
                content_checksum=event.content_checksum,
                disposition=reason,
                retain_until=processing_time + policy.replay_horizon,
                processing_time=processing_time,
                state_revision=state.revision + 1,
            ),
        ),
        rejections=(*state.rejections, rejection),
    )
    return candidate, rejection


def _accepted_transition(
    *,
    state: OnlineStreamState,
    feature: RegisteredFeature,
    event: OnlineFeatureEvent,
    artifact: OnlineCalculatorArtifact,
    policy: OnlineWindowPolicy,
    processing_time: datetime,
) -> tuple[OnlineStreamState, OnlineFeatureValue | None, OnlineCalculationResult]:
    all_events = tuple(
        sorted(
            (*state.events, event),
            key=lambda item: (item.event_time, item.available_time, item.event_id),
        ),
    )
    window = _window_for(event.event_time, policy)
    window_events = tuple(
        item for item in all_events if window.start <= item.event_time < window.end
    )
    if any(item.available_time > processing_time for item in window_events):
        raise OnlineIntegrityError(
            "window recomputation would use input unavailable at processing_time"
        )
    calculation = _calculate(
        calculator=artifact.calculator,
        contextual_calculator=artifact.contextual_calculator,
        identity=artifact.identity,
        spec=feature.spec,
        window=window,
        events=window_events,
        processing_time=processing_time,
    )
    next_revision = state.revision + 1
    lineage = tuple(OnlineInputLineage.from_event(item) for item in window_events)
    online_value: OnlineFeatureValue | None = None
    terminal_outcome: OnlineTerminalOutcome | None = None
    if calculation.disposition is OnlineCalculationDisposition.MATERIALIZED:
        calculated_value = cast(JsonValue, calculation.value)
        available_time = _expected_available_time(
            feature.spec,
            lineage,
            computed_at=processing_time,
        )
        online_value = OnlineFeatureValue(
            registry_ref=feature.snapshot_ref,
            entity_id=event.entity_id,
            window=window,
            value=calculated_value,
            input_lineage=lineage,
            input_checksum=canonical_checksum(lineage),
            calculator_identity=artifact.identity,
            policy_checksum=policy.identity_checksum,
            available_time=available_time,
            computed_at=processing_time,
            stale_at=available_time + policy.stale_after,
            expires_at=available_time + policy.ttl,
            state_revision=next_revision,
        )
    elif calculation.disposition is OnlineCalculationDisposition.TERMINAL:
        if calculation.status is None or calculation.reason is None:
            raise OnlineIntegrityError("terminal calculation lacks status or reason")
        terminal_outcome = OnlineTerminalOutcome(
            event_id=event.event_id,
            window=window,
            status=calculation.status,
            reason=calculation.reason,
            input_lineage=lineage,
            input_checksum=canonical_checksum(lineage),
            computed_at=processing_time,
            retain_until=processing_time + policy.replay_horizon,
            state_revision=next_revision,
        )
    max_event_time = (
        event.event_time
        if state.max_event_time is None
        else max(state.max_event_time, event.event_time)
    )
    watermark_anchor = (
        event
        if state.watermark_anchor is None or event.event_time > state.watermark_anchor.event_time
        else state.watermark_anchor
    )
    watermark = max_event_time - policy.allowed_lateness
    retained_events = tuple(
        item for item in all_events if _window_for(item.event_time, policy).end > watermark
    )
    retained_values = (
        tuple(existing for existing in state.values if existing.window != window)
        if (
            online_value is not None
            or calculation.disposition is OnlineCalculationDisposition.TERMINAL
        )
        else state.values
    )
    retained_receipts = state.receipts
    if terminal_outcome is not None:
        terminal_event_ids = {item.event_id for item in terminal_outcome.input_lineage}
        retained_receipts = tuple(
            replace(
                receipt,
                retain_until=max(receipt.retain_until, terminal_outcome.retain_until),
            )
            if receipt.event_id in terminal_event_ids
            else receipt
            for receipt in state.receipts
        )
    candidate = replace(
        state,
        revision=next_revision,
        last_processing_time=processing_time,
        max_event_time=max_event_time,
        watermark=watermark,
        watermark_anchor=watermark_anchor,
        events=retained_events,
        accepted_evidence=(*state.accepted_evidence, event),
        receipts=(
            *retained_receipts,
            OnlineEventReceipt(
                event_id=event.event_id,
                content_checksum=event.content_checksum,
                disposition=OnlineEventDisposition.ACCEPTED,
                retain_until=processing_time + policy.replay_horizon,
                processing_time=processing_time,
                state_revision=next_revision,
            ),
        ),
        values=(
            tuple(
                sorted(
                    (*retained_values, online_value),
                    key=lambda item: (item.window.start, item.state_revision),
                ),
            )
            if online_value is not None
            else retained_values
        ),
        terminal_outcomes=(
            (*state.terminal_outcomes, terminal_outcome)
            if terminal_outcome is not None
            else state.terminal_outcomes
        ),
    )
    return candidate, online_value, calculation


def _retain_until(state: OnlineStreamState) -> datetime:
    deadlines = [
        *[receipt.retain_until for receipt in state.receipts],
        *[value.expires_at for value in state.values],
        *[outcome.retain_until for outcome in state.terminal_outcomes],
    ]
    if not deadlines:
        raise OnlineIntegrityError("online state has no retention evidence")
    return max(deadlines)


def _require_cas_result(value: object) -> OnlineCasResult:
    if type(value) is not OnlineCasResult:
        raise OnlineIntegrityError("online store returned an invalid CAS result")
    if type(value.status) is not OnlineCasStatus:
        raise OnlineIntegrityError("online store returned an invalid CAS status")
    return value


class OnlineFeatureEngine:
    def __init__(
        self,
        *,
        store: OnlineStateStore,
        integrity: OnlineStateIntegrity,
        calculator_trust: OnlineCalculatorTrust,
        policy: OnlineWindowPolicy,
        max_conflict_retries: int = 3,
    ) -> None:
        if type(max_conflict_retries) is not int or max_conflict_retries < 1:
            raise OnlineValidationError("max_conflict_retries must be a positive integer")
        self._store = store
        self._integrity = integrity
        self._calculator_trust = calculator_trust
        self._policy = policy
        self._max_conflict_retries = max_conflict_retries

    def process(
        self,
        feature: object,
        event: object,
        *,
        processing_time: datetime,
    ) -> OnlineProcessResult:
        if type(feature) is not RegisteredFeature:
            raise OnlineValidationError("online execution requires a RegisteredFeature")
        if type(event) is not OnlineFeatureEvent:
            raise OnlineValidationError("online execution requires an OnlineFeatureEvent")
        _aware(processing_time, "processing_time")
        _validate_policy(feature, self._policy)
        if event.available_time > processing_time or event.ingest_time > processing_time:
            raise OnlineValidationError("event is not available and ingested at processing_time")
        allowed_contracts = {
            (contract.name, contract.version) for contract in feature.spec.source_contracts
        }
        if (event.contract_name, event.contract_version) not in allowed_contracts:
            raise OnlineValidationError("event contract is not declared by FeatureSpec")
        if event.source is not _expected_source(event.contract_name):
            raise OnlineValidationError("event source does not match contract namespace")
        artifact = _calculator_artifact(feature, self._calculator_trust)
        stream_key = _stream_key(feature, event.entity_id, artifact.identity)

        for _attempt in range(self._max_conflict_retries):
            loaded = self._store.load(stream_key)
            if loaded is None:
                state = OnlineStreamState.empty(
                    stream_key=stream_key,
                    registry_ref=feature.snapshot_ref,
                    calculator_identity=artifact.identity,
                    entity_id=event.entity_id,
                    policy_checksum=self._policy.identity_checksum,
                )
            else:
                envelope = _verify_envelope(loaded, integrity=self._integrity)
                state = _validate_state(
                    envelope.state,
                    stream_key=stream_key,
                    feature=feature,
                    artifact=artifact,
                    entity_id=event.entity_id,
                    policy=self._policy,
                )
                if (
                    state.last_processing_time is not None
                    and processing_time < state.last_processing_time
                ):
                    raise OnlineIntegrityError(
                        "processing_time cannot move backward within a stream"
                    )
            working_state = _prune_state(state, processing_time=processing_time)
            terminal_status: str | None = None
            terminal_reason: str | None = None
            existing_receipt = next(
                (
                    receipt
                    for receipt in working_state.receipts
                    if receipt.event_id == event.event_id
                ),
                None,
            )
            existing_terminal = _terminal_outcome_for_event(
                working_state,
                event.event_id,
            )
            if existing_receipt is not None:
                if existing_receipt.content_checksum != event.content_checksum:
                    raise OnlineConflictError(
                        "event_id was already committed with different content"
                    )
                if state.last_processing_time == processing_time:
                    return OnlineProcessResult(
                        disposition=OnlineProcessDisposition.DUPLICATE,
                        state=state,
                        value=_latest_value(state, as_of=processing_time),
                        rejection=next(
                            (
                                rejection
                                for rejection in state.rejections
                                if rejection.event_id == event.event_id
                            ),
                            None,
                        ),
                        terminal_status=(
                            None if existing_terminal is None else existing_terminal.status
                        ),
                        terminal_reason=(
                            None if existing_terminal is None else existing_terminal.reason
                        ),
                    )
                candidate = replace(
                    working_state,
                    revision=state.revision + 1,
                    last_processing_time=processing_time,
                )
                disposition = OnlineProcessDisposition.DUPLICATE
                value = _latest_value(working_state, as_of=processing_time)
                rejection = next(
                    (item for item in working_state.rejections if item.event_id == event.event_id),
                    None,
                )
                if existing_terminal is not None:
                    terminal_status = existing_terminal.status
                    terminal_reason = existing_terminal.reason
            elif state.watermark is not None and event.event_time < state.watermark:
                candidate, rejection = _rejection_transition(
                    state=working_state,
                    event=event,
                    reason=OnlineEventDisposition.REJECTED_LATE,
                    policy=self._policy,
                    processing_time=processing_time,
                )
                disposition = OnlineProcessDisposition.REJECTED_LATE
                value = _latest_value(candidate, as_of=processing_time)
            elif processing_time >= event.available_time + self._policy.ttl:
                candidate, rejection = _rejection_transition(
                    state=working_state,
                    event=event,
                    reason=OnlineEventDisposition.REJECTED_EXPIRED,
                    policy=self._policy,
                    processing_time=processing_time,
                )
                disposition = OnlineProcessDisposition.REJECTED_EXPIRED
                value = _latest_value(candidate, as_of=processing_time)
            else:
                candidate, value, calculation = _accepted_transition(
                    state=working_state,
                    feature=feature,
                    event=event,
                    artifact=artifact,
                    policy=self._policy,
                    processing_time=processing_time,
                )
                rejection = None
                if calculation.disposition is OnlineCalculationDisposition.MATERIALIZED:
                    disposition = OnlineProcessDisposition.COMMITTED
                elif calculation.disposition is OnlineCalculationDisposition.PENDING:
                    disposition = OnlineProcessDisposition.PENDING
                else:
                    disposition = OnlineProcessDisposition.TERMINAL
                    terminal_status = calculation.status
                    terminal_reason = calculation.reason

            _validate_state(
                candidate,
                stream_key=stream_key,
                feature=feature,
                artifact=artifact,
                entity_id=event.entity_id,
                policy=self._policy,
            )
            sealed = self._integrity.seal(
                candidate,
                retain_until=_retain_until(candidate),
            )
            expected_revision = None if state.revision == 0 else state.revision
            commit = _require_cas_result(
                self._store.compare_and_set(
                    expected_revision=expected_revision,
                    candidate=sealed,
                ),
            )
            if commit.status is OnlineCasStatus.CONFLICT:
                continue
            if commit.status not in (
                OnlineCasStatus.CREATED,
                OnlineCasStatus.UPDATED,
                OnlineCasStatus.EXISTING_SAME,
            ):
                raise OnlineIntegrityError("online store returned an unknown CAS status")
            persisted_raw = self._store.load(stream_key)
            persisted_envelope = _verify_envelope(
                persisted_raw,
                integrity=self._integrity,
            )
            persisted = _validate_state(
                persisted_envelope.state,
                stream_key=stream_key,
                feature=feature,
                artifact=artifact,
                entity_id=event.entity_id,
                policy=self._policy,
            )
            if (
                commit.persisted != persisted_envelope
                or persisted_envelope != sealed
                or persisted != candidate
            ):
                raise OnlineIntegrityError("online CAS result differs from durable state read-back")
            persisted_terminal = _terminal_outcome_for_event(persisted, event.event_id)
            if persisted_terminal is not None:
                terminal_status = persisted_terminal.status
                terminal_reason = persisted_terminal.reason
            return OnlineProcessResult(
                disposition=disposition,
                state=persisted,
                value=value,
                rejection=rejection,
                terminal_status=terminal_status,
                terminal_reason=terminal_reason,
            )

        raise OnlineConflictError("online state CAS retry limit was exhausted")

    def read(
        self,
        feature: object,
        entity_id: str,
        *,
        as_of: datetime,
    ) -> OnlineReadResult:
        if type(feature) is not RegisteredFeature:
            raise OnlineValidationError("online read requires a RegisteredFeature")
        _aware(as_of, "as_of")
        _validate_policy(feature, self._policy)
        artifact = _calculator_artifact(feature, self._calculator_trust)
        stream_key = _stream_key(feature, entity_id, artifact.identity)
        loaded = self._store.load(stream_key)
        if loaded is None:
            return OnlineReadResult(OnlineFreshness.MISSING, None)
        envelope = _verify_envelope(loaded, integrity=self._integrity)
        state = _validate_state(
            envelope.state,
            stream_key=stream_key,
            feature=feature,
            artifact=artifact,
            entity_id=entity_id,
            policy=self._policy,
        )
        value = _latest_value(state, as_of=as_of)
        if value is None:
            return OnlineReadResult(OnlineFreshness.MISSING, None)
        if as_of >= value.expires_at:
            return OnlineReadResult(OnlineFreshness.EXPIRED, None)
        if as_of >= value.stale_at:
            return OnlineReadResult(OnlineFreshness.DEGRADED_STALE, value)
        return OnlineReadResult(OnlineFreshness.FRESH, value)
