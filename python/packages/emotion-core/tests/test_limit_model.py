"""Limit fact model tests.

Covers per-board price limit rules (ST 5%, main 10%, ChiNext/STAR 20%, BSE
30%) and the no-price case, where no judgement is made.
"""

from __future__ import annotations

from emotion_core.models import is_limit_down, is_limit_up, limit_rate, limit_up_price


def test_limit_rates_by_board_and_st() -> None:
    assert limit_rate("MAIN", False) == 0.1
    assert limit_rate("CHINEXT", False) == 0.2
    assert limit_rate("STAR", False) == 0.2
    assert limit_rate("BSE", False) == 0.3
    assert limit_rate("MAIN", True) == 0.05
    assert limit_rate("CHINEXT", True) == 0.05
    assert limit_rate("BSE", True) == 0.05


def test_limit_up_price_rounds_to_cent() -> None:
    # 10.00 * 1.10 = 11.00
    assert limit_up_price(10.00, "MAIN", False) == 11.00
    # 10.00 * 1.20 = 12.00 (ChiNext)
    assert limit_up_price(10.00, "CHINEXT", False) == 12.00
    # 10.00 * 1.05 = 10.50 (ST)
    assert limit_up_price(10.00, "MAIN", True) == 10.50


def test_is_limit_up_by_board() -> None:
    assert is_limit_up(11.00, 10.00, "MAIN", False) is True
    assert is_limit_up(12.00, 10.00, "CHINEXT", False) is True
    assert is_limit_up(13.00, 10.00, "BSE", False) is True
    assert is_limit_up(10.50, 10.00, "MAIN", True) is True
    assert is_limit_up(10.99, 10.00, "MAIN", False) is False


def test_is_limit_down() -> None:
    # 10.00 * 0.90 = 9.00
    assert is_limit_down(9.00, 10.00, "MAIN", False) is True
    assert is_limit_down(9.01, 10.00, "MAIN", False) is False


def test_no_price_makes_no_judgement() -> None:
    # prev_close == 0 (e.g. suspended with no reference price)
    assert is_limit_up(0.0, 0.0, "MAIN", False) is False
    assert is_limit_down(0.0, 0.0, "MAIN", False) is False
