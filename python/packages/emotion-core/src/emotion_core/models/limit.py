"""Limit-up / limit-down fact model.

Limit-up/down is derived from per-day price limit rules (board + ST status),
never a fixed percentage. The rules live in
packages/contracts/emotion/limit-rules.json — the single source of truth.

P2-R01: prices and limit-rate math use ``Decimal`` and round to the A-share
0.01 CNY tick size (``ROUND_HALF_UP``), never binary float or ``round()``.
This reuses the P1-R02 Decimal precision contract; no separate price model is
introduced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Literal, cast

BoardId = Literal["MAIN", "CHINEXT", "STAR", "BSE"]
EventType = Literal["LIMIT_UP", "LIMIT_DOWN", "SEAL", "BREAK_SEAL", "OPEN_COUNT"]

_RULES_PATH = (
    Path(__file__).resolve().parents[6] / "packages" / "contracts" / "emotion" / "limit-rules.json"
)

# A-share price tick size is 0.01 CNY for every board.
_TICK = Decimal("0.01")


def _load_rules() -> dict[tuple[str, bool], Decimal]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        (str(rule["board"]), bool(rule["st"])): Decimal(str(rule["limitRate"]))
        for rule in cast(list[dict[str, object]], data["rules"])
    }


_RULES = _load_rules()


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _tick_round(value: Decimal) -> Decimal:
    """Round to the 0.01 tick using ROUND_HALF_UP (A-share exchange rule)."""
    return value.quantize(_TICK, rounding=ROUND_HALF_UP)


def limit_rate(board: str, is_st: bool) -> Decimal:
    """The price limit rate for a board and ST status."""
    return _RULES[(board, is_st)]


def limit_up_price(prev_close: Decimal | float, board: str, is_st: bool) -> Decimal:
    """The limit-up price for a board/ST, rounded to the 0.01 tick."""
    base = _to_decimal(prev_close)
    return _tick_round(base * (Decimal("1") + limit_rate(board, is_st)))


def limit_down_price(prev_close: Decimal | float, board: str, is_st: bool) -> Decimal:
    """The limit-down price for a board/ST, rounded to the 0.01 tick."""
    base = _to_decimal(prev_close)
    return _tick_round(base * (Decimal("1") - limit_rate(board, is_st)))


def is_limit_up(
    close: Decimal | float, prev_close: Decimal | float, board: str, is_st: bool
) -> bool:
    """Whether close touches the limit-up price (no price -> no judgement)."""
    base = _to_decimal(prev_close)
    if base <= 0:
        return False
    return _to_decimal(close) >= limit_up_price(base, board, is_st)


def is_limit_down(
    close: Decimal | float, prev_close: Decimal | float, board: str, is_st: bool
) -> bool:
    """Whether close touches the limit-down price (no price -> no judgement)."""
    base = _to_decimal(prev_close)
    if base <= 0:
        return False
    return _to_decimal(close) <= limit_down_price(base, board, is_st)


@dataclass(frozen=True)
class LimitEvent:
    """A single limit-up/limit-down fact."""

    unified_code: str
    exchange: str
    date: str
    event_type: EventType
    timestamp: str
    price: Decimal
    open_count: int = 0


@dataclass(frozen=True)
class LimitPoolSnapshot:
    """A point-in-time snapshot of the limit pool."""

    date: str
    timestamp: str
    limit_up_count: int
    limit_down_count: int
    sealed_count: int
    limit_up_instruments: tuple[str, ...] = ()
    limit_down_instruments: tuple[str, ...] = ()
    first_seal_time: str | None = None
    last_seal_time: str | None = None
    total_open_count: int = 0
