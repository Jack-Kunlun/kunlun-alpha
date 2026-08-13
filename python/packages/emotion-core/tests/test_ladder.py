"""Board ladder tests.

Covers consecutive board counting across trading days (not natural days),
suspension not breaking a streak, broken streaks, and advancement rates.
"""

from __future__ import annotations

from emotion_core.ladder import compute_board_ladder, consecutive_boards

# Trading days: Mon-Fri, skipping the weekend (natural-day continuity is not
# assumed anywhere).
TRADING_DAYS = [
    "2026-08-10",  # Mon
    "2026-08-11",  # Tue
    "2026-08-12",  # Wed
    "2026-08-13",  # Thu
    "2026-08-14",  # Fri
]


def test_consecutive_boards_across_weekend() -> None:
    history = {
        "A": {"2026-08-13": True, "2026-08-14": True},
    }
    # Two consecutive limit-ups, even though the input only has two days.
    assert consecutive_boards("A", "2026-08-14", TRADING_DAYS, history) == 2


def test_suspended_day_does_not_break_streak() -> None:
    history = {
        "A": {"2026-08-12": True, "2026-08-14": True},
    }
    suspended = {"A": {"2026-08-13"}}  # suspended, not a broken board
    assert consecutive_boards("A", "2026-08-14", TRADING_DAYS, history, suspended) == 2


def test_broken_board_ends_streak() -> None:
    history = {
        "A": {"2026-08-13": False, "2026-08-14": True},
    }
    # 08-13 was a trading day without a limit-up -> streak restarts.
    assert consecutive_boards("A", "2026-08-14", TRADING_DAYS, history) == 1


def test_new_stock_starts_at_one_board() -> None:
    history = {"A": {"2026-08-14": True}}
    assert consecutive_boards("A", "2026-08-14", TRADING_DAYS, history) == 1


def test_ladder_distribution_and_advancement() -> None:
    history = {
        "A": {"2026-08-12": True, "2026-08-13": True, "2026-08-14": True},  # 3 boards
        "B": {"2026-08-13": True, "2026-08-14": False},  # broke today
        "C": {"2026-08-13": True, "2026-08-14": True},  # 2 boards
        "D": {"2026-08-14": True},  # 1 board, new
    }
    snapshot = compute_board_ladder("2026-08-14", TRADING_DAYS, history)

    assert snapshot.boards[3] == ["A"]
    assert snapshot.boards[2] == ["C"]
    assert snapshot.boards[1] == ["D"]
    # Yesterday: A at 2 boards, B and C at 1 board.
    # A advanced (1/1); C advanced but B broke (1/2).
    assert abs(snapshot.advancement[2] - 1.0) < 1e-9
    assert abs(snapshot.advancement[1] - 0.5) < 1e-9
