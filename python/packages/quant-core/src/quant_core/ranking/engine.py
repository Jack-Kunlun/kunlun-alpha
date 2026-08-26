from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from .models import (
    FeatureObservation,
    InstrumentFeatureSnapshot,
    MissingFeaturePolicy,
    RankingContribution,
    RankingDirection,
    RankingFeatureSpec,
    RankingFilter,
    RankingInputError,
    RankingRow,
    RankingRowStatus,
    RankingSnapshot,
    RankingSpec,
    canonical_instant,
)

_BPS = Decimal(10_000)


def _canonical_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _input_fingerprint(
    *,
    spec: RankingSpec,
    as_of: datetime,
    instruments: tuple[InstrumentFeatureSnapshot, ...],
    pit_by_instrument: dict[str, dict[str, FeatureObservation]],
) -> str:
    payload = {
        "asOf": canonical_instant(as_of, field_name="as_of"),
        "instruments": [
            {
                "instrumentId": instrument.instrument_id,
                "instrumentName": instrument.instrument_name,
                "observations": [
                    {
                        "availableTime": (
                            canonical_instant(
                                observation.available_time, field_name="available_time"
                            )
                            if observation.available_time is not None
                            else None
                        ),
                        "featureKey": observation.feature_key,
                        "missingReason": observation.missing_reason,
                        "source": observation.source,
                        "value": (
                            _canonical_decimal(observation.value)
                            if observation.value is not None
                            else None
                        ),
                    }
                    for observation in sorted(
                        pit_by_instrument[instrument.instrument_id].values(),
                        key=lambda item: item.feature_key,
                    )
                ],
                "sector": instrument.sector,
            }
            for instrument in sorted(instruments, key=lambda item: item.instrument_id)
        ],
        "specFingerprint": spec.fingerprint,
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _point_in_time_observation(
    observation: FeatureObservation | None,
    *,
    feature_key: str,
    as_of: datetime,
) -> FeatureObservation:
    if observation is None:
        return FeatureObservation(
            feature_key=feature_key,
            value=None,
            missing_reason="FEATURE_NOT_PROVIDED",
        )
    if observation.available_time is not None and observation.available_time > as_of:
        return FeatureObservation(
            feature_key=feature_key,
            value=None,
            missing_reason="NOT_AVAILABLE_AT_SNAPSHOT",
        )
    if observation.value is None:
        return observation
    if observation.available_time is None or observation.available_time > as_of:
        return FeatureObservation(
            feature_key=feature_key,
            value=None,
            missing_reason="NOT_AVAILABLE_AT_SNAPSHOT",
        )
    return observation


def _normalization_map(
    *,
    feature: RankingFeatureSpec,
    observations: dict[str, FeatureObservation],
) -> dict[str, int]:
    available = {
        instrument_id: observation.value
        for instrument_id, observation in observations.items()
        if observation.value is not None
    }
    if not available:
        return {}
    values = tuple(available.values())
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return {instrument_id: 5_000 for instrument_id in available}

    result: dict[str, int] = {}
    for instrument_id, value in available.items():
        score = (value - minimum) / (maximum - minimum) * _BPS
        if feature.direction is RankingDirection.LOWER_IS_BETTER:
            score = _BPS - score
        result[instrument_id] = int(score.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return result


def _allocate_integer_budget(
    *,
    budget: int,
    weighted_keys: tuple[tuple[str, int], ...],
) -> dict[str, int]:
    if budget == 0 or not weighted_keys:
        return {key: 0 for key, _ in weighted_keys}
    total_weight = sum(weight for _, weight in weighted_keys)
    exact = {
        key: Decimal(budget) * Decimal(weight) / Decimal(total_weight)
        for key, weight in weighted_keys
    }
    allocated = {
        key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()
    }
    residual = budget - sum(allocated.values())
    order = sorted(
        weighted_keys,
        key=lambda item: (-(exact[item[0]] - Decimal(allocated[item[0]])), item[0]),
    )
    for key, _ in order[:residual]:
        allocated[key] += 1
    return allocated


def _round_contributions(
    raw: tuple[tuple[str, Decimal], ...],
) -> dict[str, int]:
    floors = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in raw}
    target = int(
        sum((value for _, value in raw), start=Decimal(0)).to_integral_value(rounding=ROUND_HALF_UP)
    )
    residual = target - sum(floors.values())
    order = sorted(
        raw,
        key=lambda item: (-(item[1] - Decimal(floors[item[0]])), item[0]),
    )
    for key, _ in order[:residual]:
        floors[key] += 1
    return floors


def _build_row(
    *,
    instrument: InstrumentFeatureSnapshot,
    spec: RankingSpec,
    pit: dict[str, FeatureObservation],
    normalized: dict[str, dict[str, int]],
) -> RankingRow:
    available_features = tuple(
        feature for feature in spec.features if pit[feature.key].value is not None
    )
    coverage_bps = sum(feature.weight_bps for feature in available_features)
    exclusion_reasons = [
        f"MISSING_REQUIRED_FEATURE:{feature.key}"
        for feature in spec.features
        if pit[feature.key].value is None and feature.missing_policy is MissingFeaturePolicy.EXCLUDE
    ]
    if not available_features:
        exclusion_reasons.append("NO_AVAILABLE_FEATURES")
    if coverage_bps < spec.minimum_coverage_bps:
        exclusion_reasons.append("COVERAGE_BELOW_MINIMUM")

    is_excluded = bool(exclusion_reasons)
    effective_weights: dict[str, int] = {feature.key: 0 for feature in spec.features}
    contribution_values: dict[str, int] = {feature.key: 0 for feature in spec.features}

    if not is_excluded:
        zero_missing_weight = sum(
            feature.weight_bps
            for feature in spec.features
            if pit[feature.key].value is None
            and feature.missing_policy is MissingFeaturePolicy.ZERO
        )
        available_budget = 10_000 - zero_missing_weight
        effective_weights.update(
            _allocate_integer_budget(
                budget=available_budget,
                weighted_keys=tuple(
                    (feature.key, feature.weight_bps) for feature in available_features
                ),
            )
        )
        for feature in spec.features:
            if (
                pit[feature.key].value is None
                and feature.missing_policy is MissingFeaturePolicy.ZERO
            ):
                effective_weights[feature.key] = feature.weight_bps

        raw: tuple[tuple[str, Decimal], ...] = tuple(
            (
                feature.key,
                Decimal(normalized[feature.key][instrument.instrument_id])
                * Decimal(effective_weights[feature.key])
                / _BPS,
            )
            for feature in available_features
        )
        contribution_values.update(_round_contributions(raw))

    contributions = tuple(
        RankingContribution(
            feature_key=feature.key,
            label=feature.label,
            direction=feature.direction,
            raw_value=pit[feature.key].value,
            normalized_score_bps=normalized[feature.key].get(instrument.instrument_id),
            configured_weight_bps=feature.weight_bps,
            effective_weight_bps=effective_weights[feature.key],
            contribution_bps=contribution_values[feature.key],
            missing_reason=pit[feature.key].missing_reason,
            available_time=pit[feature.key].available_time,
            source=pit[feature.key].source,
        )
        for feature in spec.features
    )
    return RankingRow(
        instrument_id=instrument.instrument_id,
        instrument_name=instrument.instrument_name,
        sector=instrument.sector,
        status=(RankingRowStatus.EXCLUDED if is_excluded else RankingRowStatus.INCLUDED),
        rank=None,
        score_bps=(None if is_excluded else sum(item.contribution_bps for item in contributions)),
        coverage_bps=coverage_bps,
        contributions=contributions,
        exclusion_reasons=tuple(exclusion_reasons),
    )


def rank_instruments(
    *,
    spec: RankingSpec,
    as_of: datetime,
    generated_at: datetime,
    instruments: tuple[InstrumentFeatureSnapshot, ...],
) -> RankingSnapshot:
    """Build a deterministic point-in-time ranking with itemized contributions."""
    canonical_instant(as_of, field_name="as_of")
    canonical_instant(generated_at, field_name="generated_at")
    if generated_at < as_of:
        raise RankingInputError("generated_at must not be earlier than as_of")
    instrument_ids = [instrument.instrument_id for instrument in instruments]
    if len(instrument_ids) != len(set(instrument_ids)):
        raise RankingInputError("instrument_id values must be unique")

    pit_by_instrument: dict[str, dict[str, FeatureObservation]] = {}
    for instrument in instruments:
        supplied = {item.feature_key: item for item in instrument.observations}
        unknown = set(supplied) - {feature.key for feature in spec.features}
        if unknown:
            raise RankingInputError(
                f"instrument {instrument.instrument_id} has unknown features: {sorted(unknown)}"
            )
        pit_by_instrument[instrument.instrument_id] = {
            feature.key: _point_in_time_observation(
                supplied.get(feature.key),
                feature_key=feature.key,
                as_of=as_of,
            )
            for feature in spec.features
        }

    normalized = {
        feature.key: _normalization_map(
            feature=feature,
            observations={
                instrument.instrument_id: pit_by_instrument[instrument.instrument_id][feature.key]
                for instrument in instruments
            },
        )
        for feature in spec.features
    }
    rows = tuple(
        _build_row(
            instrument=instrument,
            spec=spec,
            pit=pit_by_instrument[instrument.instrument_id],
            normalized=normalized,
        )
        for instrument in instruments
    )
    included = sorted(
        (row for row in rows if row.status is RankingRowStatus.INCLUDED),
        key=lambda row: (-int(row.score_bps or 0), -row.coverage_bps, row.instrument_id),
    )
    ranked = tuple(replace(row, rank=index) for index, row in enumerate(included, start=1))
    excluded = tuple(
        sorted(
            (row for row in rows if row.status is RankingRowStatus.EXCLUDED),
            key=lambda row: row.instrument_id,
        )
    )
    input_fingerprint = _input_fingerprint(
        spec=spec,
        as_of=as_of,
        instruments=instruments,
        pit_by_instrument=pit_by_instrument,
    )
    snapshot_id = hashlib.sha256(f"{spec.fingerprint}:{input_fingerprint}".encode()).hexdigest()
    return RankingSnapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
        generated_at=generated_at,
        spec=spec,
        input_fingerprint=input_fingerprint,
        rows=ranked + excluded,
    )


def filter_ranking_rows(
    snapshot: RankingSnapshot,
    ranking_filter: RankingFilter,
) -> tuple[RankingRow, ...]:
    """Filter a ranking without recalculating or changing global ranks."""
    query = ranking_filter.query.strip().casefold()
    return tuple(
        row
        for row in snapshot.rows
        if (ranking_filter.include_excluded or row.status is RankingRowStatus.INCLUDED)
        and (not ranking_filter.sectors or row.sector in ranking_filter.sectors)
        and (
            ranking_filter.minimum_score_bps is None
            or row.score_bps is None
            or row.score_bps >= ranking_filter.minimum_score_bps
        )
        and (
            not query
            or query in row.instrument_id.casefold()
            or query in row.instrument_name.casefold()
        )
    )
