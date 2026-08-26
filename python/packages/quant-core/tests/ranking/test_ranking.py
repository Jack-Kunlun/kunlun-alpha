from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from quant_core.ranking import (
    FeatureObservation,
    InstrumentFeatureSnapshot,
    MissingFeaturePolicy,
    RankingDirection,
    RankingFeatureSpec,
    RankingFilter,
    RankingInputError,
    RankingRowStatus,
    RankingSnapshot,
    RankingSpec,
    filter_ranking_rows,
    rank_instruments,
)

AS_OF = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)


def _spec(*, minimum_coverage_bps: int = 5_000) -> RankingSpec:
    return RankingSpec(
        spec_id="cn-equity-intelligence",
        version="1.0.0",
        minimum_coverage_bps=minimum_coverage_bps,
        features=(
            RankingFeatureSpec(
                key="momentum",
                label="Momentum",
                weight_bps=5_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
            ),
            RankingFeatureSpec(
                key="quality",
                label="Quality",
                weight_bps=3_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
            ),
            RankingFeatureSpec(
                key="risk",
                label="Risk",
                weight_bps=2_000,
                direction=RankingDirection.LOWER_IS_BETTER,
                missing_policy=MissingFeaturePolicy.ZERO,
            ),
        ),
    )


def _observation(key: str, value: str, *, offset_minutes: int = -5) -> FeatureObservation:
    return FeatureObservation(
        feature_key=key,
        value=Decimal(value),
        available_time=AS_OF + timedelta(minutes=offset_minutes),
        source="feature-store:acceptance-v1",
    )


def _instrument(
    instrument_id: str,
    name: str,
    sector: str,
    observations: tuple[FeatureObservation, ...],
) -> InstrumentFeatureSnapshot:
    return InstrumentFeatureSnapshot(
        instrument_id=instrument_id,
        instrument_name=name,
        sector=sector,
        observations=observations,
    )


def _inputs() -> tuple[InstrumentFeatureSnapshot, ...]:
    common = (
        _observation("momentum", "90"),
        _observation("quality", "80"),
        _observation("risk", "10"),
    )
    return (
        _instrument("600519.SH", "Alpha", "Consumer", common),
        _instrument(
            "000001.SZ",
            "Beta",
            "Bank",
            (
                _observation("momentum", "70"),
                FeatureObservation(
                    feature_key="quality",
                    value=None,
                    missing_reason="UPSTREAM_VALUE_MISSING",
                ),
                _observation("risk", "30"),
            ),
        ),
        _instrument("601318.SH", "Gamma", "Insurance", common),
    )


def test_same_point_in_time_input_is_stable_and_ties_use_instrument_id() -> None:
    first = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=1),
        instruments=_inputs(),
    )
    second = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=2),
        instruments=tuple(reversed(_inputs())),
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.input_fingerprint == second.input_fingerprint
    assert [row.instrument_id for row in first.rows] == [
        "600519.SH",
        "601318.SH",
        "000001.SZ",
    ]
    assert [row.rank for row in first.rows] == [1, 2, 3]
    assert all(
        row.score_bps == sum(item.contribution_bps for item in row.contributions)
        for row in first.rows
    )


def test_future_feature_is_not_used_and_missing_policy_is_explained() -> None:
    instrument = _instrument(
        "600519.SH",
        "Alpha",
        "Consumer",
        (
            _observation("momentum", "90"),
            _observation("quality", "80", offset_minutes=5),
            _observation("risk", "10"),
        ),
    )

    snapshot = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(instrument,),
    )
    row = snapshot.rows[0]
    quality = next(item for item in row.contributions if item.feature_key == "quality")

    assert row.status is RankingRowStatus.INCLUDED
    assert row.coverage_bps == 7_000
    assert quality.raw_value is None
    assert quality.missing_reason == "NOT_AVAILABLE_AT_SNAPSHOT"
    assert quality.effective_weight_bps == 0
    assert sum(item.effective_weight_bps for item in row.contributions) == 10_000


def test_zero_policy_keeps_weight_and_records_zero_contribution() -> None:
    instrument = _instrument(
        "600519.SH",
        "Alpha",
        "Consumer",
        (
            _observation("momentum", "90"),
            _observation("quality", "80"),
            FeatureObservation(
                feature_key="risk",
                value=None,
                missing_reason="UPSTREAM_VALUE_MISSING",
            ),
        ),
    )

    row = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(instrument,),
    ).rows[0]
    risk = next(item for item in row.contributions if item.feature_key == "risk")

    assert row.coverage_bps == 8_000
    assert risk.effective_weight_bps == 2_000
    assert risk.contribution_bps == 0
    assert risk.missing_reason == "UPSTREAM_VALUE_MISSING"


def test_required_missing_feature_and_low_coverage_are_excluded() -> None:
    spec = RankingSpec(
        spec_id="strict-ranking",
        version="1.0.0",
        minimum_coverage_bps=9_000,
        features=(
            RankingFeatureSpec(
                key="required",
                label="Required",
                weight_bps=6_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
                missing_policy=MissingFeaturePolicy.EXCLUDE,
            ),
            RankingFeatureSpec(
                key="optional",
                label="Optional",
                weight_bps=4_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
            ),
        ),
    )
    instrument = _instrument(
        "600519.SH",
        "Alpha",
        "Consumer",
        (
            FeatureObservation(
                feature_key="required",
                value=None,
                missing_reason="UPSTREAM_VALUE_MISSING",
            ),
            _observation("optional", "1"),
        ),
    )

    row = rank_instruments(
        spec=spec,
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(instrument,),
    ).rows[0]

    assert row.status is RankingRowStatus.EXCLUDED
    assert row.rank is None
    assert row.score_bps is None
    assert row.exclusion_reasons == (
        "MISSING_REQUIRED_FEATURE:required",
        "COVERAGE_BELOW_MINIMUM",
    )


def test_filtering_preserves_global_rank_and_can_include_exclusions() -> None:
    snapshot = rank_instruments(
        spec=_spec(minimum_coverage_bps=8_000),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=_inputs(),
    )

    consumer = filter_ranking_rows(
        snapshot,
        RankingFilter(query="600519", sectors=frozenset({"Consumer"})),
    )
    with_excluded = filter_ranking_rows(
        snapshot,
        RankingFilter(include_excluded=True),
    )

    assert len(consumer) == 1
    assert consumer[0].rank == 1
    assert [row.status for row in with_excluded] == [
        RankingRowStatus.INCLUDED,
        RankingRowStatus.INCLUDED,
        RankingRowStatus.EXCLUDED,
    ]


def test_input_contract_rejects_naive_time_and_invalid_weight_total() -> None:
    with pytest.raises(RankingInputError, match="timezone-aware"):
        rank_instruments(
            spec=_spec(),
            as_of=datetime(2026, 8, 26, 15, 0),
            generated_at=AS_OF,
            instruments=(),
        )

    with pytest.raises(RankingInputError, match="total 10000"):
        RankingSpec(
            spec_id="invalid",
            version="1.0.0",
            features=(
                RankingFeatureSpec(
                    key="only",
                    label="Only",
                    weight_bps=9_999,
                    direction=RankingDirection.HIGHER_IS_BETTER,
                ),
            ),
        )


def test_future_candidates_do_not_change_point_in_time_snapshot_identity() -> None:
    def candidate(value: str) -> InstrumentFeatureSnapshot:
        return _instrument(
            "600519.SH",
            "Alpha",
            "Consumer",
            (
                _observation("momentum", value, offset_minutes=5),
                _observation("quality", "80"),
                _observation("risk", "10"),
            ),
        )

    first = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(candidate("99"),),
    )
    second = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=1),
        instruments=(candidate("88"),),
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.input_fingerprint == second.input_fingerprint
    assert first.rows == second.rows


def test_future_missing_observation_does_not_leak_evidence_time_or_source() -> None:
    instrument = _instrument(
        "600519.SH",
        "Alpha",
        "Consumer",
        (
            FeatureObservation(
                feature_key="momentum",
                value=None,
                available_time=AS_OF + timedelta(minutes=1),
                source="future-missing-marker",
                missing_reason="UPSTREAM_VALUE_MISSING",
            ),
            _observation("quality", "80"),
            _observation("risk", "10"),
        ),
    )

    row = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(instrument,),
    ).rows[0]
    momentum = next(item for item in row.contributions if item.feature_key == "momentum")

    assert momentum.missing_reason == "NOT_AVAILABLE_AT_SNAPSHOT"
    assert momentum.available_time is None
    assert momentum.source is None


def test_zero_coverage_is_excluded_even_when_spec_allows_zero_minimum() -> None:
    spec = RankingSpec(
        spec_id="zero-minimum",
        version="1.0.0",
        minimum_coverage_bps=0,
        features=(
            RankingFeatureSpec(
                key="only",
                label="Only",
                weight_bps=10_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
            ),
        ),
    )
    instrument = _instrument(
        "600519.SH",
        "Alpha",
        "Consumer",
        (
            FeatureObservation(
                feature_key="only",
                value=None,
                missing_reason="UPSTREAM_VALUE_MISSING",
            ),
        ),
    )

    row = rank_instruments(
        spec=spec,
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=(instrument,),
    ).rows[0]

    assert row.status is RankingRowStatus.EXCLUDED
    assert row.exclusion_reasons == ("NO_AVAILABLE_FEATURES",)
    assert row.rank is None
    assert row.score_bps is None


def test_lower_is_better_and_largest_remainder_are_deterministic() -> None:
    snapshot = rank_instruments(
        spec=_spec(),
        as_of=AS_OF,
        generated_at=AS_OF,
        instruments=_inputs(),
    )
    alpha = next(row for row in snapshot.rows if row.instrument_id == "600519.SH")
    beta = next(row for row in snapshot.rows if row.instrument_id == "000001.SZ")
    alpha_risk = next(item for item in alpha.contributions if item.feature_key == "risk")
    beta_risk = next(item for item in beta.contributions if item.feature_key == "risk")

    assert alpha_risk.normalized_score_bps == 10_000
    assert beta_risk.normalized_score_bps == 0
    assert sum(item.effective_weight_bps for item in beta.contributions) == 10_000
    assert beta.score_bps == sum(item.contribution_bps for item in beta.contributions)


def test_labels_and_declaration_order_are_part_of_snapshot_identity() -> None:
    first_feature = RankingFeatureSpec(
        key="first",
        label="Factor A",
        weight_bps=6_000,
        direction=RankingDirection.HIGHER_IS_BETTER,
    )
    second_feature = RankingFeatureSpec(
        key="second",
        label="Factor B",
        weight_bps=4_000,
        direction=RankingDirection.HIGHER_IS_BETTER,
    )
    base = RankingSpec(
        spec_id="identity",
        version="1.0.0",
        features=(first_feature, second_feature),
    )
    renamed = RankingSpec(
        spec_id="identity",
        version="1.0.0",
        features=(
            RankingFeatureSpec(
                key="first",
                label="Renamed Factor A",
                weight_bps=6_000,
                direction=RankingDirection.HIGHER_IS_BETTER,
            ),
            second_feature,
        ),
    )
    reordered = RankingSpec(
        spec_id="identity",
        version="1.0.0",
        features=(second_feature, first_feature),
    )

    snapshots = tuple(
        rank_instruments(
            spec=spec,
            as_of=AS_OF,
            generated_at=AS_OF,
            instruments=(),
        )
        for spec in (base, renamed, reordered)
    )

    assert len({spec.fingerprint for spec in (base, renamed, reordered)}) == 3
    assert len({snapshot.input_fingerprint for snapshot in snapshots}) == 3
    assert len({snapshot.snapshot_id for snapshot in snapshots}) == 3


def test_generated_time_cannot_precede_snapshot_time() -> None:
    with pytest.raises(RankingInputError, match="generated_at must not be earlier"):
        rank_instruments(
            spec=_spec(),
            as_of=AS_OF,
            generated_at=AS_OF - timedelta(seconds=1),
            instruments=(),
        )


def test_public_spec_boundary_rejects_unparsed_enums_and_non_integer_bps() -> None:
    with pytest.raises(RankingInputError, match="RankingDirection"):
        RankingFeatureSpec(
            key="direction",
            label="Direction",
            weight_bps=10_000,
            direction=cast(RankingDirection, "LOWER_IS_BETTER"),
        )
    with pytest.raises(RankingInputError, match="MissingFeaturePolicy"):
        RankingFeatureSpec(
            key="policy",
            label="Policy",
            weight_bps=10_000,
            direction=RankingDirection.HIGHER_IS_BETTER,
            missing_policy=cast(MissingFeaturePolicy, "ZERO"),
        )
    for invalid_weight in (cast(int, 10_000.0), True):
        with pytest.raises(RankingInputError, match="weight_bps must be an integer"):
            RankingFeatureSpec(
                key="weight",
                label="Weight",
                weight_bps=invalid_weight,
                direction=RankingDirection.HIGHER_IS_BETTER,
            )
    with pytest.raises(RankingInputError, match="minimum_coverage_bps must be an integer"):
        RankingSpec(
            spec_id="coverage",
            version="1.0.0",
            minimum_coverage_bps=cast(int, 5_000.0),
            features=(
                RankingFeatureSpec(
                    key="only",
                    label="Only",
                    weight_bps=10_000,
                    direction=RankingDirection.HIGHER_IS_BETTER,
                ),
            ),
        )
    with pytest.raises(RankingInputError, match="requires a reason"):
        FeatureObservation(feature_key="missing", value=None, missing_reason="   ")

    with pytest.raises(RankingInputError, match="generated_at must not be earlier"):
        RankingSnapshot(
            snapshot_id="invalid-time-order",
            as_of=AS_OF,
            generated_at=AS_OF - timedelta(seconds=1),
            spec=_spec(),
            input_fingerprint="invalid-time-order",
            rows=(),
        )


def _acceptance_spec() -> RankingSpec:
    return RankingSpec(
        spec_id="cn-equity-intelligence",
        version="1.0.0",
        minimum_coverage_bps=5_000,
        features=(
            RankingFeatureSpec("momentum", "趋势强度", 4_000, RankingDirection.HIGHER_IS_BETTER),
            RankingFeatureSpec("sentiment", "市场情绪", 2_500, RankingDirection.HIGHER_IS_BETTER),
            RankingFeatureSpec("quality", "质量因子", 2_000, RankingDirection.HIGHER_IS_BETTER),
            RankingFeatureSpec(
                "risk",
                "风险韧性",
                1_500,
                RankingDirection.LOWER_IS_BETTER,
                MissingFeaturePolicy.ZERO,
            ),
        ),
    )


def _acceptance_inputs() -> tuple[InstrumentFeatureSnapshot, ...]:
    def observations(
        momentum: str,
        sentiment: str | None,
        quality: str | None,
        risk: str | None,
    ) -> tuple[FeatureObservation, ...]:
        values = (
            ("momentum", momentum),
            ("sentiment", sentiment),
            ("quality", quality),
            ("risk", risk),
        )
        return tuple(
            _observation(key, value)
            if value is not None
            else FeatureObservation(
                feature_key=key,
                value=None,
                missing_reason=(
                    "NOT_AVAILABLE_AT_SNAPSHOT"
                    if key == "sentiment" and momentum == "0.51"
                    else "UPSTREAM_VALUE_MISSING"
                ),
            )
            for key, value in values
        )

    return (
        _instrument(
            "600519.SH",
            "贵州茅台",
            "食品饮料",
            observations("0.82", "0.78", "0.74", "0.31"),
        ),
        _instrument(
            "300750.SZ",
            "宁德时代",
            "电力设备",
            observations("0.76", "0.69", None, "0.38"),
        ),
        _instrument(
            "601318.SH",
            "中国平安",
            "非银金融",
            observations("0.64", "0.61", "0.81", None),
        ),
        _instrument(
            "000001.SZ",
            "平安银行",
            "银行",
            observations("0.51", None, "0.69", "0.35"),
        ),
        _instrument(
            "688981.SH",
            "中芯国际",
            "电子",
            observations("0.58", None, None, None),
        ),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _acceptance_payload() -> dict[str, object]:
    snapshot = rank_instruments(
        spec=_acceptance_spec(),
        as_of=AS_OF,
        generated_at=AS_OF + timedelta(minutes=1),
        instruments=_acceptance_inputs(),
    )
    return {
        "snapshotId": snapshot.snapshot_id,
        "inputFingerprint": snapshot.input_fingerprint,
        "asOf": _iso(snapshot.as_of),
        "generatedAt": _iso(snapshot.generated_at),
        "sourceMode": "SANITIZED_ACCEPTANCE_FIXTURE",
        "spec": {
            "specId": snapshot.spec.spec_id,
            "version": snapshot.spec.version,
            "algorithmVersion": snapshot.spec.algorithm_version,
            "fingerprint": snapshot.spec.fingerprint,
            "minimumCoverageBps": snapshot.spec.minimum_coverage_bps,
            "features": [
                {
                    "key": feature.key,
                    "label": feature.label,
                    "weightBps": feature.weight_bps,
                    "direction": feature.direction.value,
                    "missingPolicy": feature.missing_policy.value,
                }
                for feature in snapshot.spec.features
            ],
        },
        "rows": [
            {
                "instrumentId": row.instrument_id,
                "instrumentName": row.instrument_name,
                "sector": row.sector,
                "status": row.status.value,
                "rank": row.rank,
                "scoreBps": row.score_bps,
                "coverageBps": row.coverage_bps,
                "contributions": [
                    {
                        "featureKey": item.feature_key,
                        "label": item.label,
                        "direction": item.direction.value,
                        "rawValue": (
                            format(item.raw_value, "f") if item.raw_value is not None else None
                        ),
                        "normalizedScoreBps": item.normalized_score_bps,
                        "configuredWeightBps": item.configured_weight_bps,
                        "effectiveWeightBps": item.effective_weight_bps,
                        "contributionBps": item.contribution_bps,
                        "missingReason": item.missing_reason,
                        "availableTime": (
                            _iso(item.available_time) if item.available_time is not None else None
                        ),
                        "source": item.source,
                    }
                    for item in row.contributions
                ],
                "exclusionReasons": list(row.exclusion_reasons),
            }
            for row in snapshot.rows
        ],
    }


def _acceptance_fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[5]
        / "apps/web/src/features/ranking/ranking-acceptance-snapshot.json"
    )


def test_web_acceptance_fixture_matches_core_output_exactly() -> None:
    fixture: object = json.loads(_acceptance_fixture_path().read_text(encoding="utf-8"))
    assert fixture == _acceptance_payload()


if __name__ == "__main__":
    _acceptance_fixture_path().write_text(
        json.dumps(_acceptance_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
