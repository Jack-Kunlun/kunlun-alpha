"""Limit fact model tests.

Covers per-board price limit rules (ST 5%, main 10%, ChiNext/STAR 20%, BSE
30%) and the no-price case, where no judgement is made.

P2-R01: prices use ``Decimal`` and round to the A-share 0.01 CNY tick size,
never binary float or ``round()``.
"""

from __future__ import annotations

from decimal import Decimal

from emotion_core.models import (
    is_limit_down,
    is_limit_up,
    limit_down_price,
    limit_rate,
    limit_up_price,
)


def test_limit_rates_by_board_and_st() -> None:
    assert limit_rate("MAIN", False) == Decimal("0.1")
    assert limit_rate("CHINEXT", False) == Decimal("0.2")
    assert limit_rate("STAR", False) == Decimal("0.2")
    assert limit_rate("BSE", False) == Decimal("0.3")
    assert limit_rate("MAIN", True) == Decimal("0.05")
    assert limit_rate("CHINEXT", True) == Decimal("0.05")
    assert limit_rate("BSE", True) == Decimal("0.05")


def test_limit_up_price_rounds_to_cent() -> None:
    # 10.00 * 1.10 = 11.00
    assert limit_up_price(Decimal("10.00"), "MAIN", False) == Decimal("11.00")
    # 10.00 * 1.20 = 12.00 (ChiNext)
    assert limit_up_price(Decimal("10.00"), "CHINEXT", False) == Decimal("12.00")
    # 10.00 * 1.05 = 10.50 (ST)
    assert limit_up_price(Decimal("10.00"), "MAIN", True) == Decimal("10.50")


def test_limit_up_price_uses_tick_size_not_float_round() -> None:
    # 9.99 * 1.10 = 10.989 -> tick 0.01 -> 10.99 (ROUND_HALF_UP)
    assert limit_up_price(Decimal("9.99"), "MAIN", False) == Decimal("10.99")
    # 9.93 * 1.10 = 10.923 -> 10.92
    assert limit_up_price(Decimal("9.93"), "MAIN", False) == Decimal("10.92")


def test_limit_down_price_uses_tick_size() -> None:
    # 10.00 * 0.90 = 9.00
    assert limit_down_price(Decimal("10.00"), "MAIN", False) == Decimal("9.00")
    # 10.05 * 0.90 = 9.045 -> 9.05 (ROUND_HALF_UP, tick 0.01)
    assert limit_down_price(Decimal("10.05"), "MAIN", False) == Decimal("9.05")


def test_no_binary_float_drift() -> None:
    # A rate that would drift under binary float (0.1 + 0.2 style) must stay exact.
    price = limit_up_price(Decimal("10.00"), "STAR", False)  # 1.20 -> 12.00
    assert price == Decimal("12.00")
    # Inputs accept Decimal, not float; the result type is Decimal.
    assert isinstance(price, Decimal)


def test_is_limit_up_by_board() -> None:
    assert is_limit_up(Decimal("11.00"), Decimal("10.00"), "MAIN", False) is True
    assert is_limit_up(Decimal("12.00"), Decimal("10.00"), "CHINEXT", False) is True
    assert is_limit_up(Decimal("13.00"), Decimal("10.00"), "BSE", False) is True
    assert is_limit_up(Decimal("10.50"), Decimal("10.00"), "MAIN", True) is True
    assert is_limit_up(Decimal("10.99"), Decimal("10.00"), "MAIN", False) is False


def test_is_limit_down() -> None:
    # 10.00 * 0.90 = 9.00
    assert is_limit_down(Decimal("9.00"), Decimal("10.00"), "MAIN", False) is True
    assert is_limit_down(Decimal("9.01"), Decimal("10.00"), "MAIN", False) is False


def test_no_price_makes_no_judgement() -> None:
    # prev_close == 0 (e.g. suspended with no reference price)
    assert is_limit_up(Decimal("0.00"), Decimal("0.00"), "MAIN", False) is False
    assert is_limit_down(Decimal("0.00"), Decimal("0.00"), "MAIN", False) is False
