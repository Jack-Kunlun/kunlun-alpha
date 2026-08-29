"""Deterministic local ranking materialization from real point-in-time daily bars."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from data_worker.jobs.local_reference import LocalReferenceCatalog
from quant_core.ranking import (
    FeatureObservation,
    InstrumentFeatureSnapshot,
    MissingFeaturePolicy,
    RankingDirection,
    RankingFeatureSpec,
    RankingSnapshot,
    RankingSpec,
    rank_instruments,
)

from .reader import DailyRankingBar

_WINDOW = 10
_ALGORITHM_VERSION = "local-daily-bars-ranking-v1"
LOCAL_DAILY_BARS_RANKING_SPEC = RankingSpec(
    spec_id="local-daily-bars-ranking",
    version="1.0.0",
    algorithm_version=_ALGORITHM_VERSION,
    minimum_coverage_bps=10_000,
    features=(
        RankingFeatureSpec(
            key="momentum_10d",
            label="10 日动量",
            weight_bps=4_000,
            direction=RankingDirection.HIGHER_IS_BETTER,
            missing_policy=MissingFeaturePolicy.EXCLUDE,
        ),
        RankingFeatureSpec(
            key="average_amount_10d",
            label="10 日平均成交额",
            weight_bps=3_000,
            direction=RankingDirection.HIGHER_IS_BETTER,
            missing_policy=MissingFeaturePolicy.EXCLUDE,
        ),
        RankingFeatureSpec(
            key="intraday_range_10d",
            label="10 日日内振幅",
            weight_bps=3_000,
            direction=RankingDirection.LOWER_IS_BETTER,
            missing_policy=MissingFeaturePolicy.EXCLUDE,
        ),
    ),
)


class RankingMaterializationError(RuntimeError):
    """Daily-bar inputs violate the ranking's point-in-time contract."""


def _canonical_instant(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RankingMaterializationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _source(rows: tuple[DailyRankingBar, ...]) -> str:
    evidence = [
        {
            "date": row.date.isoformat(),
            "evidenceId": row.evidence_id,
            "source": row.source,
            "sourceVersion": row.source_version,
        }
        for row in rows
    ]
    encoded = json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    return f"bars_daily_v2:{_ALGORITHM_VERSION}:sha256:{digest}"


def _missing_observations(reason: str, reference_version: str) -> tuple[FeatureObservation, ...]:
    return tuple(
        FeatureObservation(
            feature_key=feature.key,
            value=None,
            missing_reason=f"{reason};REFERENCE={reference_version}",
        )
        for feature in LOCAL_DAILY_BARS_RANKING_SPEC.features
    )


def _observations(
    rows: tuple[DailyRankingBar, ...],
    *,
    reference_provenance: str,
    reference_version: str,
) -> tuple[FeatureObservation, ...]:
    if len(rows) < _WINDOW:
        return _missing_observations(
            f"INSUFFICIENT_DAILY_BARS:{len(rows)}/{_WINDOW}", reference_version
        )
    selected = rows[-_WINDOW:]
    visible_at = max(instant for row in selected for instant in row.instants)
    source = f"{_source(selected)};reference={reference_provenance}"
    momentum = selected[-1].close / selected[0].close - Decimal(1)
    average_amount = sum((row.amount for row in selected), start=Decimal(0)) / Decimal(_WINDOW)
    intraday_range = sum(
        ((row.high - row.low) / row.close for row in selected),
        start=Decimal(0),
    ) / Decimal(_WINDOW)
    return (
        FeatureObservation(
            feature_key="momentum_10d",
            value=momentum,
            available_time=visible_at,
            source=source,
        ),
        FeatureObservation(
            feature_key="average_amount_10d",
            value=average_amount,
            available_time=visible_at,
            source=source,
        ),
        FeatureObservation(
            feature_key="intraday_range_10d",
            value=intraday_range,
            available_time=visible_at,
            source=source,
        ),
    )


def build_local_ranking_snapshot(
    *,
    catalog: LocalReferenceCatalog,
    bars_by_instrument: dict[str, tuple[DailyRankingBar, ...]],
    read_cutoff: datetime,
    generated_at: datetime,
) -> RankingSnapshot:
    cutoff = _canonical_instant(read_cutoff, "read_cutoff")
    generated = _canonical_instant(generated_at, "generated_at")
    catalog_ids = {item.instrument_id for item in catalog.instruments}
    unknown_ids = set(bars_by_instrument) - catalog_ids
    if unknown_ids:
        raise RankingMaterializationError(
            f"bars contain unknown instruments: {sorted(unknown_ids)}"
        )

    sector_names = {item.sector_id: item.name for item in catalog.sectors}
    reference_provenance = f"{catalog.source}@{catalog.source_version}:{catalog.evidence_id}"
    inputs: list[InstrumentFeatureSnapshot] = []
    visibility_times = [catalog.available_time]
    for instrument in catalog.instruments:
        rows = tuple(
            sorted(bars_by_instrument.get(instrument.instrument_id, ()), key=lambda row: row.date)
        )
        if any(row.instrument_id != instrument.instrument_id for row in rows):
            raise RankingMaterializationError(
                f"bar instrument mismatch for {instrument.instrument_id}"
            )
        dates = [row.date for row in rows]
        if len(dates) != len(set(dates)):
            raise RankingMaterializationError(
                f"duplicate daily bar date for {instrument.instrument_id}"
            )
        future = [instant for row in rows for instant in row.instants if instant > cutoff]
        if future:
            raise RankingMaterializationError(
                f"bar visibility is later than read cutoff for {instrument.instrument_id}"
            )
        visibility_times.extend(instant for row in rows for instant in row.instants)
        inputs.append(
            InstrumentFeatureSnapshot(
                instrument_id=instrument.instrument_id,
                instrument_name=instrument.name,
                sector=sector_names[instrument.sector_id],
                observations=_observations(
                    rows,
                    reference_provenance=reference_provenance,
                    reference_version=catalog.catalog_version,
                ),
            )
        )

    as_of = max(visibility_times)
    if as_of > cutoff:
        raise RankingMaterializationError("catalog visibility is later than read cutoff")
    if generated < as_of:
        raise RankingMaterializationError("generated_at is earlier than selected input visibility")
    return rank_instruments(
        spec=LOCAL_DAILY_BARS_RANKING_SPEC,
        as_of=as_of,
        generated_at=generated,
        instruments=tuple(inputs),
    )
