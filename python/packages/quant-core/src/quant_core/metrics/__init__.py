"""Generic Decimal performance metrics with no backtest-core dependency."""

from .models import (
    METRICS_ALGORITHM_VERSION,
    METRICS_SCHEMA_VERSION,
    MetricsPolicy,
    MetricStatus,
    MetricsValidationError,
    MetricValue,
    NavObservation,
    PerformanceMetrics,
    RiskFreeObservation,
    canonical_digest,
)
from .performance import (
    calculate_metrics,
    calculate_performance_metrics,
    verify_performance_metrics_against_inputs,
)

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
    "calculate_metrics",
    "calculate_performance_metrics",
    "verify_performance_metrics_against_inputs",
    "canonical_digest",
]
