"""Precious-metal fund contracts."""

from market_core.funds.validator import (
    AssetClass,
    PreciousMetalFund,
    ValidationResult,
    fund_from_dict,
    validate_precious_metal_fund,
)

__all__ = [
    "AssetClass",
    "PreciousMetalFund",
    "ValidationResult",
    "fund_from_dict",
    "validate_precious_metal_fund",
]
