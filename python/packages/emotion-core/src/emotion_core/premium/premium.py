"""Yesterday-limit premium and loss-making effect.

Measures how yesterday's limit-up (or multi-board) pool performs today. The
sample is unbiased: suspended instruments (no data), one-word boards (opening
already at limit, so no reasonable entry) and instruments whose observation is
not yet available at the decision time are excluded, and every exclusion is
recorded with a reason. Only fields available at the decision time are used —
never a same-day close/high that leaks after the observation time.

P2-R01: ``decision_time`` + per-instrument ``available_times`` enforce
point-in-time correctness; results carry a version and per-instrument exclusion
reasons for auditability.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PREMIUM_VERSION = "premium_v1"


@dataclass(frozen=True)
class PremiumResult:
    """Premium / loss-making effect for a pool of yesterday's limit-ups."""

    sample_size: int
    average_premium: float
    win_rate: float
    exclusion_reasons: dict[str, str] = field(default_factory=dict)
    version: str = PREMIUM_VERSION


def _available_at(
    code: str,
    available_times: dict[str, str] | None,
    decision_time: str | None,
) -> bool:
    """Whether ``code``'s observation is available at ``decision_time``.

    Availability is unconstrained when the caller supplies no timing context.
    Otherwise an instrument is available only if its ``available_time`` is at or
    before ``decision_time`` (ISO 8601 strings compare lexicographically when
    normalized to the same UTC layout).
    """
    if decision_time is None or available_times is None:
        return True
    available_time = available_times.get(code)
    if available_time is None:
        return False
    return available_time <= decision_time


def compute_premium(
    yesterday_pool: list[str],
    yesterday_close: dict[str, float],
    today_price: dict[str, float],
    *,
    suspended: set[str] | None = None,
    one_word_board: set[str] | None = None,
    available_times: dict[str, str] | None = None,
    decision_time: str | None = None,
) -> PremiumResult:
    """Average premium of yesterday's pool at today's observation price.

    ``today_price`` may be the open price (open-based) or close price
    (close-based); the caller decides which field to pass. Suspended,
    one-word-board and not-yet-available instruments are excluded so the sample
    is unbiased and point-in-time correct.
    """
    suspended = suspended or set()
    one_word_board = one_word_board or set()

    premiums: list[float] = []
    wins = 0
    exclusion_reasons: dict[str, str] = {}
    for code in yesterday_pool:
        if code in suspended:
            exclusion_reasons[code] = "suspended"
            continue
        if code in one_word_board:
            exclusion_reasons[code] = "one_word_board"
            continue
        if not _available_at(code, available_times, decision_time):
            exclusion_reasons[code] = "unavailable_at_decision_time"
            continue
        prev_close = yesterday_close.get(code)
        price = today_price.get(code)
        if prev_close is None or price is None or prev_close <= 0:
            exclusion_reasons[code] = "missing_price"
            continue
        premium = price / prev_close - 1.0
        premiums.append(premium)
        if premium > 0:
            wins += 1

    if not premiums:
        return PremiumResult(
            sample_size=0,
            average_premium=0.0,
            win_rate=0.0,
            exclusion_reasons=exclusion_reasons,
        )

    return PremiumResult(
        sample_size=len(premiums),
        average_premium=sum(premiums) / len(premiums),
        win_rate=wins / len(premiums),
        exclusion_reasons=exclusion_reasons,
    )


def compute_drawdown(
    pool: list[str],
    today_high: dict[str, float],
    today_close: dict[str, float],
    *,
    suspended: set[str] | None = None,
    available_times: dict[str, str] | None = None,
    decision_time: str | None = None,
) -> float:
    """Average high-to-close drawdown of a pool (loss-making effect).

    Instruments that are suspended or whose close is not yet available at the
    decision time are excluded, so the measure never uses leaked same-day data.
    """
    suspended = suspended or set()
    drawdowns: list[float] = []
    for code in pool:
        if code in suspended:
            continue
        if not _available_at(code, available_times, decision_time):
            continue
        high = today_high.get(code)
        close = today_close.get(code)
        if high is None or close is None or high <= 0:
            continue
        drawdowns.append((high - close) / high)

    if not drawdowns:
        return 0.0
    return sum(drawdowns) / len(drawdowns)
