"""Precious-metal fund validator tests (Python port of the TS suite).

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/funds/fixtures.json).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.funds.validator import (
    PreciousMetalFund,
    RecurringFee,
    fund_from_dict,
    validate_precious_metal_fund,
)


class NamedFund(TypedDict):
    name: str
    fund: dict[str, object]


class InvalidFund(NamedFund):
    reason: str


_FIXTURES = cast(
    dict[str, object],
    json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "contracts"
            / "funds"
            / "fixtures.json"
        ).read_text(encoding="utf-8"),
        parse_float=Decimal,
    ),
)


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedFund], _FIXTURES["valid"]),
    ids=lambda f: f["name"],
)
def test_validate_valid_funds(fixture: NamedFund) -> None:
    result = validate_precious_metal_fund(fund_from_dict(fixture["fund"]))
    assert result.valid is True
    assert result.errors == []


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidFund], _FIXTURES["invalid"]),
    ids=lambda f: f["name"],
)
def test_validate_invalid_funds(fixture: InvalidFund) -> None:
    result = validate_precious_metal_fund(fund_from_dict(fixture["fund"]))
    assert result.valid is False
    assert len(result.errors) > 0


def test_classification_keeps_commodity_separate_from_fund_asset_class() -> None:
    valid = cast(list[NamedFund], _FIXTURES["valid"])
    for fixture in valid:
        fund = fund_from_dict(fixture["fund"])
        assert fund.fund_asset_class == "PRECIOUS_METALS"
        assert fund.underlying_commodity in ("GOLD", "SILVER", "OTHER")


def test_precious_metals_metadata_requires_explicit_classification_and_provenance() -> None:
    raw: dict[str, object] = {
        "unifiedCode": "518880.SH",
        "exchange": "SH",
        "assetType": "ETF",
        "fundAssetClass": "PRECIOUS_METALS",
        "underlyingCommodity": "GOLD",
        "tradingCurrency": "CNY",
        "navCurrency": "CNY",
        "benchmarkOrTrackingIndex": "Au99.99",
        "managementFeeRate": "0.005",
        "validFrom": "2020-01-01",
        "validTo": None,
        "source": "provider-x",
        "publishTime": "2026-08-13T09:00:00Z",
        "ingestTime": "2026-08-13T09:01:00Z",
        "availableTime": "2026-08-13T09:02:00Z",
        "processingTime": "2026-08-13T09:03:00Z",
        "rawObjectId": "sha256:classification",
        "confidence": "0.95",
        "reviewStatus": "REVIEWED",
    }

    fund = fund_from_dict(raw)
    result = validate_precious_metal_fund(fund)

    assert result.valid is True
    assert fund.fund_asset_class == "PRECIOUS_METALS"


def test_metadata_rejects_evidence_unavailable_at_decision_time() -> None:
    raw = cast(dict[str, object], cast(list[NamedFund], _FIXTURES["valid"])[0]["fund"]).copy()
    raw.update(
        {
            "publishTime": "2026-08-14T09:00:00Z",
            "ingestTime": "2026-08-14T09:01:00Z",
            "availableTime": "2026-08-14T09:02:00Z",
            "processingTime": "2026-08-14T09:03:00Z",
            "rawObjectId": "sha256:classification",
        }
    )

    fund = fund_from_dict(raw)
    result = validate_precious_metal_fund(
        fund,
        decision_time=datetime(2026, 8, 13, 12, tzinfo=UTC),
    )
    assert result.valid is False


def test_metadata_rejects_suffix_exchange_mismatch() -> None:
    raw = cast(dict[str, object], cast(list[NamedFund], _FIXTURES["valid"])[0]["fund"]).copy()
    raw["exchange"] = "SZ"
    result = validate_precious_metal_fund(fund_from_dict(raw))
    assert result.valid is False


def test_direct_fund_models_reject_float_rates() -> None:
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        RecurringFee(
            kind="custody",
            rate=0.1 + 0.2,
            valid_from="2020-01-01",
            valid_to=None,
            source="provider-x",
        )

    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        PreciousMetalFund(
            unified_code="518880.SH",
            exchange="SH",
            asset_type="ETF",
            fund_asset_class="PRECIOUS_METALS",
            underlying_commodity="GOLD",
            trading_currency="CNY",
            nav_currency="CNY",
            benchmark_or_tracking_index="Au99.99",
            management_fee_rate=0.1 + 0.2,
            valid_from="2020-01-01",
            valid_to=None,
            source="provider-x",
            publish_time=datetime(2026, 8, 13, 9, tzinfo=UTC),
            ingest_time=datetime(2026, 8, 13, 9, 1, tzinfo=UTC),
            available_time=datetime(2026, 8, 13, 9, 2, tzinfo=UTC),
            processing_time=datetime(2026, 8, 13, 9, 3, tzinfo=UTC),
            raw_object_id="sha256:classification",
            confidence=Decimal("0.95"),
            review_status="REVIEWED",
        )
