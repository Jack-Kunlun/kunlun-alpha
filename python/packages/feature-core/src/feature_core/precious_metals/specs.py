"""Versioned FeatureSpec definitions for exchange-listed precious-metal funds."""

from __future__ import annotations

from feature_core.registry import (
    AvailabilityPolicy,
    FeatureEntity,
    FeatureFrequency,
    FeatureRegistry,
    FeatureSpec,
    FeatureValueType,
    SourceContract,
)

PRECIOUS_METALS_FEATURE_VERSION = "v1"
PRECIOUS_METALS_ALGORITHM_VERSION = "v1"
PRECIOUS_METALS_POLICY_VERSION = "v1"
PRECIOUS_METALS_SOURCE_CONTRACT_VERSION = "v1"

_SOURCE_CONTRACTS = {
    "fund": SourceContract(name="domain.precious_metal_fund", version="v1"),
    "nav": SourceContract(name="domain.fund_nav", version="v1"),
    "bar": SourceContract(name="market.daily_bar", version="v1"),
    "benchmark": SourceContract(name="market.benchmark_series_point", version="v1"),
}


def _spec(
    name: str,
    frequency: FeatureFrequency,
    definition: str,
    window: str,
    source_contracts: tuple[str, ...],
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        version=PRECIOUS_METALS_FEATURE_VERSION,
        entity=FeatureEntity.PRECIOUS_METALS_FUND,
        frequency=frequency,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research.precious-metals",
        description=definition,
        algorithm_version=PRECIOUS_METALS_ALGORITHM_VERSION,
        calculation_definition=definition,
        window_definition=window,
        filter_policy_version=PRECIOUS_METALS_POLICY_VERSION,
        pit_policy_version=PRECIOUS_METALS_POLICY_VERSION,
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
        dependencies=(),
        source_contracts=tuple(_SOURCE_CONTRACTS[item] for item in source_contracts),
    )


_SPECS = (
    _spec(
        "precious_metals_fund.premium_discount_bps",
        FeatureFrequency.SNAPSHOT,
        "10000 * (raw market reference / fresh iNAV or eligible NAV - 1)",
        "EVENT_TIME_TUMBLING:P1D",
        ("fund", "nav", "bar"),
    ),
    _spec(
        "precious_metals_fund.tracking_difference_bps_20_sessions",
        FeatureFrequency.DAILY,
        "mean((raw fund return - benchmark return) * 10000) over paired sessions",
        "EVENT_TIME_TUMBLING:P20D",
        ("fund", "bar", "benchmark"),
    ),
    _spec(
        "precious_metals_fund.tracking_error_bps_20_sessions",
        FeatureFrequency.DAILY,
        "sample standard deviation of paired return differences * 10000",
        "EVENT_TIME_TUMBLING:P20D",
        ("fund", "bar", "benchmark"),
    ),
    _spec(
        "precious_metals_fund.liquidity_median_turnover_cny_20_sessions",
        FeatureFrequency.DAILY,
        "median amount for non-suspended raw daily bars with amount > 0",
        "EVENT_TIME_TUMBLING:P20D",
        ("fund", "bar"),
    ),
    _spec(
        "precious_metals_fund.benchmark_beta_20_sessions",
        FeatureFrequency.DAILY,
        "sample covariance(raw fund return, benchmark return) / sample benchmark variance",
        "EVENT_TIME_TUMBLING:P20D",
        ("fund", "bar", "benchmark"),
    ),
)


def precious_metals_feature_specs() -> tuple[FeatureSpec, ...]:
    """Return the immutable v1 feature specification tuple."""
    return _SPECS


def precious_metals_feature_registry(
    *, namespace_id: str = "precious_metals.funds"
) -> FeatureRegistry:
    """Build a registry snapshot without introducing a benchmark default."""
    registry = FeatureRegistry.empty(namespace_id=namespace_id)
    return registry.evolve(_SPECS, expected_parent_fingerprint=registry.head_fingerprint)


__all__ = [
    "PRECIOUS_METALS_ALGORITHM_VERSION",
    "PRECIOUS_METALS_FEATURE_VERSION",
    "PRECIOUS_METALS_POLICY_VERSION",
    "PRECIOUS_METALS_SOURCE_CONTRACT_VERSION",
    "precious_metals_feature_registry",
    "precious_metals_feature_specs",
]
