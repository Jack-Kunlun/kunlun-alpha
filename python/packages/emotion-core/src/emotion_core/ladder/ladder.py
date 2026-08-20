"""Board ladder (consecutive limit-up counts) and advancement rates.

Consecutive-board counting walks backwards over a trading-day sequence — never
natural days — so weekends do not break a streak and a suspended day does not
count as a broken board. The snapshot reports the distribution of board counts
and the advancement rate from board N to N+1 (e.g. 1 -> 2).

P2-R01: the snapshot carries an algorithm version and the suspended-day
exclusions that shaped each streak, so results stay auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LADDER_VERSION = "board_ladder_v1"


@dataclass(frozen=True)
class BoardLadderSnapshot:
    """Distribution of consecutive limit-up counts plus advancement rates."""

    date: str
    boards: dict[int, list[str]]
    advancement: dict[int, float]
    exclusions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    version: str = LADDER_VERSION


def consecutive_boards(
    code: str,
    date: str,
    trading_days: list[str],
    limit_up_history: dict[str, dict[str, bool]],
    suspended: dict[str, set[str]] | None = None,
) -> int:
    """The consecutive limit-up count ending on ``date`` for ``code``.

    Walks backwards over the trading-day sequence; suspended days are skipped
    (they do not break the streak) and the first non-limit-up trading day ends
    the streak.
    """
    suspended_days = (suspended or {}).get(code, set())
    history = limit_up_history.get(code, {})
    if date not in trading_days:
        return 0

    count = 0
    index = trading_days.index(date)
    for day in reversed(trading_days[: index + 1]):
        if day in suspended_days:
            continue
        if history.get(day):
            count += 1
        else:
            break
    return count


def compute_board_ladder(
    date: str,
    trading_days: list[str],
    limit_up_history: dict[str, dict[str, bool]],
    suspended: dict[str, set[str]] | None = None,
) -> BoardLadderSnapshot:
    """Compute the board ladder and advancement rates for ``date``.

    ``trading_days`` is the ascending trading-day sequence ending at ``date``.
    ``limit_up_history[code][day]`` is whether ``code`` was limit-up that day.
    """
    codes = list(limit_up_history.keys())
    board_counts = {
        code: consecutive_boards(code, date, trading_days, limit_up_history, suspended)
        for code in codes
    }

    # Record, per code, the suspended trading days that fell inside the observed
    # window — these are the exclusions that shaped the streak.
    window = set(trading_days)
    exclusions: dict[str, tuple[str, ...]] = {}
    for code, days in (suspended or {}).items():
        within = tuple(sorted(day for day in days if day in window))
        if within:
            exclusions[code] = within

    boards: dict[int, list[str]] = {}
    for code, count in board_counts.items():
        if count > 0:
            boards.setdefault(count, []).append(code)

    # Advancement: of the codes with N boards yesterday, how many are limit-up today.
    advancement: dict[int, float] = {}
    if len(trading_days) >= 2:
        yesterday = trading_days[-2]
        today = date
        for n in sorted(boards.keys()):
            yesterday_n = [
                code
                for code in codes
                if consecutive_boards(code, yesterday, trading_days, limit_up_history, suspended)
                == n
            ]
            if not yesterday_n:
                continue
            advanced = sum(1 for code in yesterday_n if limit_up_history.get(code, {}).get(today))
            advancement[n] = advanced / len(yesterday_n)

    return BoardLadderSnapshot(
        date=date, boards=boards, advancement=advancement, exclusions=exclusions
    )
