"""Premium / loss-making effect tests.

Covers unbiased sampling (suspended and one-word boards excluded), average
premium, win rate, high-to-close drawdown, point-in-time availability filtering
and provenance/version fields.
"""

from __future__ import annotations

from emotion_core.premium import PREMIUM_VERSION, compute_drawdown, compute_premium


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
    assert result.exclusion_reasons["B"] == "suspended"
    assert result.exclusion_reasons["C"] == "one_word_board"


def test_empty_sample_returns_zero() -> None:
    result = compute_premium(["A"], {"A": 10.0}, {}, suspended={"A"})
    assert result.sample_size == 0
    assert result.average_premium == 0.0


def test_premium_result_carries_version() -> None:
    result = compute_premium(["A"], {"A": 10.0}, {"A": 11.0})
    assert result.version == PREMIUM_VERSION


def test_sample_unavailable_at_decision_time_is_excluded() -> None:
    # C's price only becomes available at 05:00, but the decision is made at
    # 01:30 — a same-day close/high that leaks after the observation time must
    # be excluded, never used as if it were known.
    pool = ["A", "B", "C"]
    yesterday_close = {"A": 10.0, "B": 10.0, "C": 10.0}
    today_price = {"A": 11.0, "B": 9.5, "C": 10.5}
    available_times = {
        "A": "2026-08-14T01:00:00.000Z",
        "B": "2026-08-14T01:20:00.000Z",
        "C": "2026-08-14T05:00:00.000Z",  # leaks after decision_time
    }

    result = compute_premium(
        pool,
        yesterday_close,
        today_price,
        available_times=available_times,
        decision_time="2026-08-14T01:30:00.000Z",
    )

    assert result.sample_size == 2  # A and B only
    assert result.exclusion_reasons["C"] == "unavailable_at_decision_time"


def test_available_exactly_at_decision_time_is_included() -> None:
    pool = ["A"]
    result = compute_premium(
        pool,
        {"A": 10.0},
        {"A": 11.0},
        available_times={"A": "2026-08-14T01:30:00.000Z"},
        decision_time="2026-08-14T01:30:00.000Z",
    )
    assert result.sample_size == 1


def test_high_to_close_drawdown() -> None:
    pool = ["A", "B"]
    today_high = {"A": 12.0, "B": 10.0}
    today_close = {"A": 11.0, "B": 9.0}  # drawdown 8.3%, 10%

    result = compute_drawdown(pool, today_high, today_close)
    assert abs(result - ((1 / 12) + (1 / 10)) / 2) < 1e-9


def test_drawdown_excludes_samples_unavailable_at_decision_time() -> None:
    pool = ["A", "B"]
    today_high = {"A": 12.0, "B": 10.0}
    today_close = {"A": 11.0, "B": 9.0}
    available_times = {
        "A": "2026-08-14T07:00:00.000Z",  # close only known after decision
        "B": "2026-08-14T07:00:00.000Z",
    }

    result = compute_drawdown(
        pool,
        today_high,
        today_close,
        available_times=available_times,
        decision_time="2026-08-14T03:00:00.000Z",
    )
    # Both close values leak after the decision time -> empty, not fabricated.
    assert result == 0.0
