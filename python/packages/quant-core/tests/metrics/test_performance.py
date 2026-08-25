from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, getcontext, setcontext
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from quant_core.metrics import (
    MetricsPolicy,
    MetricStatus,
    MetricsValidationError,
    NavObservation,
    RiskFreeObservation,
    calculate_performance_metrics,
    verify_performance_metrics_against_inputs,
)

UTC = ZoneInfo("UTC")


def _nav(values: tuple[str, ...]) -> tuple[NavObservation, ...]:
    return tuple(
        NavObservation(
            observation_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            available_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            nav=Decimal(value),
        )
        for index, value in enumerate(values)
    )


def _rf(count: int) -> tuple[RiskFreeObservation, ...]:
    return tuple(
        RiskFreeObservation(
            observation_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            available_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index),
            rate=Decimal("0"),
        )
        for index in range(count)
    )


def test_decimal_metrics_are_deterministic_and_do_not_use_float() -> None:
    policy = MetricsPolicy(
        policy_id="metrics-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    result = calculate_performance_metrics(_nav(("100", "101", "100")), _rf(3), policy)
    assert result.period_returns[0] == Decimal("0.01")
    assert result.period_returns[1] == Decimal(
        "-0.009900990099009900990099009900990099009900990099009900990099"
    )
    assert result.cumulative_chained_return == Decimal("0")
    assert result.annualized_volatility is not None
    assert (
        result.canonical_input_digest
        == calculate_performance_metrics(
            _nav(("100", "101", "100")), _rf(3), policy
        ).canonical_input_digest
    )


def test_unavailable_statuses_are_explicit() -> None:
    policy = MetricsPolicy(
        policy_id="metrics-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    result = calculate_performance_metrics(_nav(("100",)), (), policy)
    assert result.annualized_return is None
    assert result.annualized_return_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.sharpe is None
    assert result.sharpe_status is MetricStatus.MISSING_RISK_FREE


def test_invalid_float_nav_and_noncanonical_order_are_rejected() -> None:
    with pytest.raises(ValueError, match="Decimal"):
        NavObservation(
            observation_time=datetime(2026, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 1, 1, tzinfo=UTC),
            nav=cast(Decimal, 100.0),
        )
    observations = _nav(("100", "101"))
    with pytest.raises(ValueError, match="canonical"):
        calculate_performance_metrics(
            tuple(reversed(observations)),
            _rf(2),
            MetricsPolicy(
                policy_id="metrics-policy",
                policy_version="1.0.0",
                frequency="DAILY",
                periods_per_year=252,
            ),
        )


def test_empty_nav_returns_insufficient_samples_for_valid_risk_free_input() -> None:
    policy = MetricsPolicy(
        policy_id="metrics-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    result = calculate_performance_metrics((), _rf(2), policy)
    assert result.nav_count == 0
    assert result.cumulative_chained_return_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.annualized_return_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.annualized_volatility_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.maximum_drawdown_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.sharpe_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.sortino_status is MetricStatus.INSUFFICIENT_SAMPLES
    assert result.calmar_status is MetricStatus.INSUFFICIENT_SAMPLES


@pytest.mark.parametrize(
    "risk_free_observations",
    (
        ("malformed",),
        (object(),),
    ),
)
def test_empty_nav_rejects_malformed_risk_free_records(
    risk_free_observations: tuple[object, ...],
) -> None:
    policy = MetricsPolicy("metrics-policy", "1.0.0", "DAILY", 252)
    with pytest.raises(MetricsValidationError):
        calculate_performance_metrics((), risk_free_observations, policy)  # type: ignore[arg-type]


def test_empty_nav_rejects_forged_duplicate_and_noncanonical_risk_free_records() -> None:
    policy = MetricsPolicy("metrics-policy", "1.0.0", "DAILY", 252)
    forged = _rf(1)[0]
    object.__setattr__(forged, "provenance_digest", "not-a-digest")
    with pytest.raises(MetricsValidationError):
        calculate_performance_metrics((), (forged,), policy)

    observations = _rf(2)
    with pytest.raises(MetricsValidationError, match="unique"):
        calculate_performance_metrics((), (observations[0], observations[0]), policy)
    with pytest.raises(MetricsValidationError, match="canonical"):
        calculate_performance_metrics((), tuple(reversed(observations)), policy)


def test_structural_metrics_result_digest_rejects_forged_mutation() -> None:
    policy = MetricsPolicy("metrics-policy", "1.0.0", "DAILY", 252)
    result = calculate_performance_metrics(_nav(("100", "101")), _rf(2), policy)
    object.__setattr__(result, "annualized_return", Decimal("0.5"))
    with pytest.raises(MetricsValidationError, match="result digest"):
        result.validate_integrity()


@pytest.mark.parametrize(
    "changes",
    (
        {"annualized_return": Decimal("0.5")},
        {"maximum_drawdown": Decimal("0.5")},
        {"sharpe": Decimal("1"), "sharpe_status": MetricStatus.AVAILABLE},
        {"sortino": Decimal("1"), "sortino_status": MetricStatus.AVAILABLE},
        {"calmar": Decimal("1"), "calmar_status": MetricStatus.AVAILABLE},
        {
            "nav_count": 3,
            "return_count": 2,
            "period_returns": (Decimal("0.01"), Decimal("0.02")),
        },
        {"policy_id": "other-policy"},
        {"policy_version": "2.0.0"},
        {"policy_digest": "a" * 64},
        {"canonical_input_digest": "b" * 64},
        {"algorithm_version": "2.0.0"},
    ),
)
def test_contextual_metrics_verification_rejects_structurally_valid_replacements(
    changes: dict[str, object],
) -> None:
    policy = MetricsPolicy("metrics-policy", "1.0.0", "DAILY", 252)
    nav = _nav(("100", "101"))
    risk_free = _rf(2)
    result = calculate_performance_metrics(nav, risk_free, policy)
    candidate = replace(result, **changes)
    candidate.validate_integrity()
    with pytest.raises(MetricsValidationError, match="inputs"):
        verify_performance_metrics_against_inputs(candidate, nav, risk_free, policy)


def test_contextual_metrics_verification_accepts_the_original_result() -> None:
    policy = MetricsPolicy("metrics-policy", "1.0.0", "DAILY", 252)
    nav = _nav(("100", "101"))
    risk_free = _rf(2)
    result = calculate_performance_metrics(nav, risk_free, policy)
    assert verify_performance_metrics_against_inputs(result, nav, risk_free, policy) == result


def test_reconstructed_metrics_reject_inconsistent_status_value_pair() -> None:
    policy = MetricsPolicy(
        policy_id="metrics-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    result = calculate_performance_metrics(_nav(("100", "101")), _rf(2), policy)
    with pytest.raises(ValueError, match="available metric"):
        replace(
            result,
            annualized_return=None,
            annualized_return_status=MetricStatus.AVAILABLE,
        )


def test_decimal_golden_vector_covers_return_volatility_drawdown_and_ratios() -> None:
    policy = MetricsPolicy(
        policy_id="golden-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=2,
    )
    result = calculate_performance_metrics(_nav(("100", "110", "99")), _rf(3), policy)
    assert result.period_returns == (Decimal("0.1"), Decimal("-0.1"))
    assert result.cumulative_chained_return == Decimal("-0.01")
    assert result.annualized_return == Decimal(
        "-0.010000000000000000000000000000000000000000000000000000000000"
    )
    assert result.annualized_volatility == Decimal(
        "0.200000000000000000000000000000000000000000000000000000000000"
    )
    assert result.maximum_drawdown == Decimal("0.1")
    assert result.sharpe == Decimal("0")
    assert result.sortino == Decimal("0")
    assert result.calmar == Decimal(
        "-0.10000000000000000000000000000000000000000000000000000000000000"
    )


def test_zero_volatility_no_downside_and_zero_drawdown_have_explicit_statuses() -> None:
    policy = MetricsPolicy(
        policy_id="edge-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    result = calculate_performance_metrics(_nav(("100", "100", "100")), _rf(3), policy)
    assert result.annualized_volatility == Decimal("0")
    assert result.sharpe is None
    assert result.sharpe_status is MetricStatus.ZERO_EXCESS_VOLATILITY
    assert result.sortino is None
    assert result.sortino_status is MetricStatus.NO_DOWNSIDE_DEVIATION
    assert result.maximum_drawdown == Decimal("0")
    assert result.calmar is None
    assert result.calmar_status is MetricStatus.ZERO_DRAWDOWN


def test_metrics_use_a_local_decimal_context_without_mutating_global_context() -> None:
    policy = MetricsPolicy(
        policy_id="context-policy",
        policy_version="1.0.0",
        frequency="DAILY",
        periods_per_year=252,
    )
    context = getcontext()
    before = context.copy()
    context.prec = 9
    expected_context = before.copy()
    expected_context.prec = 9
    try:
        result = calculate_performance_metrics(_nav(("100", "101", "100")), _rf(3), policy)
        assert result.annualized_volatility is not None
        assert context.prec == 9
        after = context.copy()
        assert after.prec == expected_context.prec
        assert after.rounding == expected_context.rounding
        assert after.Emin == expected_context.Emin
        assert after.Emax == expected_context.Emax
        assert after.traps == expected_context.traps
        assert after.flags == expected_context.flags
    finally:
        setcontext(before)
