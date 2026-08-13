"""Yesterday-limit premium and loss-making effect.

Measures how yesterday's limit-up (or multi-board) pool performs today. The
sample is unbiased: suspended instruments (no data) and one-word boards
(opening already at limit, so no reasonable entry) are excluded, and the
sample size is always reported. Only fields available at the observation time
are used — never same-day close for an open-based measure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PremiumResult:
    """Premium / loss-making effect for a pool of yesterday's limit-ups."""

    sample_size: int
    average_premium: float
    win_rate: float


def compute_premium(
    yesterday_pool: list[str],
    yesterday_close: dict[str, float],
    today_price: dict[str, float],
    *,
    suspended: set[str] | None = None,
    one_word_board: set[str] | None = None,
) -> PremiumResult:
    """Average premium of yesterday's pool at today's observation price.

    ``today_price`` may be the open price (open-based) or close price
    (close-based); the caller decides which field to pass. Suspended and
    one-word-board instruments are excluded so the sample is unbiased.
    """
    suspended = suspended or set()
    one_word_board = one_word_board or set()

    premiums: list[float] = []
    wins = 0
    for code in yesterday_pool:
        if code in suspended or code in one_word_board:
            continue
        prev_close = yesterday_close.get(code)
        price = today_price.get(code)
        if prev_close is None or price is None or prev_close <= 0:
            continue
        premium = price / prev_close - 1.0
        premiums.append(premium)
        if premium > 0:
            wins += 1

    if not premiums:
        return PremiumResult(sample_size=0, average_premium=0.0, win_rate=0.0)

    return PremiumResult(
        sample_size=len(premiums),
        average_premium=sum(premiums) / len(premiums),
        win_rate=wins / len(premiums),
    )


def compute_drawdown(
    pool: list[str],
    today_high: dict[str, float],
    today_close: dict[str, float],
    *,
    suspended: set[str] | None = None,
) -> float:
    """Average high-to-close drawdown of a pool (loss-making effect)."""
    suspended = suspended or set()
    drawdowns: list[float] = []
    for code in pool:
        if code in suspended:
            continue
        high = today_high.get(code)
        close = today_close.get(code)
        if high is None or close is None or high <= 0:
            continue
        drawdowns.append((high - close) / high)

    if not drawdowns:
        return 0.0
    return sum(drawdowns) / len(drawdowns)
