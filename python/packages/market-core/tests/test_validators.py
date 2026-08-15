"""Market data validator tests (Python port of the TS suite).

Driven by the same fixtures file as the TypeScript suite
(packages/contracts/market-data/fixtures.json) so both validators stay
aligned. Covers price, volume, amount, suspended and adjustment samples.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import TypedDict, cast

import pytest
from market_core.models.validators import (
    AdjustmentFactor,
    Bar,
    CorporateAction,
    Tick,
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
        parse_float=Decimal,
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


def test_price_sensitive_market_fields_use_decimal_without_float_round_trip() -> None:
    bar = bar_from_dict(
        {
            "unifiedCode": "600000.SH",
            "exchange": "SH",
            "date": "2026-08-13",
            "interval": "DAILY",
            "session": "CONTINUOUS",
            "timestamp": "2026-08-13T07:00:00.000Z",
            "open": Decimal("0.1"),
            "high": Decimal("0.3"),
            "low": Decimal("0.1"),
            "close": Decimal("0.3"),
            "volume": 1,
            "amount": Decimal("0.3"),
            "priceType": "RAW",
        }
    )

    assert bar.open == Decimal("0.1")
    assert bar.amount == Decimal("0.3")
    assert validate_bar(bar).valid is True

    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        bar_from_dict({**{
            "unifiedCode": "600000.SH",
            "exchange": "SH",
            "date": "2026-08-13",
            "interval": "DAILY",
            "session": "CONTINUOUS",
            "timestamp": "2026-08-13T07:00:00.000Z",
            "open": 0.1 + 0.2,
            "high": Decimal("0.4"),
            "low": Decimal("0.1"),
            "close": Decimal("0.3"),
            "volume": 1,
            "amount": Decimal("0.3"),
            "priceType": "RAW",
        }})


def test_direct_market_models_reject_float_price_values() -> None:
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        Bar(
            unified_code="600000.SH",
            exchange="SH",
            date="2026-08-13",
            interval="DAILY",
            session="CONTINUOUS",
            timestamp="2026-08-13T07:00:00.000Z",
            open=0.1 + 0.2,
            high=Decimal("0.4"),
            low=Decimal("0.1"),
            close=Decimal("0.3"),
            volume=1,
            amount=Decimal("0.3"),
            price_type="RAW",
        )
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        Tick(
            unified_code="600000.SH",
            exchange="SH",
            date="2026-08-13",
            timestamp="2026-08-13T07:00:00.000Z",
            price=0.1 + 0.2,
            volume=1,
            amount=Decimal("0.3"),
            direction="BUY",
            trade_type="MATCH",
        )
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        AdjustmentFactor(
            unified_code="600000.SH",
            exchange="SH",
            date="2026-08-13",
            factor=0.1 + 0.2,
            factor_type="FORWARD",
        )
    with pytest.raises(TypeError, match="float is not an accepted decimal boundary value"):
        CorporateAction(
            unified_code="600000.SH",
            exchange="SH",
            ex_date="2026-08-13",
            action_type="DIVIDEND",
            description="cash dividend",
            per_share_cash=0.1 + 0.2,
        )


@pytest.mark.parametrize(
    "factory, raw",
    [
        (
            bar_from_dict,
            {
                "unifiedCode": "600000.SZ",
                "exchange": "SH",
                "date": "2026-08-13",
                "interval": "DAILY",
                "session": "CONTINUOUS",
                "timestamp": "2026-08-13T07:00:00.000Z",
                "open": Decimal("0.1"),
                "high": Decimal("0.4"),
                "low": Decimal("0.1"),
                "close": Decimal("0.3"),
                "volume": 1,
                "amount": Decimal("0.3"),
                "priceType": "RAW",
            },
        ),
        (
            tick_from_dict,
            {
                "unifiedCode": "600000.SZ",
                "exchange": "SH",
                "date": "2026-08-13",
                "timestamp": "2026-08-13T07:00:00.000Z",
                "price": Decimal("0.3"),
                "volume": 1,
                "amount": Decimal("0.3"),
                "direction": "BUY",
                "tradeType": "MATCH",
            },
        ),
        (
            factor_from_dict,
            {
                "unifiedCode": "600000.SZ",
                "exchange": "SH",
                "date": "2026-08-13",
                "factor": Decimal("1"),
                "factorType": "FORWARD",
            },
        ),
        (
            action_from_dict,
            {
                "unifiedCode": "600000.SZ",
                "exchange": "SH",
                "exDate": "2026-08-13",
                "actionType": "DIVIDEND",
                "description": "cash dividend",
                "perShareCash": Decimal("0.3"),
            },
        ),
        (
            bar_from_dict,
            {
                "unifiedCode": "123456.SH",
                "exchange": "SH",
                "date": "2026-08-13",
                "interval": "DAILY",
                "session": "CONTINUOUS",
                "timestamp": "2026-08-13T07:00:00.000Z",
                "open": Decimal("0.1"),
                "high": Decimal("0.4"),
                "low": Decimal("0.1"),
                "close": Decimal("0.3"),
                "volume": 1,
                "amount": Decimal("0.3"),
                "priceType": "RAW",
            },
        ),
    ],
)
def test_factories_reject_unified_code_exchange_mismatch(
    factory: Callable[[dict[str, object]], object], raw: dict[str, object]
) -> None:
    with pytest.raises(ValueError, match="unifiedCode/exchange identity mismatch"):
        factory(raw)
