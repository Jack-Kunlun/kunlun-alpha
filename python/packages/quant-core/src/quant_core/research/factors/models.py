from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import cast

FACTOR_RESEARCH_ALGORITHM_VERSION = "factor-research-v1"

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class FactorResearchInputError(ValueError):
    pass


class FactorFutureDataError(FactorResearchInputError):
    pass


class FactorResearchStatus(StrEnum):
    OK = "OK"
    NO_VALID_SAMPLES = "NO_VALID_SAMPLES"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    CONSTANT_INPUT = "CONSTANT_INPUT"


class CorrelationStatus(StrEnum):
    OK = "OK"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    CONSTANT_INPUT = "CONSTANT_INPUT"


class InferenceAssumption(StrEnum):
    IID_DESCRIPTIVE_UNADJUSTED = "IID_DESCRIPTIVE_UNADJUSTED"


class SampleDropReason(StrEnum):
    MISSING_FACTOR = "MISSING_FACTOR"
    MISSING_RETURN = "MISSING_RETURN"
    OUTCOME_NOT_AVAILABLE = "OUTCOME_NOT_AVAILABLE"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise FactorResearchInputError(f"{field} must be a non-empty string")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise FactorResearchInputError(f"{field} must be timezone-aware")
    return value


def _decimal(value: Decimal | None, field: str) -> Decimal | None:
    if value is not None and (type(value) is not Decimal or not value.is_finite()):
        raise FactorResearchInputError(f"{field} must be a finite Decimal or None")
    return value


@dataclass(frozen=True, slots=True)
class ForwardReturn:
    horizon_sessions: int
    outcome_time: datetime
    available_time: datetime
    value: Decimal | None

    def __post_init__(self) -> None:
        if type(self.horizon_sessions) is not int or self.horizon_sessions <= 0:
            raise FactorResearchInputError("horizon_sessions must be positive")
        _aware(self.outcome_time, "outcome_time")
        _aware(self.available_time, "return available_time")
        if self.available_time < self.outcome_time:
            raise FactorResearchInputError("return available_time cannot precede outcome_time")
        _decimal(self.value, "forward return")


@dataclass(frozen=True, slots=True)
class FactorObservation:
    factor_name: str
    factor_version: str
    entity_id: str
    decision_time: datetime
    factor_available_time: datetime
    factor_value: Decimal | None
    forward_returns: tuple[ForwardReturn, ...]

    def __post_init__(self) -> None:
        _text(self.factor_name, "factor_name")
        if _VERSION.fullmatch(self.factor_version) is None:
            raise FactorResearchInputError("factor_version must be semantic x.y.z")
        _text(self.entity_id, "entity_id")
        _aware(self.decision_time, "decision_time")
        _aware(self.factor_available_time, "factor_available_time")
        if self.factor_available_time > self.decision_time:
            raise FactorFutureDataError("factor is unavailable at decision_time")
        _decimal(self.factor_value, "factor_value")
        returns = tuple(self.forward_returns)
        if any(type(cast(object, item)) is not ForwardReturn for item in returns):
            raise FactorResearchInputError("forward return type is invalid")
        if len({item.horizon_sessions for item in returns}) != len(returns):
            raise FactorResearchInputError("forward return horizons must be unique")
        if any(item.outcome_time <= self.decision_time for item in returns):
            raise FactorFutureDataError("forward return must follow decision_time")
        object.__setattr__(
            self,
            "forward_returns",
            tuple(sorted(returns, key=lambda item: item.horizon_sessions)),
        )

    @property
    def factor_identity(self) -> tuple[str, str]:
        return (self.factor_name, self.factor_version)


@dataclass(frozen=True, slots=True)
class WinsorizationPolicy:
    lower_quantile: Decimal
    upper_quantile: Decimal

    def __post_init__(self) -> None:
        _decimal(self.lower_quantile, "lower_quantile")
        _decimal(self.upper_quantile, "upper_quantile")
        if not Decimal(0) <= self.lower_quantile < self.upper_quantile <= Decimal(1):
            raise FactorResearchInputError(
                "winsorization quantiles must satisfy 0 <= low < high <= 1"
            )


@dataclass(frozen=True, slots=True)
class SignTestResult:
    positive_count: int
    negative_count: int
    zero_count: int
    two_sided_p_value: Decimal | None


@dataclass(frozen=True, slots=True)
class MetricSummary:
    sample_count: int
    mean: Decimal | None
    median: Decimal | None
    standard_error: Decimal | None
    sign_test: SignTestResult
    inference_assumption: InferenceAssumption


@dataclass(frozen=True, slots=True)
class CorrelationPoint:
    decision_time: datetime
    horizon_sessions: int
    sample_count: int
    status: CorrelationStatus
    ic: Decimal | None
    rank_ic: Decimal | None


@dataclass(frozen=True, slots=True)
class DecayResult:
    horizon_sessions: int
    valid_pair_count: int
    period_count: int
    ic: MetricSummary
    rank_ic: MetricSummary


@dataclass(frozen=True, slots=True)
class StratumPeriodReturn:
    decision_time: datetime
    stratum: int
    constituent_count: int
    entity_ids: tuple[str, ...]
    return_value: Decimal


@dataclass(frozen=True, slots=True)
class StratumResult:
    stratum: int
    sample_count: int
    period_count: int
    return_summary: MetricSummary
    period_returns: tuple[StratumPeriodReturn, ...]


@dataclass(frozen=True, slots=True)
class TurnoverPolicy:
    expected_interval: timedelta
    tolerance: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.expected_interval <= timedelta(0):
            raise FactorResearchInputError("expected_interval must be positive")
        if self.tolerance < timedelta(0):
            raise FactorResearchInputError("turnover tolerance cannot be negative")

    def is_adjacent(self, previous: datetime, current: datetime) -> bool:
        actual_interval = current - previous
        return abs(actual_interval - self.expected_interval) <= self.tolerance


@dataclass(frozen=True, slots=True)
class TurnoverResult:
    stratum: int
    transition_count: int
    excluded_transition_count: int
    turnover_summary: MetricSummary


@dataclass(frozen=True, slots=True)
class ChartPoint:
    series: str
    x: str
    value: Decimal
    sample_count: int


@dataclass(frozen=True, slots=True)
class FactorResearchResult:
    factor_name: str
    factor_version: str
    algorithm_version: str
    data_cutoff_time: datetime
    status: FactorResearchStatus
    input_observation_count: int
    valid_pair_count: int
    primary_valid_pair_count: int
    valid_period_count: int
    primary_horizon_sessions: int | None
    ic: MetricSummary
    rank_ic: MetricSummary
    correlation_points: tuple[CorrelationPoint, ...]
    decay: tuple[DecayResult, ...]
    strata: tuple[StratumResult, ...]
    turnover: tuple[TurnoverResult, ...]
    turnover_policy: TurnoverPolicy | None
    drop_counts: tuple[tuple[SampleDropReason, int], ...]
    winsorization: WinsorizationPolicy | None
    chart_data: tuple[ChartPoint, ...]


@dataclass(frozen=True, slots=True)
class FactorCorrelationResult:
    left_factor_name: str
    left_factor_version: str
    right_factor_name: str
    right_factor_version: str
    algorithm_version: str
    data_cutoff_time: datetime
    aligned_sample_count: int
    valid_period_count: int
    correlation: MetricSummary
    rank_correlation: MetricSummary
    points: tuple[CorrelationPoint, ...]
    chart_data: tuple[ChartPoint, ...]
