"""Deterministic Decimal performance metrics."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, localcontext

from .models import (
    MetricsPolicy,
    MetricStatus,
    MetricsValidationError,
    NavObservation,
    PerformanceMetrics,
    RiskFreeObservation,
    canonical_digest,
)

DECIMAL_PRECISION = 60


def _validate_nav_path(observations: tuple[NavObservation, ...]) -> None:
    if type(observations) is not tuple:
        raise MetricsValidationError("NAV observations must be an exact tuple")
    for item in observations:
        if type(item) is not NavObservation:
            raise MetricsValidationError("NAV path contains a wrong nominal type")
        item.__post_init__()
    times = tuple(item.observation_time for item in observations)
    if times != tuple(sorted(times)) or len(times) != len(set(times)):
        raise MetricsValidationError("NAV observations must be canonical and unique by time")
    dates = tuple(item.observation_time.date() for item in observations)
    if len(dates) != len(set(dates)):
        raise MetricsValidationError("DAILY NAV observations must have unique dates")


def _validate_risk_free_path(observations: tuple[RiskFreeObservation, ...]) -> None:
    if type(observations) is not tuple:
        raise MetricsValidationError("risk-free observations must be an exact tuple")
    for item in observations:
        if type(item) is not RiskFreeObservation:
            raise MetricsValidationError("risk-free path contains a wrong nominal type")
        item.__post_init__()
    times = tuple(item.observation_time for item in observations)
    if times != tuple(sorted(times)) or len(times) != len(set(times)):
        raise MetricsValidationError("risk-free observations must be canonical and unique by time")
    dates = tuple(item.observation_time.date() for item in observations)
    if len(dates) != len(set(dates)):
        raise MetricsValidationError("DAILY risk-free observations must have unique dates")


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _sample_standard_deviation(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    average = _mean(values)
    variance = sum(((value - average) ** 2 for value in values), Decimal("0")) / Decimal(
        len(values) - 1
    )
    return variance.sqrt()


def _wealth_drawdown(returns: tuple[Decimal, ...]) -> Decimal:
    wealth = Decimal("1")
    peak = wealth
    maximum = Decimal("0")
    for result in returns:
        wealth *= Decimal("1") + result
        if wealth > peak:
            peak = wealth
        drawdown = Decimal("1") - wealth / peak
        if drawdown > maximum:
            maximum = drawdown
    return maximum


def _unavailable(status: MetricStatus) -> tuple[None, MetricStatus]:
    return None, status


def _empty_metrics(
    risk_free_observations: tuple[RiskFreeObservation, ...], policy: MetricsPolicy
) -> PerformanceMetrics:
    unavailable = MetricStatus.INSUFFICIENT_SAMPLES
    input_digest = canonical_digest(((), risk_free_observations, policy.policy_digest))
    return PerformanceMetrics(
        schema_version=policy.schema_version,
        algorithm_version=policy.algorithm_version,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        frequency=policy.frequency,
        periods_per_year=policy.periods_per_year,
        nav_count=0,
        return_count=0,
        risk_free_count=len(risk_free_observations),
        cutoff_time=policy_cutoff(policy),
        canonical_input_digest=input_digest,
        period_returns=(),
        cumulative_chained_return=None,
        cumulative_chained_return_status=unavailable,
        annualized_return=None,
        annualized_return_status=unavailable,
        annualized_volatility=None,
        annualized_volatility_status=unavailable,
        maximum_drawdown=None,
        maximum_drawdown_status=unavailable,
        sharpe=None,
        sharpe_status=unavailable,
        sortino=None,
        sortino_status=unavailable,
        calmar=None,
        calmar_status=unavailable,
    )


def calculate_performance_metrics(
    nav_observations: tuple[NavObservation, ...],
    risk_free_observations: tuple[RiskFreeObservation, ...],
    policy: MetricsPolicy,
) -> PerformanceMetrics:
    """Calculate chained returns and risk metrics with a fixed Decimal context."""

    if type(policy) is not MetricsPolicy:
        raise MetricsValidationError("policy must be MetricsPolicy")
    policy.validate_integrity()
    _validate_nav_path(nav_observations)
    _validate_risk_free_path(risk_free_observations)
    if not nav_observations:
        return _empty_metrics(risk_free_observations, policy)
    cutoff = nav_observations[-1].observation_time
    for item in nav_observations:
        if item.available_time > cutoff:
            raise MetricsValidationError("NAV path contains future availability")
    for item in risk_free_observations:
        if item.available_time > cutoff:
            raise MetricsValidationError("risk-free path contains future availability")

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        returns = tuple(
            current.nav / previous.nav - Decimal("1")
            for previous, current in zip(nav_observations[:-1], nav_observations[1:], strict=True)
        )
        nav_count = len(nav_observations)
        return_count = len(returns)
        cumulative: Decimal | None
        cumulative_status: MetricStatus
        annualized: Decimal | None
        annualized_status: MetricStatus
        volatility: Decimal | None
        volatility_status: MetricStatus
        drawdown: Decimal | None
        drawdown_status: MetricStatus
        if nav_count < 2:
            cumulative, cumulative_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
            annualized, annualized_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
            volatility, volatility_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
            drawdown, drawdown_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
        else:
            cumulative = nav_observations[-1].nav / nav_observations[0].nav - Decimal("1")
            cumulative_status = MetricStatus.AVAILABLE
            annualized = _annualized_return(cumulative, return_count, policy.periods_per_year)
            annualized_status = MetricStatus.AVAILABLE
            standard_deviation = _sample_standard_deviation(returns)
            if standard_deviation is None:
                volatility, volatility_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
            else:
                volatility = standard_deviation * Decimal(policy.periods_per_year).sqrt()
                volatility_status = MetricStatus.AVAILABLE
            drawdown = _wealth_drawdown(returns)
            drawdown_status = MetricStatus.AVAILABLE

        rf_status: MetricStatus | None = None
        aligned_excess: tuple[Decimal, ...] = ()
        if not risk_free_observations:
            rf_status = MetricStatus.MISSING_RISK_FREE
        elif len(risk_free_observations) != nav_count or tuple(
            item.observation_time for item in risk_free_observations
        ) != tuple(item.observation_time for item in nav_observations):
            rf_status = MetricStatus.MISALIGNED_RISK_FREE
        else:
            aligned_excess = tuple(
                current - risk_free.rate
                for current, risk_free in zip(returns, risk_free_observations[1:], strict=True)
            )

        sharpe: Decimal | None
        sharpe_status: MetricStatus
        sortino: Decimal | None
        sortino_status: MetricStatus
        if rf_status is not None:
            sharpe, sharpe_status = _unavailable(rf_status)
            sortino, sortino_status = _unavailable(rf_status)
        elif len(aligned_excess) < 2:
            sharpe, sharpe_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
            sortino, sortino_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
        else:
            excess_deviation = _sample_standard_deviation(aligned_excess)
            if excess_deviation is None or excess_deviation == 0:
                sharpe, sharpe_status = _unavailable(MetricStatus.ZERO_EXCESS_VOLATILITY)
            else:
                sharpe = (
                    _mean(aligned_excess)
                    / excess_deviation
                    * Decimal(policy.periods_per_year).sqrt()
                )
                sharpe_status = MetricStatus.AVAILABLE
            downside_square_sum = sum(
                (value * value for value in aligned_excess if value < 0), Decimal("0")
            )
            if downside_square_sum == 0:
                sortino, sortino_status = _unavailable(MetricStatus.NO_DOWNSIDE_DEVIATION)
            else:
                downside_deviation = (downside_square_sum / Decimal(len(aligned_excess))).sqrt()
                sortino = (
                    _mean(aligned_excess)
                    / downside_deviation
                    * Decimal(policy.periods_per_year).sqrt()
                )
                sortino_status = MetricStatus.AVAILABLE

        if annualized is None or drawdown is None:
            calmar, calmar_status = _unavailable(MetricStatus.INSUFFICIENT_SAMPLES)
        elif drawdown == 0:
            calmar, calmar_status = _unavailable(MetricStatus.ZERO_DRAWDOWN)
        else:
            calmar = annualized / drawdown
            calmar_status = MetricStatus.AVAILABLE

        input_digest = canonical_digest(
            (nav_observations, risk_free_observations, policy.policy_digest)
        )
        return PerformanceMetrics(
            schema_version=policy.schema_version,
            algorithm_version=policy.algorithm_version,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            frequency=policy.frequency,
            periods_per_year=policy.periods_per_year,
            nav_count=nav_count,
            return_count=return_count,
            risk_free_count=len(risk_free_observations),
            cutoff_time=cutoff,
            canonical_input_digest=input_digest,
            period_returns=returns,
            cumulative_chained_return=cumulative,
            cumulative_chained_return_status=cumulative_status,
            annualized_return=annualized,
            annualized_return_status=annualized_status,
            annualized_volatility=volatility,
            annualized_volatility_status=volatility_status,
            maximum_drawdown=drawdown,
            maximum_drawdown_status=drawdown_status,
            sharpe=sharpe,
            sharpe_status=sharpe_status,
            sortino=sortino,
            sortino_status=sortino_status,
            calmar=calmar,
            calmar_status=calmar_status,
        )


def _annualized_return(cumulative: Decimal, periods: int, periods_per_year: int) -> Decimal:
    if periods <= 0:
        raise MetricsValidationError("annualized return requires a positive return count")
    wealth = Decimal("1") + cumulative
    return (wealth.ln() * (Decimal(periods_per_year) / Decimal(periods))).exp() - Decimal("1")


def policy_cutoff(policy: MetricsPolicy) -> datetime:
    del policy
    return datetime(1970, 1, 1, tzinfo=UTC)


def calculate_metrics(
    nav_observations: tuple[NavObservation, ...],
    risk_free_observations: tuple[RiskFreeObservation, ...],
    policy: MetricsPolicy,
) -> PerformanceMetrics:
    """Short alias for callers using the generic metrics term."""

    return calculate_performance_metrics(nav_observations, risk_free_observations, policy)


def verify_performance_metrics_against_inputs(
    candidate: PerformanceMetrics,
    nav_observations: tuple[NavObservation, ...],
    risk_free_observations: tuple[RiskFreeObservation, ...],
    policy: MetricsPolicy,
) -> PerformanceMetrics:
    """Verify a candidate result by recomputing it from the original inputs."""

    if type(candidate) is not PerformanceMetrics:
        raise MetricsValidationError("candidate must be PerformanceMetrics")
    candidate.validate_integrity()
    if type(policy) is not MetricsPolicy:
        raise MetricsValidationError("policy must be MetricsPolicy")
    policy.validate_integrity()
    _validate_nav_path(nav_observations)
    _validate_risk_free_path(risk_free_observations)
    expected = calculate_performance_metrics(nav_observations, risk_free_observations, policy)
    if candidate.result_digest != expected.result_digest or candidate != expected:
        raise MetricsValidationError("metrics result does not match the original inputs")
    return candidate


__all__ = [
    "calculate_metrics",
    "calculate_performance_metrics",
    "verify_performance_metrics_against_inputs",
]
