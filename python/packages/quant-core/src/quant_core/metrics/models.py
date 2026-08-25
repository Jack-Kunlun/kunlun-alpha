"""Versioned Decimal-only performance metric contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol, cast, runtime_checkable

METRICS_SCHEMA_VERSION = "quant-metrics-v1"
METRICS_ALGORITHM_VERSION = "1.0.0"
ZERO_DIGEST = "0" * 64


class MetricsValidationError(ValueError):
    """Raised when a metrics input violates its deterministic path contract."""


class MetricStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"
    MISSING_RISK_FREE = "MISSING_RISK_FREE"
    MISALIGNED_RISK_FREE = "MISALIGNED_RISK_FREE"
    ZERO_EXCESS_VOLATILITY = "ZERO_EXCESS_VOLATILITY"
    NO_DOWNSIDE_DEVIATION = "NO_DOWNSIDE_DEVIATION"
    ZERO_DRAWDOWN = "ZERO_DRAWDOWN"
    MISSING_RISK_FREE_PATH = "MISSING_RISK_FREE"
    MISALIGNED_RISK_FREE_PATH = "MISALIGNED_RISK_FREE"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise MetricsValidationError(f"{field_name} must be a non-empty string")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise MetricsValidationError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise MetricsValidationError(f"{field_name} must be a finite Decimal")
    if positive and value <= 0:
        raise MetricsValidationError(f"{field_name} must be positive")
    return value


def _digest(value: object, field_name: str, *, allow_zero: bool = False) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise MetricsValidationError(f"{field_name} must be a lowercase hex digest")
    if not allow_zero and value == ZERO_DIGEST:
        raise MetricsValidationError(f"{field_name} must not be empty")
    return value


def _tuple(value: object, field_name: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        raise MetricsValidationError(f"{field_name} must be an exact tuple")
    return cast(tuple[object, ...], value)


@runtime_checkable
class _PayloadLike(Protocol):
    def _payload(self) -> object: ...


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.astimezone(UTC).isoformat()}
    if isinstance(value, Enum):
        return {"enum": value.value}
    if isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
        return [_canonical(item) for item in items]
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_canonical(item) for item in items]
    if isinstance(value, Mapping):
        items = cast(Mapping[object, object], value)
        return {
            str(key): _canonical(item)
            for key, item in sorted(items.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, _PayloadLike):
        return _canonical(value._payload())  # pyright: ignore[reportPrivateUsage]
    return value


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        _canonical(value), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NavObservation:
    observation_time: datetime
    available_time: datetime
    nav: Decimal
    source_id: str = "portfolio"
    source_version: str = "1.0.0"
    provenance_digest: str = ZERO_DIGEST

    def __post_init__(self) -> None:
        _aware(self.observation_time, "observation_time")
        available = _aware(self.available_time, "available_time")
        if available > self.observation_time:
            raise MetricsValidationError("NAV availability cannot exceed observation time")
        _decimal(self.nav, "nav", positive=True)
        _text(self.source_id, "source_id")
        _text(self.source_version, "source_version")
        _digest(self.provenance_digest, "provenance_digest", allow_zero=True)

    @property
    def time(self) -> datetime:
        return self.observation_time

    def _payload(self) -> dict[str, object]:
        return {
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "nav": self.nav,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "provenance_digest": self.provenance_digest,
        }


@dataclass(frozen=True, slots=True)
class RiskFreeObservation:
    observation_time: datetime
    available_time: datetime
    rate: Decimal
    source_id: str = "risk-free"
    source_version: str = "1.0.0"
    provenance_digest: str = ZERO_DIGEST

    def __post_init__(self) -> None:
        _aware(self.observation_time, "observation_time")
        available = _aware(self.available_time, "available_time")
        if available > self.observation_time:
            raise MetricsValidationError("risk-free availability cannot exceed observation time")
        _decimal(self.rate, "rate")
        _text(self.source_id, "source_id")
        _text(self.source_version, "source_version")
        _digest(self.provenance_digest, "provenance_digest", allow_zero=True)

    @property
    def time(self) -> datetime:
        return self.observation_time

    def _payload(self) -> dict[str, object]:
        return {
            "observation_time": self.observation_time,
            "available_time": self.available_time,
            "rate": self.rate,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "provenance_digest": self.provenance_digest,
        }


@dataclass(frozen=True, slots=True)
class MetricsPolicy:
    policy_id: str
    policy_version: str
    frequency: str
    periods_per_year: int
    schema_version: str = METRICS_SCHEMA_VERSION
    algorithm_version: str = METRICS_ALGORITHM_VERSION
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.policy_id, "policy_id")
        _text(self.policy_version, "policy_version")
        if self.frequency != "DAILY":
            raise MetricsValidationError("only DAILY metrics frequency is supported")
        if type(self.periods_per_year) is not int or self.periods_per_year <= 0:
            raise MetricsValidationError("periods_per_year must be a positive integer")
        if self.schema_version != METRICS_SCHEMA_VERSION:
            raise MetricsValidationError("unsupported metrics schema")
        _text(self.algorithm_version, "algorithm_version")
        object.__setattr__(self, "policy_digest", canonical_digest(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "frequency": self.frequency,
            "periods_per_year": self.periods_per_year,
            "algorithm_version": self.algorithm_version,
        }

    def validate_integrity(self) -> None:
        original = self.policy_digest
        self.__post_init__()
        if original != canonical_digest(self._payload()):
            raise MetricsValidationError("metrics policy digest mismatch")


@dataclass(frozen=True, slots=True)
class MetricValue:
    status: MetricStatus
    value: Decimal | None

    def __post_init__(self) -> None:
        if type(self.status) is not MetricStatus:
            raise MetricsValidationError("metric status is invalid")
        if self.value is not None:
            _decimal(self.value, "metric.value")
        if self.status is MetricStatus.AVAILABLE and self.value is None:
            raise MetricsValidationError("available metric must contain a value")
        if self.status is not MetricStatus.AVAILABLE and self.value is not None:
            raise MetricsValidationError("unavailable metric must not contain a value")


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    schema_version: str
    algorithm_version: str
    policy_id: str
    policy_version: str
    policy_digest: str
    frequency: str
    periods_per_year: int
    nav_count: int
    return_count: int
    risk_free_count: int
    cutoff_time: datetime
    canonical_input_digest: str
    period_returns: tuple[Decimal, ...]
    cumulative_chained_return: Decimal | None
    cumulative_chained_return_status: MetricStatus
    annualized_return: Decimal | None
    annualized_return_status: MetricStatus
    annualized_volatility: Decimal | None
    annualized_volatility_status: MetricStatus
    maximum_drawdown: Decimal | None
    maximum_drawdown_status: MetricStatus
    sharpe: Decimal | None
    sharpe_status: MetricStatus
    sortino: Decimal | None
    sortino_status: MetricStatus
    calmar: Decimal | None
    calmar_status: MetricStatus
    result_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != METRICS_SCHEMA_VERSION:
            raise MetricsValidationError("unsupported metrics result schema")
        _text(self.algorithm_version, "algorithm_version")
        _text(self.policy_id, "policy_id")
        _text(self.policy_version, "policy_version")
        _digest(self.policy_digest, "policy_digest")
        if self.frequency != "DAILY":
            raise MetricsValidationError("unsupported result frequency")
        if type(self.periods_per_year) is not int or self.periods_per_year <= 0:
            raise MetricsValidationError("periods_per_year must be positive")
        for name in ("nav_count", "return_count", "risk_free_count"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise MetricsValidationError(f"{name} must be non-negative")
        if self.return_count != max(self.nav_count - 1, 0):
            raise MetricsValidationError("return_count does not match nav_count")
        _aware(self.cutoff_time, "cutoff_time")
        _digest(self.canonical_input_digest, "canonical_input_digest")
        raw_returns = _tuple(self.period_returns, "period_returns")
        for value in raw_returns:
            _decimal(value, "period_return")
        if self.return_count != len(raw_returns):
            raise MetricsValidationError("return_count does not match period_returns")
        for name in (
            "cumulative_chained_return",
            "annualized_return",
            "annualized_volatility",
            "maximum_drawdown",
            "sharpe",
            "sortino",
            "calmar",
        ):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name)
        for name in (
            "cumulative_chained_return_status",
            "annualized_return_status",
            "annualized_volatility_status",
            "maximum_drawdown_status",
            "sharpe_status",
            "sortino_status",
            "calmar_status",
        ):
            if type(getattr(self, name)) is not MetricStatus:
                raise MetricsValidationError(f"{name} is invalid")
        for name in (
            "cumulative_chained_return",
            "annualized_return",
            "annualized_volatility",
            "maximum_drawdown",
            "sharpe",
            "sortino",
            "calmar",
        ):
            MetricValue(
                getattr(self, f"{name}_status"),
                getattr(self, name),
            )
        object.__setattr__(self, "result_digest", canonical_digest(self._payload()))

    @property
    def input_digest(self) -> str:
        return self.canonical_input_digest

    def metric(self, name: str) -> MetricValue:
        value = getattr(self, name)
        status = getattr(self, f"{name}_status")
        return MetricValue(status, value)

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "algorithm_version": self.algorithm_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "frequency": self.frequency,
            "periods_per_year": self.periods_per_year,
            "nav_count": self.nav_count,
            "return_count": self.return_count,
            "risk_free_count": self.risk_free_count,
            "cutoff_time": self.cutoff_time,
            "canonical_input_digest": self.canonical_input_digest,
            "period_returns": self.period_returns,
            "cumulative_chained_return": self.cumulative_chained_return,
            "cumulative_chained_return_status": self.cumulative_chained_return_status,
            "annualized_return": self.annualized_return,
            "annualized_return_status": self.annualized_return_status,
            "annualized_volatility": self.annualized_volatility,
            "annualized_volatility_status": self.annualized_volatility_status,
            "maximum_drawdown": self.maximum_drawdown,
            "maximum_drawdown_status": self.maximum_drawdown_status,
            "sharpe": self.sharpe,
            "sharpe_status": self.sharpe_status,
            "sortino": self.sortino,
            "sortino_status": self.sortino_status,
            "calmar": self.calmar,
            "calmar_status": self.calmar_status,
        }

    def validate_integrity(self) -> None:
        original = self.result_digest
        self.__post_init__()
        if original != self.result_digest:
            raise MetricsValidationError("result digest mismatch")


__all__ = [
    "METRICS_ALGORITHM_VERSION",
    "METRICS_SCHEMA_VERSION",
    "MetricStatus",
    "MetricValue",
    "MetricsPolicy",
    "MetricsValidationError",
    "NavObservation",
    "PerformanceMetrics",
    "RiskFreeObservation",
    "canonical_digest",
]
