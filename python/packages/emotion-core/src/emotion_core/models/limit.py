"""Limit-up / limit-down fact model.

Limit-up/down is derived from per-day price limit rules (board + ST status),
never a fixed percentage. The rules live in
packages/contracts/emotion/limit-rules.json — the single source of truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

BoardId = Literal["MAIN", "CHINEXT", "STAR", "BSE"]
EventType = Literal["LIMIT_UP", "LIMIT_DOWN", "SEAL", "BREAK_SEAL", "OPEN_COUNT"]

_RULES_PATH = (
    Path(__file__).resolve().parents[6] / "packages" / "contracts" / "emotion" / "limit-rules.json"
)

_EPSILON = 1e-6


def _load_rules() -> dict[tuple[str, bool], float]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        (str(rule["board"]), bool(rule["st"])): cast(float, rule["limitRate"])
        for rule in cast(list[dict[str, object]], data["rules"])
    }


_RULES = _load_rules()


def limit_rate(board: str, is_st: bool) -> float:
    """The price limit rate for a board and ST status."""
    return _RULES[(board, is_st)]


def limit_up_price(prev_close: float, board: str, is_st: bool) -> float:
    """The limit-up price for a board/ST, rounded to 0.01."""
    return round(prev_close * (1 + limit_rate(board, is_st)), 2)


def limit_down_price(prev_close: float, board: str, is_st: bool) -> float:
    """The limit-down price for a board/ST, rounded to 0.01."""
    return round(prev_close * (1 - limit_rate(board, is_st)), 2)


def is_limit_up(close: float, prev_close: float, board: str, is_st: bool) -> bool:
    """Whether close touches the limit-up price (no price -> no judgement)."""
    if prev_close <= 0:
        return False
    return close >= limit_up_price(prev_close, board, is_st) - _EPSILON


def is_limit_down(close: float, prev_close: float, board: str, is_st: bool) -> bool:
    """Whether close touches the limit-down price (no price -> no judgement)."""
    if prev_close <= 0:
        return False
    return close <= limit_down_price(prev_close, board, is_st) + _EPSILON


@dataclass(frozen=True)
class LimitEvent:
    """A single limit-up/limit-down fact."""

    unified_code: str
    exchange: str
    date: str
    event_type: EventType
    timestamp: str
    price: float
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
