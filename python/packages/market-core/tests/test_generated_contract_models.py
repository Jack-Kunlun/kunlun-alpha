"""Generated Pydantic model boundary tests.

These tests exercise the generated artifacts directly rather than the domain
dataclasses.  Generated transport models must not silently coerce binary
floats into Decimal values, and records carrying both unifiedCode and exchange
must enforce the shared prefix/suffix identity.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import pytest
from ashare_contracts.funds_fund_nav import FundNav
from ashare_contracts.funds_precious_metal_fund import PreciousMetalFund
from ashare_contracts.market_data_adjustment_factor import AdjustmentFactor
from ashare_contracts.market_data_bar import Bar
from ashare_contracts.market_data_corporate_action import CorporateAction
from ashare_contracts.market_data_tick import Tick


def _fund_nav_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": Decimal("1.0"),
        "inav": Decimal("1.1"),
        "eventTime": "2026-08-13T09:00:00Z",
        "publishTime": "2026-08-13T09:01:00Z",
        "ingestTime": "2026-08-13T09:02:00Z",
        "availableTime": "2026-08-13T09:03:00Z",
        "processingTime": "2026-08-13T09:04:00Z",
        "rawObjectId": "sha256:nav",
        "source": "provider-x",
    }


def _fund_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "518880.SH",
        "exchange": "SH",
        "assetType": "ETF",
        "fundAssetClass": "PRECIOUS_METALS",
        "underlyingCommodity": "GOLD",
        "tradingCurrency": "CNY",
        "navCurrency": "CNY",
        "benchmarkOrTrackingIndex": "Au99.99",
        "managementFeeRate": Decimal("0.005"),
        "validFrom": "2020-01-01",
        "validTo": None,
        "source": "provider-x",
        "publishTime": "2026-08-13T09:00:00Z",
        "ingestTime": "2026-08-13T09:01:00Z",
        "availableTime": "2026-08-13T09:02:00Z",
        "processingTime": "2026-08-13T09:03:00Z",
        "rawObjectId": "sha256:fund",
        "confidence": Decimal("0.95"),
        "reviewStatus": "REVIEWED",
    }


def _bar_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "600000.SH",
        "exchange": "SH",
        "date": "2026-08-13",
        "interval": "DAILY",
        "session": "CONTINUOUS",
        "timestamp": "2026-08-13T09:00:00Z",
        "open": Decimal("10.0"),
        "high": Decimal("10.5"),
        "low": Decimal("9.8"),
        "close": Decimal("10.2"),
        "volume": 1000,
        "amount": Decimal("10200"),
        "priceType": "RAW",
    }


def _tick_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "600000.SH",
        "exchange": "SH",
        "date": "2026-08-13",
        "timestamp": "2026-08-13T09:00:00Z",
        "price": Decimal("10.0"),
        "volume": 100,
        "amount": Decimal("1000"),
        "direction": "BUY",
        "tradeType": "MATCH",
    }


def _factor_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "600000.SH",
        "exchange": "SH",
        "date": "2026-08-13",
        "factor": Decimal("1.1"),
        "factorType": "FORWARD",
    }


def _action_payload() -> dict[str, Any]:
    return {
        "unifiedCode": "600000.SH",
        "exchange": "SH",
        "exDate": "2026-08-13",
        "actionType": "DIVIDEND",
        "description": "cash dividend",
        "perShareCash": Decimal("0.5"),
    }


@pytest.mark.parametrize(
    ("model", "payload", "field"),
    [
        (FundNav, _fund_nav_payload(), "nav"),
        (PreciousMetalFund, _fund_payload(), "managementFeeRate"),
        (Bar, _bar_payload(), "open"),
        (Tick, _tick_payload(), "price"),
        (AdjustmentFactor, _factor_payload(), "factor"),
        (CorporateAction, _action_payload(), "perShareCash"),
    ],
)
def test_generated_models_reject_binary_float_before_decimal_coercion(
    model: type[Any], payload: dict[str, Any], field: str
) -> None:
    payload[field] = 0.1 + 0.2

    with pytest.raises(
        (TypeError, ValueError), match="float is not an accepted decimal boundary value"
    ):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (PreciousMetalFund, _fund_payload()),
        (Bar, _bar_payload()),
        (Tick, _tick_payload()),
        (AdjustmentFactor, _factor_payload()),
        (CorporateAction, _action_payload()),
    ],
)
def test_generated_models_reject_unified_code_exchange_mismatch(
    model: type[Any], payload: dict[str, Any]
) -> None:
    mismatched = deepcopy(payload)
    mismatched["unifiedCode"] = "600000.SZ"
    mismatched["exchange"] = "SH"

    with pytest.raises(ValueError, match="unifiedCode.*exchange"):
        model.model_validate(mismatched)


def test_generated_constructor_rejects_float_directly() -> None:
    payload = _bar_payload()
    payload["open"] = 0.1 + 0.2

    with pytest.raises(
        (TypeError, ValueError), match="float is not an accepted decimal boundary value"
    ):
        Bar(**payload)
