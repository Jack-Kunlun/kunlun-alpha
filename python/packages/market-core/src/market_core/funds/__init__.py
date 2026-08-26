"""Precious-metal fund contracts."""

from ashare_contracts import BenchmarkSeriesPoint

from market_core.funds.validator import (
    AssetClass,
    AssetType,
    FundAssetClass,
    PreciousMetalFund,
    RecurringFee,
    ReviewStatus,
    UnderlyingCommodity,
    ValidationResult,
    benchmark_series_matches,
    fund_from_dict,
    validate_precious_metal_fund,
)

__all__ = [
    "AssetClass",
    "AssetType",
    "BenchmarkSeriesPoint",
    "FundAssetClass",
    "PreciousMetalFund",
    "RecurringFee",
    "ReviewStatus",
    "UnderlyingCommodity",
    "ValidationResult",
    "benchmark_series_matches",
    "fund_from_dict",
    "validate_precious_metal_fund",
]
