"""Precious-metal fund contracts."""

from market_core.funds.validator import (
    AssetClass,
    AssetType,
    FundAssetClass,
    PreciousMetalFund,
    RecurringFee,
    ReviewStatus,
    UnderlyingCommodity,
    ValidationResult,
    fund_from_dict,
    validate_precious_metal_fund,
)

__all__ = [
    "AssetClass",
    "AssetType",
    "FundAssetClass",
    "PreciousMetalFund",
    "RecurringFee",
    "ReviewStatus",
    "UnderlyingCommodity",
    "ValidationResult",
    "fund_from_dict",
    "validate_precious_metal_fund",
]
