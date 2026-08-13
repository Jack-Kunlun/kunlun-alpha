"""Precious-metal fund validator tests (Python port of the TS suite).

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/funds/fixtures.json).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.funds.validator import fund_from_dict, validate_precious_metal_fund


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


def test_classification_accepts_gold_silver_other() -> None:
    valid = cast(list[NamedFund], _FIXTURES["valid"])
    for fixture in valid:
        fund = fund_from_dict(fixture["fund"])
        assert fund.fund_asset_class in ("GOLD", "SILVER", "OTHER")
        assert fund.underlying_commodity != ""
