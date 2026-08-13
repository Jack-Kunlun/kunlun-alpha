"""Market data validator tests (Python port of the TS suite).

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/market-data/fixtures.json) so both validators stay
aligned. Covers price, volume, amount, suspended and adjustment samples.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.models.validators import (
    ValidationResult,
    action_from_dict,
    bar_from_dict,
    factor_from_dict,
    tick_from_dict,
    validate_adjustment_factor,
    validate_bar,
    validate_corporate_action,
    validate_tick,
)


class NamedBar(TypedDict):
    name: str
    bar: dict[str, object]


class InvalidBar(NamedBar):
    reason: str


class NamedTick(TypedDict):
    name: str
    tick: dict[str, object]


class InvalidTick(NamedTick):
    reason: str


class NamedFactor(TypedDict):
    name: str
    factor: dict[str, object]


class InvalidFactor(NamedFactor):
    reason: str


class NamedAction(TypedDict):
    name: str
    action: dict[str, object]


class InvalidAction(NamedAction):
    reason: str


_FIXTURES = cast(
    dict[str, object],
    json.loads(
        (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "contracts"
            / "market-data"
            / "fixtures.json"
        ).read_text(encoding="utf-8"),
    ),
)


def _assert_valid(result: ValidationResult) -> None:
    assert result.valid is True
    assert result.errors == []


def _assert_invalid(result: ValidationResult) -> None:
    assert result.valid is False
    assert len(result.errors) > 0


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedBar], cast(dict[str, object], _FIXTURES["bars"])["valid"]),
    ids=lambda f: f["name"],
)
def test_validate_bar_valid(fixture: NamedBar) -> None:
    _assert_valid(validate_bar(bar_from_dict(fixture["bar"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedBar], cast(dict[str, object], _FIXTURES["bars"])["suspended"]),
    ids=lambda f: f["name"],
)
def test_validate_bar_suspended(fixture: NamedBar) -> None:
    _assert_valid(validate_bar(bar_from_dict(fixture["bar"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidBar], cast(dict[str, object], _FIXTURES["bars"])["invalid"]),
    ids=lambda f: f["name"],
)
def test_validate_bar_invalid(fixture: InvalidBar) -> None:
    _assert_invalid(validate_bar(bar_from_dict(fixture["bar"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedTick], cast(dict[str, object], _FIXTURES["ticks"])["valid"]),
    ids=lambda f: f["name"],
)
def test_validate_tick_valid(fixture: NamedTick) -> None:
    _assert_valid(validate_tick(tick_from_dict(fixture["tick"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidTick], cast(dict[str, object], _FIXTURES["ticks"])["invalid"]),
    ids=lambda f: f["name"],
)
def test_validate_tick_invalid(fixture: InvalidTick) -> None:
    _assert_invalid(validate_tick(tick_from_dict(fixture["tick"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedFactor], cast(dict[str, object], _FIXTURES["factors"])["valid"]),
    ids=lambda f: f["name"],
)
def test_validate_factor_valid(fixture: NamedFactor) -> None:
    _assert_valid(validate_adjustment_factor(factor_from_dict(fixture["factor"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidFactor], cast(dict[str, object], _FIXTURES["factors"])["invalid"]),
    ids=lambda f: f["name"],
)
def test_validate_factor_invalid(fixture: InvalidFactor) -> None:
    _assert_invalid(validate_adjustment_factor(factor_from_dict(fixture["factor"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[NamedAction], cast(dict[str, object], _FIXTURES["actions"])["valid"]),
    ids=lambda f: f["name"],
)
def test_validate_action_valid(fixture: NamedAction) -> None:
    _assert_valid(validate_corporate_action(action_from_dict(fixture["action"])))


@pytest.mark.parametrize(
    "fixture",
    cast(list[InvalidAction], cast(dict[str, object], _FIXTURES["actions"])["invalid"]),
    ids=lambda f: f["name"],
)
def test_validate_action_invalid(fixture: InvalidAction) -> None:
    _assert_invalid(validate_corporate_action(action_from_dict(fixture["action"])))


def test_research_vs_trade_price_separation() -> None:
    """Both RAW and adjusted bars are accepted as long as priceType is explicit."""
    valid_bars = cast(list[NamedBar], cast(dict[str, object], _FIXTURES["bars"])["valid"])
    for fixture in valid_bars:
        bar = bar_from_dict(fixture["bar"])
        assert bar.price_type in ("RAW", "FORWARD_ADJUSTED", "BACKWARD_ADJUSTED")
