"""Premium / loss-making effect tests.

Covers unbiased sampling (suspended and one-word boards excluded), average
premium, win rate, and high-to-close drawdown.
"""

from __future__ import annotations

from emotion_core.premium import compute_drawdown, compute_premium


def test_average_premium_and_win_rate() -> None:
    pool = ["A", "B", "C"]
    yesterday_close = {"A": 10.0, "B": 10.0, "C": 10.0}
    today_open = {"A": 11.0, "B": 9.5, "C": 10.0}  # +10%, -5%, 0%

    result = compute_premium(pool, yesterday_close, today_open)

    assert result.sample_size == 3
    assert abs(result.average_premium - (0.10 - 0.05 + 0.0) / 3) < 1e-9
    assert abs(result.win_rate - 1 / 3) < 1e-9


def test_suspended_and_one_word_board_excluded() -> None:
    pool = ["A", "B", "C"]
    yesterday_close = {"A": 10.0, "B": 10.0, "C": 10.0}
    today_open = {"A": 11.0}  # B, C missing (suspended / no data)

    result = compute_premium(
        pool, yesterday_close, today_open, suspended={"B"}, one_word_board={"C"}
    )

    assert result.sample_size == 1
    assert abs(result.average_premium - 0.10) < 1e-9


def test_empty_sample_returns_zero() -> None:
    result = compute_premium(["A"], {"A": 10.0}, {}, suspended={"A"})
    assert result.sample_size == 0
    assert result.average_premium == 0.0


def test_high_to_close_drawdown() -> None:
    pool = ["A", "B"]
    today_high = {"A": 12.0, "B": 10.0}
    today_close = {"A": 11.0, "B": 9.0}  # drawdown 8.3%, 10%

    result = compute_drawdown(pool, today_high, today_close)
    assert abs(result - ((1 / 12) + (1 / 10)) / 2) < 1e-9
