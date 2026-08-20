"""Limit fact model tests.

Covers per-board price limit rules (ST 5%, main 10%, ChiNext/STAR 20%, BSE
30%) and the no-price case, where no judgement is made.

P2-R01: prices use ``Decimal`` and round to the A-share 0.01 CNY tick size,
never binary float or ``round()``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
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


# --- P2-R01 R3-2: minimum one-tick adjustment for low-priced securities ---
#
# Per SSE Trading Rules 3.3.17 / SZSE Trading Rules 3.3.19: when the rounded
# limit price would differ from prev_close by less than one tick, the limit-up
# price is prev_close + one tick and the limit-down price is prev_close - one
# tick. SZSE additionally enforces a price floor of one tick. All three
# exchanges use tick 0.01 and equivalent minimum-one-tick adjustment. The tick
# size and adjustment rule are versioned in limit-rules.json, never hardcoded.


def test_low_price_st_limit_up_gets_min_one_tick() -> None:
    # prev_close 0.09, MAIN ST 5%: 0.09 * 1.05 = 0.0945 -> rounds to 0.09,
    # which equals prev_close (diff 0.00 < one tick). Must lift to prev + 1 tick.
    assert limit_up_price(Decimal("0.09"), "MAIN", True, exchange="SH") == Decimal("0.10")


def test_low_price_st_limit_down_gets_min_one_tick() -> None:
    # prev_close 0.09, MAIN ST 5%: 0.09 * 0.95 = 0.0855 -> rounds to 0.09,
    # which equals prev_close (diff 0.00 < one tick). Must drop to prev - 1 tick.
    assert limit_down_price(Decimal("0.09"), "MAIN", True, exchange="SH") == Decimal("0.08")


def test_low_price_limit_down_not_below_min_legal_price_sz() -> None:
    # prev_close 0.01 on SZSE: naive limit-down would go to 0.00, but the SZSE
    # price floor is one tick (0.01). The result must not be below one tick.
    assert limit_down_price(Decimal("0.01"), "MAIN", True, exchange="SZ") == Decimal("0.01")


def test_normal_price_is_unchanged_by_tick_adjustment() -> None:
    # 10.00 main board: 11.00 / 9.00 — diff is far more than one tick,
    # so the minimum-one-tick adjustment is a no-op.
    assert limit_up_price(Decimal("10.00"), "MAIN", False, exchange="SH") == Decimal("11.00")
    assert limit_down_price(Decimal("10.00"), "MAIN", False, exchange="SH") == Decimal("9.00")


def test_unknown_exchange_is_rejected() -> None:
    # Fail-closed: an exchange with no versioned tick rule must not be guessed.
    with pytest.raises(ValueError, match="unknown exchange"):
        limit_up_price(Decimal("10.00"), "MAIN", False, exchange="XX")
