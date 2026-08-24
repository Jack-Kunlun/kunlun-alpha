"""Pure deterministic engine for P4-N05 seat co-occurrence statistics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, localcontext
from itertools import combinations

from seat_core.cooccurrence.models import (
    COOCCURRENCE_ALGORITHM_VERSION,
    COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION,
    COOCCURRENCE_SCHEMA_VERSION,
    SEAT_EVENT_ID_ALGORITHM_VERSION,
    CIStatus,
    CooccurrenceDiagnostic,
    CooccurrenceInputError,
    CooccurrenceKey,
    CooccurrenceMetric,
    CooccurrencePolicy,
    CooccurrenceProvenance,
    CooccurrenceRecord,
    CooccurrenceResult,
    EventOutcomeProvenance,
    EventTopicMembership,
    ParentFeatureProvenance,
    SeatEventKey,
    SeatEventReference,
    SeatTradeEvidence,
)
from seat_core.features.performance import (
    DailyPriceObservation,
    PerformanceSample,
    SeatPerformanceFeature,
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def compute_seat_event_id(key: SeatEventKey) -> str:
    """Return the versioned SHA-256 ID for a SeatEventKey."""

    if type(key) is not SeatEventKey:
        raise TypeError("key must be SeatEventKey")
    payload = {
        "algorithmVersion": SEAT_EVENT_ID_ALGORITHM_VERSION,
        "instrumentId": key.instrument_id,
        "tradeDate": key.trade_date.isoformat(),
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def r7_quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    """Compute R-7 interpolation using Decimal arithmetic only."""

    if not values:
        raise ValueError("values must not be empty")
    if type(probability) is not Decimal or not probability.is_finite():
        raise TypeError("probability must be a finite Decimal")
    if not Decimal("0") <= probability <= Decimal("1"):
        raise ValueError("probability must be in [0, 1]")
    ordered = tuple(sorted(values))
    for value in ordered:
        if type(value) is not Decimal or not value.is_finite():
            raise TypeError("values must contain finite Decimal instances")
    if len(ordered) == 1:
        return ordered[0]
    with localcontext() as context:
        context.prec = 34
        context.rounding = ROUND_HALF_EVEN
        h = Decimal(len(ordered) - 1) * probability + Decimal("1")
        lower_index = int(h.to_integral_value(rounding=ROUND_FLOOR))
        if h <= Decimal("1"):
            return ordered[0]
        if h >= Decimal(len(ordered)):
            return ordered[-1]
        fraction = h - Decimal(lower_index)
        lower = ordered[lower_index - 1]
        upper = ordered[lower_index]
        return lower + fraction * (upper - lower)


quantile_r7 = r7_quantile


@dataclass(frozen=True, slots=True)
class _EventOutcome:
    key: SeatEventKey
    seat_event_id: str
    path_dates: tuple[date, ...]
    event_returns: tuple[Decimal, ...]
    bars: tuple[DailyPriceObservation, ...]
    identity: str


@dataclass(frozen=True, slots=True)
class _EventMember:
    seat_id: str
    feature: ParentFeatureProvenance
    samples: tuple[PerformanceSample, ...]


@dataclass(frozen=True, slots=True)
class _PreparedEvent:
    key: SeatEventKey
    reference: SeatEventReference
    outcome: _EventOutcome
    members: tuple[_EventMember, ...]


def _bar_payload(bar: DailyPriceObservation) -> dict[str, object]:
    return {
        "adjustment": bar.adjustment,
        "availableTime": bar.available_time.isoformat(),
        "close": _decimal_text(bar.close),
        "dataVersion": bar.data_version,
        "eventTime": bar.event_time.isoformat(),
        "instrumentId": bar.instrument_id,
        "interval": bar.interval,
        "limitState": bar.limit_state.value,
        "rawCaptureId": bar.raw_capture_id,
        "replacementVersion": bar.replacement_version,
        "revisionId": bar.revision_id,
        "schemaVersion": bar.schema_version,
        "session": bar.session,
        "source": bar.source,
        "sourceVersion": bar.source_version,
        "suspended": bar.suspended,
        "tradeDate": bar.trade_date.isoformat(),
    }


def _sample_payload(sample: PerformanceSample) -> dict[str, object]:
    return {
        "bars": [_bar_payload(bar) for bar in sample.bars],
        "eventReturns": [_decimal_text(value) for value in sample.event_returns],
        "exclusionReason": sample.exclusion_reason.value
        if sample.exclusion_reason is not None
        else None,
        "included": sample.included,
        "instrumentId": sample.instrument_id,
        "maxDrawdown": _decimal_text(sample.max_drawdown)
        if sample.max_drawdown is not None
        else None,
        "pathDates": [day.isoformat() for day in sample.path_dates],
        "tradeAvailableTime": sample.trade_available_time.isoformat(),
        "tradeDate": sample.trade_date.isoformat(),
        "tradeEvidenceId": sample.trade_evidence_id,
        "tradeId": sample.trade_id,
        "tradeLineageId": sample.trade_lineage_id,
        "tradePreviousRevisionId": sample.trade_previous_revision_id,
        "tradeRawRecordId": sample.trade_raw_record_id,
        "tradeRevisionId": sample.trade_revision_id,
        "tradeSource": sample.trade_source,
        "tradeSourceVersion": sample.trade_source_version,
    }


def _validate_sample(sample: PerformanceSample) -> _EventOutcome:
    if type(sample) is not PerformanceSample:
        raise CooccurrenceInputError("invalid_parent_sample", "parent sample has invalid type")
    try:
        if not sample.included:
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "excluded samples must not be passed to outcome validation",
            )
        if sample.exclusion_reason is not None:
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "included samples must not carry an exclusion reason",
            )
        if type(sample.max_drawdown) is not Decimal or not sample.max_drawdown.is_finite():
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "included samples must carry a finite max drawdown",
            )
        if (
            type(sample.bars) is not tuple
            or type(sample.event_returns) is not tuple
            or type(sample.path_dates) is not tuple
            or len(sample.bars) != 6
            or len(sample.event_returns) != 5
            or len(sample.path_dates) != 6
        ):
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "included sample must contain exactly six bars, five returns, and six dates",
            )
        if type(sample.trade_date) is not date or sample.path_dates[0] != sample.trade_date:
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "sample path must start on trade_date",
            )
        if any(type(day) is not date for day in sample.path_dates):
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "sample path dates must be date values",
            )
        for bar in sample.bars:
            if type(bar) is not DailyPriceObservation:
                raise CooccurrenceInputError(
                    "invalid_parent_sample",
                    "included sample bars must be DailyPriceObservation values",
                )
            if bar.instrument_id != sample.instrument_id:
                raise CooccurrenceInputError(
                    "invalid_parent_sample",
                    "every parent bar must use the sample instrument",
                )
            if type(bar.close) is not Decimal or not bar.close.is_finite() or bar.close <= 0:
                raise CooccurrenceInputError(
                    "invalid_parent_sample",
                    "parent bar close must be finite and positive",
                )
            if bar.suspended:
                raise CooccurrenceInputError(
                    "invalid_parent_sample",
                    "included parent bars must not be suspended",
                )
        if tuple(bar.trade_date for bar in sample.bars) != sample.path_dates:
            raise CooccurrenceInputError(
                "invalid_parent_sample",
                "sample path dates do not match bar dates",
            )
        for value in sample.event_returns:
            if type(value) is not Decimal or not value.is_finite():
                raise CooccurrenceInputError(
                    "invalid_parent_sample",
                    "event returns must be finite Decimal values",
                )
        with localcontext() as context:
            context.prec = 34
            context.rounding = ROUND_HALF_EVEN
            first_close = sample.bars[0].close
            for bar, actual_return in zip(sample.bars[1:], sample.event_returns, strict=True):
                expected_return = bar.close / first_close - Decimal("1")
                if expected_return != actual_return:
                    raise CooccurrenceInputError(
                        "invalid_parent_sample",
                        "event return does not match the selected bar path",
                    )
        event_key = SeatEventKey(sample.instrument_id, sample.trade_date)
        payload = {
            "eventReturns": [_decimal_text(value) for value in sample.event_returns],
            "instrumentId": sample.instrument_id,
            "pathDates": [day.isoformat() for day in sample.path_dates],
            "bars": [_bar_payload(bar) for bar in sample.bars],
            "tradeDate": sample.trade_date.isoformat(),
        }
        return _EventOutcome(
            key=event_key,
            seat_event_id="",
            path_dates=sample.path_dates,
            event_returns=sample.event_returns,
            bars=sample.bars,
            identity=_canonical_json(payload),
        )
    except CooccurrenceInputError:
        raise
    except Exception as error:
        raise CooccurrenceInputError(
            "invalid_parent_sample",
            f"malformed included parent sample: {error}",
        ) from error


def _sample_sort_key(sample: PerformanceSample) -> tuple[str, str, str, str, str]:
    return (
        sample.trade_id,
        sample.trade_lineage_id,
        sample.trade_revision_id,
        sample.trade_raw_record_id,
        sample.trade_evidence_id,
    )


def _feature_provenance(feature: SeatPerformanceFeature) -> ParentFeatureProvenance:
    return ParentFeatureProvenance(
        seat_id=feature.seat_id,
        schema_version=feature.schema_version,
        algorithm_version=feature.algorithm_version,
        policy_version=feature.policy_version,
        policy_fingerprint=feature.policy_fingerprint,
    )


def _diagnostic_sort_key(diagnostic: CooccurrenceDiagnostic) -> tuple[str, ...]:
    key = diagnostic.seat_event_key
    return (
        diagnostic.code,
        key.instrument_id if key is not None else "",
        key.trade_date.isoformat() if key is not None else "",
        diagnostic.seat_event_id or "",
        diagnostic.topic_id or "",
        diagnostic.taxonomy_id or "",
        diagnostic.taxonomy_version or "",
        diagnostic.source or "",
        diagnostic.source_version or "",
        diagnostic.evidence_id or "",
        diagnostic.message,
    )


def _build_events(
    features: Iterable[SeatPerformanceFeature],
    policy: CooccurrencePolicy,
) -> tuple[
    tuple[_PreparedEvent, ...],
    tuple[CooccurrenceDiagnostic, ...],
    dict[SeatEventKey, str],
    SeatPerformanceFeature,
]:
    first: SeatPerformanceFeature | None = None
    expected: tuple[object, ...] | None = None
    feature_by_seat: dict[str, ParentFeatureProvenance] = {}
    samples_by_event_seat: dict[SeatEventKey, dict[str, list[PerformanceSample]]] = {}
    outcomes_by_event: dict[SeatEventKey, dict[str, set[str]]] = {}
    outcome_by_identity: dict[tuple[SeatEventKey, str], _EventOutcome] = {}
    event_ids: dict[SeatEventKey, str] = {}
    id_to_key: dict[str, SeatEventKey] = {}
    total_samples = 0
    feature_count = 0

    for feature in features:
        feature_count += 1
        if feature_count > policy.max_parent_features:
            raise CooccurrenceInputError(
                "max_parent_features_exceeded",
                "parent feature budget exceeded before producing results",
            )
        if type(feature) is not SeatPerformanceFeature:
            raise CooccurrenceInputError(
                "invalid_parent_feature", "parent features have invalid type"
            )
        if first is None:
            first = feature
            expected = (
                feature.schema_version,
                feature.window_start,
                feature.window_end,
                feature.decision_time,
                feature.algorithm_version,
                feature.policy_version,
                feature.policy_fingerprint,
            )
        if feature.seat_id in feature_by_seat:
            raise CooccurrenceInputError(
                "duplicate_parent_feature",
                f"duplicate parent feature for seat {feature.seat_id!r}",
            )
        actual: tuple[object, ...] = (
            feature.schema_version,
            feature.window_start,
            feature.window_end,
            feature.decision_time,
            feature.algorithm_version,
            feature.policy_version,
            feature.policy_fingerprint,
        )
        if actual != expected:
            raise CooccurrenceInputError(
                "parent_snapshot_mismatch",
                "parent features must share schema/window/decision/version/fingerprint",
            )
        feature_by_seat[feature.seat_id] = _feature_provenance(feature)
        for sample in feature.samples:
            total_samples += 1
            if total_samples > policy.max_input_samples:
                raise CooccurrenceInputError(
                    "max_input_samples_exceeded",
                    "parent sample budget exceeded before producing results",
                )
            if type(sample) is not PerformanceSample:
                raise CooccurrenceInputError(
                    "invalid_parent_sample", "parent samples have invalid type"
                )
            if not sample.included:
                continue
            outcome = _validate_sample(sample)
            key = outcome.key
            if key not in samples_by_event_seat and len(samples_by_event_seat) >= policy.max_events:
                raise CooccurrenceInputError(
                    "max_events_exceeded",
                    "distinct SeatEventKey budget exceeded before producing results",
                )
            seat_event_id = event_ids.setdefault(key, compute_seat_event_id(key))
            existing_key = id_to_key.setdefault(seat_event_id, key)
            if existing_key != key:
                raise CooccurrenceInputError(
                    "seat_event_id_collision",
                    "one seat event ID maps to multiple SeatEventKey values",
                )
            outcome = _EventOutcome(
                key=key,
                seat_event_id=seat_event_id,
                path_dates=outcome.path_dates,
                event_returns=outcome.event_returns,
                bars=outcome.bars,
                identity=outcome.identity,
            )
            samples_by_event_seat.setdefault(key, {}).setdefault(feature.seat_id, []).append(sample)
            outcomes_by_event.setdefault(key, {}).setdefault(feature.seat_id, set()).add(
                outcome.identity
            )
            outcome_by_identity.setdefault((key, outcome.identity), outcome)

    if first is None:
        raise CooccurrenceInputError(
            "empty_parent_features", "at least one parent feature is required"
        )

    diagnostics: list[CooccurrenceDiagnostic] = []
    prepared: list[_PreparedEvent] = []
    for key in sorted(samples_by_event_seat):
        seat_samples = samples_by_event_seat[key]
        seat_event_id = event_ids[key]
        seat_count = len(seat_samples)
        if seat_count > policy.max_seats_per_event:
            diagnostics.append(
                CooccurrenceDiagnostic(
                    code="event_seat_limit_exceeded",
                    message="event excluded because distinct seat membership exceeds policy",
                    seat_event_key=key,
                    seat_event_id=seat_event_id,
                )
            )
            continue
        if seat_count == 1:
            diagnostics.append(
                CooccurrenceDiagnostic(
                    code="isolated_event",
                    message="event has fewer than two distinct seats and creates no pair",
                    seat_event_key=key,
                    seat_event_id=seat_event_id,
                )
            )
            continue
        identities = {
            identity
            for seat_identities in outcomes_by_event[key].values()
            for identity in seat_identities
        }
        if len(identities) != 1:
            raise CooccurrenceInputError(
                "shared_outcome_conflict",
                f"shared event outcome conflict for {key.instrument_id} {key.trade_date}",
            )
        identity = next(iter(identities))
        outcome = outcome_by_identity[(key, identity)]
        members = tuple(
            _EventMember(
                seat_id=seat_id,
                feature=feature_by_seat[seat_id],
                samples=tuple(sorted(samples, key=_sample_sort_key)),
            )
            for seat_id, samples in sorted(seat_samples.items())
        )
        prepared.append(
            _PreparedEvent(
                key=key,
                reference=SeatEventReference(
                    seat_event_key=key,
                    seat_event_id=seat_event_id,
                    event_id_algorithm_version=SEAT_EVENT_ID_ALGORITHM_VERSION,
                ),
                outcome=outcome,
                members=members,
            )
        )
    return (
        tuple(prepared),
        tuple(sorted(diagnostics, key=_diagnostic_sort_key)),
        event_ids,
        first,
    )


def _topic_sort_key(membership: EventTopicMembership) -> tuple[str, ...]:
    return (
        membership.seat_event_key.instrument_id,
        membership.seat_event_key.trade_date.isoformat(),
        membership.topic_id,
        membership.taxonomy_id,
        membership.taxonomy_version,
        membership.assignment_version,
        membership.assignment_fingerprint,
        membership.source,
        membership.source_version,
        membership.evidence_id,
        membership.available_time.isoformat(),
    )


def _prepare_topics(
    topics: Iterable[EventTopicMembership] | None,
    decision_time: datetime,
    policy: CooccurrencePolicy,
    events: Sequence[_PreparedEvent],
) -> tuple[
    dict[SeatEventKey, dict[str, tuple[EventTopicMembership, ...]]],
    set[SeatEventKey],
    tuple[CooccurrenceDiagnostic, ...],
]:
    event_by_key = {event.key: event for event in events}
    diagnostics: list[CooccurrenceDiagnostic] = []
    grouped: dict[tuple[SeatEventKey, str], list[EventTopicMembership]] = {}
    topic_count = 0
    topic_iterator: Iterable[EventTopicMembership] = () if topics is None else topics
    for membership in topic_iterator:
        topic_count += 1
        if topic_count > policy.max_topic_membership_records:
            raise CooccurrenceInputError(
                "max_topic_membership_records_exceeded",
                "topic membership record budget exceeded before producing results",
            )
        if type(membership) is not EventTopicMembership:
            raise CooccurrenceInputError(
                "invalid_topic_membership",
                "topic memberships must contain EventTopicMembership instances",
            )
        if membership.available_time > decision_time:
            continue
        event = event_by_key.get(membership.seat_event_key)
        if event is None:
            diagnostics.append(
                CooccurrenceDiagnostic(
                    code="topic_event_not_in_parent",
                    message="visible topic membership has no eligible parent seat event",
                    seat_event_key=membership.seat_event_key,
                    seat_event_id=compute_seat_event_id(membership.seat_event_key),
                    topic_id=membership.topic_id,
                    taxonomy_id=membership.taxonomy_id,
                    taxonomy_version=membership.taxonomy_version,
                    source=membership.source,
                    source_version=membership.source_version,
                    evidence_id=membership.evidence_id,
                    available_time=membership.available_time,
                )
            )
            continue
        if not policy.allows_topic(membership):
            diagnostics.append(
                CooccurrenceDiagnostic(
                    code="topic_membership_not_allowed",
                    message="visible topic membership is outside the controlled policy allowlist",
                    seat_event_key=membership.seat_event_key,
                    seat_event_id=event.reference.seat_event_id,
                    topic_id=membership.topic_id,
                    taxonomy_id=membership.taxonomy_id,
                    taxonomy_version=membership.taxonomy_version,
                    source=membership.source,
                    source_version=membership.source_version,
                    evidence_id=membership.evidence_id,
                    available_time=membership.available_time,
                )
            )
            continue
        grouped.setdefault(membership.logical_key, []).append(membership)

    topics_by_event: dict[SeatEventKey, set[str]] = {}
    for key in grouped:
        topics_by_event.setdefault(key[0], set()).add(key[1])
    excluded_events: set[SeatEventKey] = set()
    for key, topic_ids in sorted(topics_by_event.items()):
        if len(topic_ids) > policy.max_topics_per_event:
            excluded_events.add(key)
            diagnostics.append(
                CooccurrenceDiagnostic(
                    code="event_topic_limit_exceeded",
                    message="event excluded because controlled topic count exceeds policy",
                    seat_event_key=key,
                    seat_event_id=event_by_key[key].reference.seat_event_id,
                )
            )

    conditioned: dict[SeatEventKey, dict[str, tuple[EventTopicMembership, ...]]] = {}
    for logical_key, records in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        if logical_key[0] in excluded_events:
            continue
        distinct_assignments = {record.assignment_key for record in records}
        if len(distinct_assignments) != 1:
            for record in sorted(records, key=_topic_sort_key):
                diagnostics.append(
                    CooccurrenceDiagnostic(
                        code="topic_membership_conflict",
                        message="visible logical topic membership has conflicting assignments",
                        seat_event_key=record.seat_event_key,
                        seat_event_id=event_by_key[record.seat_event_key].reference.seat_event_id,
                        topic_id=record.topic_id,
                        taxonomy_id=record.taxonomy_id,
                        taxonomy_version=record.taxonomy_version,
                        source=record.source,
                        source_version=record.source_version,
                        evidence_id=record.evidence_id,
                        available_time=record.available_time,
                    )
                )
            continue
        conditioned.setdefault(logical_key[0], {})[logical_key[1]] = tuple(
            sorted(set(records), key=_topic_sort_key)
        )
    return conditioned, excluded_events, tuple(sorted(diagnostics, key=_diagnostic_sort_key))


def _metric_values(outcomes: Sequence[_PreparedEvent], horizon: int) -> tuple[Decimal, ...]:
    index = {1: 0, 3: 2, 5: 4}[horizon]
    return tuple(event.outcome.event_returns[index] for event in outcomes)


def compute_bootstrap_mean_ci(
    values: Sequence[Decimal],
    event_ids: Sequence[str],
    key: CooccurrenceKey,
    horizon: int,
    policy: CooccurrencePolicy,
) -> tuple[Decimal | None, Decimal | None, CIStatus]:
    """Compute the versioned deterministic non-parametric mean bootstrap CI."""

    if len(values) != len(event_ids) or not values:
        raise ValueError("values and event_ids must be non-empty and aligned")
    if horizon not in (1, 3, 5):
        raise ValueError("horizon must be one of 1, 3, 5")
    single_horizon_draws = len(values) * policy.resamples
    if single_horizon_draws > policy.max_bootstrap_draws:
        raise CooccurrenceInputError(
            "max_bootstrap_draws_exceeded",
            "bootstrap draw budget exceeded before computing a CI",
        )
    ordered = tuple(sorted(zip(event_ids, values, strict=True), key=lambda pair: pair[0]))
    sorted_event_ids = tuple(item[0] for item in ordered)
    sorted_values = tuple(item[1] for item in ordered)
    if len(sorted_event_ids) < policy.min_ci_samples:
        return None, None, CIStatus.INSUFFICIENT_SAMPLES
    seed_payload = {
        "algorithmVersion": policy.bootstrap_algorithm_version,
        "eventIds": list(sorted_event_ids),
        "hashToIndexAlgorithmVersion": policy.hash_to_index_algorithm_version,
        "key": {
            "leftSeatId": key.left_seat_id,
            "rightSeatId": key.right_seat_id,
            "topicId": key.topic_id,
        },
        "metric": f"T+{horizon}",
        "policyFingerprint": policy.fingerprint,
    }
    seed = _canonical_json(seed_payload).encode("utf-8")
    bootstrap_means: list[Decimal] = []
    with localcontext() as context:
        context.prec = policy.decimal_precision
        context.rounding = ROUND_HALF_EVEN
        for replicate in range(policy.resamples):
            total = Decimal("0")
            for draw in range(len(sorted_values)):
                draw_input = seed + f"|{replicate}|{draw}".encode("ascii")
                digest = hashlib.sha256(draw_input).digest()
                index = int.from_bytes(digest[:8], "big") % len(sorted_values)
                total += sorted_values[index]
            bootstrap_means.append(total / Decimal(len(sorted_values)))
        lower = r7_quantile(bootstrap_means, policy.alpha / Decimal("2"))
        upper = r7_quantile(bootstrap_means, Decimal("1") - policy.alpha / Decimal("2"))
    return lower, upper, CIStatus.PUBLISHED


def _make_metric(
    outcomes: Sequence[_PreparedEvent],
    key: CooccurrenceKey,
    horizon: int,
    policy: CooccurrencePolicy,
) -> CooccurrenceMetric:
    values = _metric_values(outcomes, horizon)
    event_ids = tuple(event.reference.seat_event_id for event in outcomes)
    with localcontext() as context:
        context.prec = policy.decimal_precision
        context.rounding = ROUND_HALF_EVEN
        mean = sum(values, Decimal("0")) / Decimal(len(values))
        minimum = min(values)
        maximum = max(values)
        p25 = r7_quantile(values, Decimal("0.25"))
        p50 = r7_quantile(values, Decimal("0.50"))
        p75 = r7_quantile(values, Decimal("0.75"))
    ci_lower, ci_upper, ci_status = compute_bootstrap_mean_ci(
        values,
        event_ids,
        key,
        horizon,
        policy,
    )
    return CooccurrenceMetric(
        horizon=horizon,
        count=len(values),
        mean=mean,
        minimum=minimum,
        p25=p25,
        p50=p50,
        p75=p75,
        maximum=maximum,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_status=ci_status,
    )


def _validate_bootstrap_budget(
    key_events: dict[CooccurrenceKey, list[_PreparedEvent]],
    policy: CooccurrencePolicy,
) -> None:
    total_draws = 0
    for key in sorted(key_events, key=lambda item: item.canonical_tuple):
        support = len(key_events[key])
        if support < policy.min_ci_samples:
            continue
        draws = support * policy.resamples * 3
        total_draws += draws
        if total_draws > policy.max_bootstrap_draws:
            raise CooccurrenceInputError(
                "max_bootstrap_draws_exceeded",
                "bootstrap draw budget exceeded before computing any CI",
            )


def _event_member_by_seat(event: _PreparedEvent) -> dict[str, _EventMember]:
    return {member.seat_id: member for member in event.members}


def _key_event_provenance(
    key: CooccurrenceKey,
    outcomes: Sequence[_PreparedEvent],
    topic_records: dict[tuple[SeatEventKey, str], tuple[EventTopicMembership, ...]],
) -> CooccurrenceProvenance:
    event_references = tuple(event.reference for event in outcomes)
    members_by_event = [_event_member_by_seat(event) for event in outcomes]
    parent_features = tuple(
        sorted(
            {
                members[key_seat].feature
                for members in members_by_event
                for key_seat in (key.left_seat_id, key.right_seat_id)
            },
            key=lambda item: item.seat_id,
        )
    )
    trade_evidence = tuple(
        SeatTradeEvidence(
            seat_id=seat_id,
            samples=tuple(
                sample for members in members_by_event for sample in members[seat_id].samples
            ),
        )
        for seat_id in (key.left_seat_id, key.right_seat_id)
    )
    event_outcomes = tuple(
        EventOutcomeProvenance(
            event=event.reference,
            shared_bars=tuple(event.outcome.bars),
        )
        for event in outcomes
    )
    shared_bars = tuple(
        bar for event_outcome in event_outcomes for bar in event_outcome.shared_bars
    )
    topic_memberships: list[EventTopicMembership] = []
    if key.topic_id is not None:
        for event in outcomes:
            topic_memberships.extend(topic_records[(event.key, key.topic_id)])
    times = [
        sample.trade_available_time for evidence in trade_evidence for sample in evidence.samples
    ]
    times.extend(bar.available_time for bar in shared_bars)
    times.extend(membership.available_time for membership in topic_memberships)
    if not times:
        raise CooccurrenceInputError(
            "missing_provenance", "co-occurrence record has no input availability time"
        )
    return CooccurrenceProvenance(
        events=event_references,
        event_outcomes=event_outcomes,
        parent_features=parent_features,
        seat_trade_evidence=trade_evidence,
        shared_bars=shared_bars,
        topic_memberships=tuple(sorted(set(topic_memberships), key=_topic_sort_key)),
        logical_available_time=max(times),
    )


def _metric_payload(metric: CooccurrenceMetric) -> dict[str, object]:
    return {
        "ciLower": _decimal_text(metric.ci_lower) if metric.ci_lower is not None else None,
        "ciStatus": metric.ci_status.value,
        "ciUpper": _decimal_text(metric.ci_upper) if metric.ci_upper is not None else None,
        "count": metric.count,
        "horizon": metric.horizon,
        "max": _decimal_text(metric.maximum),
        "mean": _decimal_text(metric.mean),
        "min": _decimal_text(metric.minimum),
        "p25": _decimal_text(metric.p25),
        "p50": _decimal_text(metric.p50),
        "p75": _decimal_text(metric.p75),
    }


def _provenance_payload(provenance: CooccurrenceProvenance) -> dict[str, object]:
    return {
        "eventOutcomes": [
            {
                "event": {
                    "algorithmVersion": event_outcome.event.event_id_algorithm_version,
                    "eventId": event_outcome.event.seat_event_id,
                    "instrumentId": event_outcome.event.seat_event_key.instrument_id,
                    "tradeDate": event_outcome.event.seat_event_key.trade_date.isoformat(),
                },
                "sharedBars": [_bar_payload(bar) for bar in event_outcome.shared_bars],
            }
            for event_outcome in provenance.event_outcomes
        ],
        "events": [
            {
                "algorithmVersion": event.event_id_algorithm_version,
                "eventId": event.seat_event_id,
                "instrumentId": event.seat_event_key.instrument_id,
                "tradeDate": event.seat_event_key.trade_date.isoformat(),
            }
            for event in provenance.events
        ],
        "logicalAvailableTime": provenance.logical_available_time.isoformat(),
        "parentFeatures": [
            {
                "algorithmVersion": item.algorithm_version,
                "policyFingerprint": item.policy_fingerprint,
                "policyVersion": item.policy_version,
                "schemaVersion": item.schema_version,
                "seatId": item.seat_id,
            }
            for item in provenance.parent_features
        ],
        "sharedBars": [_bar_payload(bar) for bar in provenance.shared_bars],
        "seatTradeEvidence": [
            {
                "samples": [_sample_payload(sample) for sample in evidence.samples],
                "seatId": evidence.seat_id,
            }
            for evidence in provenance.seat_trade_evidence
        ],
        "topicMemberships": [
            {
                "assignmentFingerprint": membership.assignment_fingerprint,
                "assignmentVersion": membership.assignment_version,
                "availableTime": membership.available_time.isoformat(),
                "evidenceId": membership.evidence_id,
                "instrumentId": membership.seat_event_key.instrument_id,
                "source": membership.source,
                "sourceVersion": membership.source_version,
                "taxonomyId": membership.taxonomy_id,
                "taxonomyVersion": membership.taxonomy_version,
                "topicId": membership.topic_id,
                "tradeDate": membership.seat_event_key.trade_date.isoformat(),
                "upstreamMarketEventIds": list(membership.upstream_market_event_ids),
            }
            for membership in provenance.topic_memberships
        ],
    }


def _record_payload(record: CooccurrenceRecord) -> dict[str, object]:
    return {
        "key": {
            "leftSeatId": record.key.left_seat_id,
            "rightSeatId": record.key.right_seat_id,
            "topicId": record.key.topic_id,
        },
        "provenance": _provenance_payload(record.provenance),
        "semanticLabel": record.semantic_label,
        "asOfSemantics": record.as_of_semantics,
        "statistics": [_metric_payload(metric) for metric in record.statistics],
        "supportCount": record.support_count,
    }


def _diagnostic_payload(diagnostic: CooccurrenceDiagnostic) -> dict[str, object]:
    key = diagnostic.seat_event_key
    return {
        "availableTime": diagnostic.available_time.isoformat()
        if diagnostic.available_time is not None
        else None,
        "code": diagnostic.code,
        "evidenceId": diagnostic.evidence_id,
        "message": diagnostic.message,
        "seatEventId": diagnostic.seat_event_id,
        "seatEventKey": {
            "instrumentId": key.instrument_id,
            "tradeDate": key.trade_date.isoformat(),
        }
        if key is not None
        else None,
        "source": diagnostic.source,
        "sourceVersion": diagnostic.source_version,
        "taxonomyId": diagnostic.taxonomy_id,
        "taxonomyVersion": diagnostic.taxonomy_version,
        "topicId": diagnostic.topic_id,
    }


def compute_seat_cooccurrence(
    features: Iterable[SeatPerformanceFeature],
    topic_memberships: Iterable[EventTopicMembership] | None = None,
    *,
    policy: CooccurrencePolicy | None = None,
) -> CooccurrenceResult:
    """Compute canonical seat-pair and controlled topic-conditioned statistics."""

    selected_policy = CooccurrencePolicy() if policy is None else policy
    if type(selected_policy) is not CooccurrencePolicy:
        raise TypeError("policy must be CooccurrencePolicy")
    events, event_diagnostics, _, first = _build_events(features, selected_policy)
    conditioned_topics, excluded_topic_events, topic_diagnostics = _prepare_topics(
        topic_memberships,
        first.decision_time,
        selected_policy,
        events,
    )

    key_events: dict[CooccurrenceKey, list[_PreparedEvent]] = {}
    topic_records_by_key: dict[
        CooccurrenceKey, dict[tuple[SeatEventKey, str], tuple[EventTopicMembership, ...]]
    ] = {}

    primitive_to_key: dict[tuple[str, str, str], CooccurrenceKey] = {}

    def add_edge(
        primitive_key: tuple[str, str, str],
        event: _PreparedEvent,
        topic_memberships: tuple[EventTopicMembership, ...] | None = None,
    ) -> None:
        edge_key = primitive_to_key.get(primitive_key)
        if edge_key is None:
            if len(primitive_to_key) >= selected_policy.max_edges:
                raise CooccurrenceInputError(
                    "max_edges_exceeded",
                    "co-occurrence edge budget exceeded before producing results",
                )
            edge_key = CooccurrenceKey(
                primitive_key[0],
                primitive_key[1],
                primitive_key[2] or None,
            )
            primitive_to_key[primitive_key] = edge_key
            key_events[edge_key] = []
        key_events[edge_key].append(event)
        if topic_memberships is not None:
            topic_records_by_key.setdefault(edge_key, {})[(event.key, edge_key.topic_id or "")] = (
                topic_memberships
            )

    for event in events:
        if event.key in excluded_topic_events:
            continue
        seat_ids = tuple(member.seat_id for member in event.members)
        event_topics = conditioned_topics.get(event.key, {})
        for left, right in combinations(seat_ids, 2):
            left_id, right_id = sorted((left, right))
            add_edge((left_id, right_id, ""), event)
            for topic_id, topic_memberships in sorted(event_topics.items()):
                add_edge((left_id, right_id, topic_id), event, topic_memberships)

    _validate_bootstrap_budget(key_events, selected_policy)

    output_records: list[CooccurrenceRecord] = []
    for key in sorted(key_events, key=lambda item: item.canonical_tuple):
        outcomes = tuple(sorted(key_events[key], key=lambda event: event.reference.seat_event_id))
        statistics = tuple(
            _make_metric(outcomes, key, horizon, selected_policy) for horizon in (1, 3, 5)
        )
        provenance = _key_event_provenance(
            key,
            outcomes,
            topic_records_by_key.get(key, {}),
        )
        output_records.append(
            CooccurrenceRecord(
                key=key,
                support_count=len(outcomes),
                statistics=statistics,
                provenance=provenance,
            )
        )

    diagnostics = tuple(sorted((*event_diagnostics, *topic_diagnostics), key=_diagnostic_sort_key))
    result_payload = {
        "algorithmVersion": COOCCURRENCE_ALGORITHM_VERSION,
        "asOfSemantics": "as_of_request_decision_time",
        "decisionTime": first.decision_time.isoformat(),
        "diagnostics": [_diagnostic_payload(item) for item in diagnostics],
        "policyFingerprint": selected_policy.fingerprint,
        "records": [_record_payload(record) for record in output_records],
        "schemaVersion": COOCCURRENCE_SCHEMA_VERSION,
        "windowEnd": first.window_end.isoformat(),
        "windowStart": first.window_start.isoformat(),
    }
    result_fingerprint = (
        "sha256:"
        + hashlib.sha256(
            _canonical_json(
                {
                    "algorithmVersion": COOCCURRENCE_FINGERPRINT_ALGORITHM_VERSION,
                    "result": result_payload,
                }
            ).encode("utf-8")
        ).hexdigest()
    )
    return CooccurrenceResult(
        schema_version=COOCCURRENCE_SCHEMA_VERSION,
        algorithm_version=COOCCURRENCE_ALGORITHM_VERSION,
        policy_version=selected_policy.policy_version,
        policy_fingerprint=selected_policy.fingerprint,
        window_start=first.window_start,
        window_end=first.window_end,
        decision_time=first.decision_time,
        records=tuple(output_records),
        diagnostics=diagnostics,
        fingerprint=result_fingerprint,
    )


__all__ = [
    "CooccurrenceInputError",
    "compute_bootstrap_mean_ci",
    "compute_seat_cooccurrence",
    "compute_seat_event_id",
    "quantile_r7",
    "r7_quantile",
]
