"""Precious-metal fund validator.

Python port of packages/contracts/src/funds/validator.ts. The underlying
commodity is explicit — never guessed from the product name — and no
spot/futures semantics are introduced. Validation covers asset class, currency
consistency and historical validity windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

AssetClass = Literal["GOLD", "SILVER", "OTHER"]

_ASSET_CLASSES = ("GOLD", "SILVER", "OTHER")


@dataclass(frozen=True)
class PreciousMetalFund:
    """Exchange-traded precious-metal fund metadata."""

    unified_code: str
    exchange: str
    fund_asset_class: str
    underlying_commodity: str
    currency: str
    benchmark: str
    management_fee_rate: float
    valid_from: str
    valid_to: str | None
    source: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation: valid flag plus accumulated error messages."""

    valid: bool
    errors: list[str]


def fund_from_dict(raw: dict[str, object]) -> PreciousMetalFund:
    """Build a PreciousMetalFund from a camelCase JSON dict (fixtures format)."""
    return PreciousMetalFund(
        unified_code=str(raw["unifiedCode"]),
        exchange=str(raw["exchange"]),
        fund_asset_class=str(raw["fundAssetClass"]),
        underlying_commodity=str(raw["underlyingCommodity"]),
        currency=str(raw["currency"]),
        benchmark=str(raw["benchmark"]),
        management_fee_rate=cast(float, raw["managementFeeRate"]),
        valid_from=str(raw["validFrom"]),
        valid_to=cast("str | None", raw.get("validTo")),
        source=str(raw["source"]),
    )


def validate_precious_metal_fund(fund: PreciousMetalFund) -> ValidationResult:
    """Validate a precious-metal fund's classification, currency and validity."""
    errors: list[str] = []

    if fund.fund_asset_class not in _ASSET_CLASSES:
        errors.append("fundAssetClass must be GOLD/SILVER/OTHER")
    if fund.underlying_commodity not in _ASSET_CLASSES:
        errors.append("underlyingCommodity must be GOLD/SILVER/OTHER")
    if fund.currency != "CNY":
        errors.append("currency must be CNY")
    if fund.valid_to is not None and fund.valid_from > fund.valid_to:
        errors.append("validFrom must be <= validTo")
    if fund.management_fee_rate < 0:
        errors.append("managementFeeRate must be >= 0")

    return ValidationResult(valid=not errors, errors=errors)
