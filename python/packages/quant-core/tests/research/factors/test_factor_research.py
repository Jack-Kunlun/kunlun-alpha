from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from quant_core.research.factors import (
    FACTOR_RESEARCH_ALGORITHM_VERSION,
    FactorFutureDataError,
    FactorObservation,
    FactorResearchInputError,
    FactorResearchStatus,
    ForwardReturn,
    InferenceAssumption,
    SampleDropReason,
    TurnoverPolicy,
    WinsorizationPolicy,
    analyze_factor,
    analyze_factor_correlation,
)

BASE = datetime(2026, 1, 1, 7, tzinfo=UTC)
CUTOFF = BASE + timedelta(days=120)
REBALANCE_POLICY = TurnoverPolicy(expected_interval=timedelta(days=30))


def _observation(
    *,
    entity_index: int,
    period: int,
    factor_value: Decimal | None,
    primary_return: Decimal | None,
    long_return: Decimal | None = None,
    factor_name: str = "quality",
    factor_version: str = "1.0.0",
    primary_available: datetime | None = None,
) -> FactorObservation:
    decision_time = BASE + timedelta(days=period * 30)
    primary_outcome = decision_time + timedelta(days=5)
    long_outcome = decision_time + timedelta(days=20)
    return FactorObservation(
        factor_name=factor_name,
        factor_version=factor_version,
        entity_id=f"{600000 + entity_index}.SH",
        decision_time=decision_time,
        factor_available_time=decision_time,
        factor_value=factor_value,
        forward_returns=(
            ForwardReturn(
                horizon_sessions=5,
                outcome_time=primary_outcome,
                available_time=primary_available or primary_outcome,
                value=primary_return,
            ),
            ForwardReturn(
                horizon_sessions=20,
                outcome_time=long_outcome,
                available_time=long_outcome,
                value=long_return if long_return is not None else primary_return,
            ),
        ),
    )


def _linear_observations(*, factor_name: str = "quality") -> tuple[FactorObservation, ...]:
    return tuple(
        _observation(
            entity_index=entity,
            period=period,
            factor_value=Decimal(entity),
            primary_return=Decimal(entity) / Decimal(100),
            long_return=Decimal(entity) / Decimal(200),
            factor_name=factor_name,
        )
        for period in range(3)
        for entity in range(1, 6)
    )


def test_factor_analysis_reports_strata_ic_decay_turnover_and_uncertainty() -> None:
    result = analyze_factor(
        _linear_observations(),
        data_cutoff_time=CUTOFF,
        bucket_count=3,
        turnover_policy=REBALANCE_POLICY,
    )

    assert result.status is FactorResearchStatus.OK
    assert result.algorithm_version == FACTOR_RESEARCH_ALGORITHM_VERSION
    assert result.data_cutoff_time == CUTOFF
    assert result.input_observation_count == 15
    assert result.valid_pair_count == 30
    assert result.valid_period_count == 3
    assert result.ic.mean == Decimal(1)
    assert result.rank_ic.mean == Decimal(1)
    assert result.ic.sign_test.two_sided_p_value == Decimal("0.25")
    assert [item.horizon_sessions for item in result.decay] == [5, 20]
    assert [item.return_summary.mean for item in result.strata] == [
        Decimal("0.015"),
        Decimal("0.035"),
        Decimal("0.05"),
    ]
    assert result.primary_valid_pair_count == 15
    assert all(
        summary.inference_assumption is InferenceAssumption.IID_DESCRIPTIVE_UNADJUSTED
        for summary in (result.ic, result.rank_ic)
    )
    assert all(item.excluded_transition_count == 0 for item in result.turnover)
    assert result.turnover_policy == REBALANCE_POLICY
    assert all(item.turnover_summary.mean == 0 for item in result.turnover)
    assert all(item.turnover_summary.standard_error == 0 for item in result.turnover)
    assert all(
        item.turnover_summary.inference_assumption is InferenceAssumption.IID_DESCRIPTIVE_UNADJUSTED
        for item in result.turnover
    )
    assert {point.series for point in result.chart_data} == {
        "ic",
        "rank_ic",
        "stratum_return",
    }


def test_missing_and_unavailable_outcomes_are_counted_not_silently_used() -> None:
    observations = (
        _observation(
            entity_index=1,
            period=0,
            factor_value=None,
            primary_return=Decimal("0.01"),
        ),
        _observation(
            entity_index=2,
            period=0,
            factor_value=Decimal(2),
            primary_return=None,
        ),
        _observation(
            entity_index=3,
            period=0,
            factor_value=Decimal(3),
            primary_return=Decimal("0.03"),
            primary_available=CUTOFF + timedelta(days=1),
        ),
    )

    result = analyze_factor(observations, data_cutoff_time=CUTOFF)
    drops = dict(result.drop_counts)

    assert drops[SampleDropReason.MISSING_FACTOR] == 2
    assert drops[SampleDropReason.MISSING_RETURN] == 2
    assert drops[SampleDropReason.OUTCOME_NOT_AVAILABLE] == 1
    assert result.valid_pair_count == 1
    assert result.status is FactorResearchStatus.INSUFFICIENT_SAMPLE


def test_constant_and_small_samples_have_explicit_status() -> None:
    constant = tuple(
        _observation(
            entity_index=index,
            period=0,
            factor_value=Decimal(1),
            primary_return=Decimal(index),
        )
        for index in range(1, 5)
    )
    constant_result = analyze_factor(constant, data_cutoff_time=CUTOFF)
    assert constant_result.status is FactorResearchStatus.CONSTANT_INPUT
    assert constant_result.ic.mean is None
    assert constant_result.strata == ()

    small_result = analyze_factor(constant[:2], data_cutoff_time=CUTOFF)
    assert small_result.status is FactorResearchStatus.INSUFFICIENT_SAMPLE
    assert small_result.valid_period_count == 0


def test_winsorization_bounds_outliers_and_is_part_of_result_provenance() -> None:
    values = (Decimal(1), Decimal(2), Decimal(3), Decimal(4), Decimal(1000))
    observations = tuple(
        _observation(
            entity_index=index + 1,
            period=0,
            factor_value=value,
            primary_return=Decimal(index + 1),
        )
        for index, value in enumerate(values)
    )
    policy = WinsorizationPolicy(Decimal("0.2"), Decimal("0.8"))

    raw = analyze_factor(observations, data_cutoff_time=CUTOFF)
    bounded = analyze_factor(
        observations,
        data_cutoff_time=CUTOFF,
        winsorization=policy,
    )

    assert bounded.winsorization == policy
    assert bounded.ic.mean is not None and raw.ic.mean is not None
    assert bounded.ic.mean > raw.ic.mean


def test_factor_correlation_aligns_cross_sections_and_reports_sample_size() -> None:
    left = _linear_observations(factor_name="quality")
    right = tuple(
        replace(
            item,
            factor_name="value",
            factor_value=-item.factor_value if item.factor_value is not None else None,
        )
        for item in left
    )

    result = analyze_factor_correlation(left, right, data_cutoff_time=CUTOFF)

    assert result.aligned_sample_count == 15
    assert result.valid_period_count == 3
    assert result.correlation.mean == Decimal(-1)
    assert result.rank_correlation.mean == Decimal(-1)
    assert len(result.chart_data) == 6
    assert {point.series for point in result.chart_data} == {
        "factor_correlation",
        "factor_rank_correlation",
    }


def test_stratum_returns_equal_weight_periods_before_summarizing() -> None:
    observations = tuple(
        replace(
            item,
            forward_returns=tuple(
                replace(
                    outcome,
                    value=(Decimal(0) if item.decision_time == BASE else Decimal(1))
                    + (item.factor_value or Decimal(0)) / Decimal(100),
                )
                for outcome in item.forward_returns
            ),
        )
        for item in _linear_observations()
        if item.decision_time in {BASE, BASE + timedelta(days=30)}
        and (item.decision_time != BASE or item.entity_id in {"600001.SH", "600002.SH"})
    )

    result = analyze_factor(observations, data_cutoff_time=CUTOFF, bucket_count=2)

    assert [item.return_summary.mean for item in result.strata] == [
        Decimal("0.515"),
        Decimal("0.5325"),
    ]
    assert [point.constituent_count for point in result.strata[0].period_returns] == [
        1,
        3,
    ]
    assert result.strata[0].sample_count == 4
    assert result.strata[0].period_count == 2


def test_tied_factor_values_remain_in_the_same_stratum() -> None:
    observations = tuple(
        _observation(
            entity_index=index,
            period=0,
            factor_value=value,
            primary_return=Decimal(index) / Decimal(100),
        )
        for index, value in enumerate((Decimal(1), Decimal(1), Decimal(2), Decimal(3)), start=1)
    )

    result = analyze_factor(observations, data_cutoff_time=CUTOFF, bucket_count=3)

    tied_entities = {"600001.SH", "600002.SH"}
    tied_memberships = [
        set(period.entity_ids)
        for stratum in result.strata
        for period in stratum.period_returns
        if tied_entities.intersection(period.entity_ids)
    ]
    assert tied_memberships == [tied_entities]
    assert result.rank_ic.mean is not None


def test_constant_period_breaks_turnover_chain_without_bridging_dates() -> None:
    interrupted_time = BASE + timedelta(days=30)
    observations = tuple(
        replace(item, factor_value=Decimal(1)) if item.decision_time == interrupted_time else item
        for item in _linear_observations()
    )

    result = analyze_factor(
        observations,
        data_cutoff_time=CUTOFF,
        bucket_count=3,
        turnover_policy=REBALANCE_POLICY,
    )

    assert all(item.transition_count == 0 for item in result.turnover)
    assert all(item.excluded_transition_count == 2 for item in result.turnover)
    assert all(item.turnover_summary.mean is None for item in result.turnover)


def test_missing_rebalance_date_is_excluded_from_turnover() -> None:
    missing_time = BASE + timedelta(days=30)
    observations = tuple(
        item for item in _linear_observations() if item.decision_time != missing_time
    )

    result = analyze_factor(
        observations,
        data_cutoff_time=CUTOFF,
        bucket_count=3,
        turnover_policy=REBALANCE_POLICY,
    )

    assert all(item.transition_count == 0 for item in result.turnover)
    assert all(item.excluded_transition_count == 1 for item in result.turnover)
    assert all(item.turnover_summary.sample_count == 0 for item in result.turnover)
    assert all(item.turnover_summary.mean is None for item in result.turnover)


def test_factor_and_return_time_boundaries_fail_closed() -> None:
    observation = _observation(
        entity_index=1,
        period=0,
        factor_value=Decimal(1),
        primary_return=Decimal("0.01"),
    )

    with pytest.raises(FactorFutureDataError, match="unavailable"):
        replace(
            observation,
            factor_available_time=observation.decision_time + timedelta(seconds=1),
        )
    with pytest.raises(FactorFutureDataError, match="must follow"):
        replace(
            observation,
            forward_returns=(
                replace(
                    observation.forward_returns[0],
                    outcome_time=observation.decision_time,
                    available_time=observation.decision_time,
                ),
            ),
        )
    with pytest.raises(FactorFutureDataError, match="data_cutoff_time"):
        analyze_factor(
            (observation,),
            data_cutoff_time=observation.decision_time - timedelta(seconds=1),
        )
    with pytest.raises(FactorResearchInputError, match="unique"):
        analyze_factor(
            (observation, observation),
            data_cutoff_time=CUTOFF,
        )
