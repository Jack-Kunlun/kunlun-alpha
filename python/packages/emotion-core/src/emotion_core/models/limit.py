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
ExchangeId = Literal["SH", "SZ", "BSE"]
EventType = Literal["LIMIT_UP", "LIMIT_DOWN", "SEAL", "BREAK_SEAL", "OPEN_COUNT"]

_RULES_PATH = (
    Path(__file__).resolve().parents[6] / "packages" / "contracts" / "emotion" / "limit-rules.json"
)


@dataclass(frozen=True)
class _TickRule:
    """Per-exchange tick size and minimum-one-tick adjustment rule.

    Loaded from limit-rules.json ``tickAdjustment`` (versioned, stated
    explicitly per exchange — never inferred from another exchange).
    """

    tick_size: Decimal
    min_tick_adjustment: bool
    price_floor_ticks: int
    source: str


def _load_rules() -> dict[tuple[str, bool], Decimal]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        (str(rule["board"]), bool(rule["st"])): Decimal(str(rule["limitRate"]))
        for rule in cast(list[dict[str, object]], data["rules"])
    }


def _load_tick_rules() -> dict[str, _TickRule]:
    with _RULES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    adjustment = cast(dict[str, object], data["tickAdjustment"])
    exchanges = cast(dict[str, dict[str, object]], adjustment["exchanges"])
    return {
        exchange: _TickRule(
            tick_size=Decimal(str(rule["tickSize"])),
            min_tick_adjustment=bool(rule["minTickAdjustment"]),
            price_floor_ticks=int(cast(int, rule["priceFloorTicks"])),
            source=str(rule["source"]),
        )
        for exchange, rule in exchanges.items()
    }


_RULES = _load_rules()
_TICK_RULES = _load_tick_rules()


def _tick_rule(exchange: str) -> _TickRule:
    """The tick/adjustment rule for an exchange (fail-closed on unknown)."""
    try:
        return _TICK_RULES[exchange]
    except KeyError as exc:
        raise ValueError(f"unknown exchange for tick rule: {exchange!r}") from exc


def _to_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _tick_round(value: Decimal, tick: Decimal) -> Decimal:
    """Round to the given tick using ROUND_HALF_UP (A-share exchange rule)."""
    return value.quantize(tick, rounding=ROUND_HALF_UP)


def limit_rate(board: str, is_st: bool) -> Decimal:
    """The price limit rate for a board and ST status."""
    return _RULES[(board, is_st)]


def limit_up_price(
    prev_close: Decimal | float, board: str, is_st: bool, *, exchange: str = "SH"
) -> Decimal:
    """The limit-up price for a board/ST, rounded to the exchange tick.

    Applies the minimum-one-tick adjustment (SSE 3.3.17 / SZSE 3.3.19): if the
    rounded price would differ from ``prev_close`` by less than one tick, the
    limit-up price is ``prev_close + one tick``.
    """
    base = _to_decimal(prev_close)
    rule = _tick_rule(exchange)
    tick = rule.tick_size
    rounded = _tick_round(base * (Decimal("1") + limit_rate(board, is_st)), tick)
    if rule.min_tick_adjustment and rounded - base < tick:
        return base + tick
    return rounded


def limit_down_price(
    prev_close: Decimal | float, board: str, is_st: bool, *, exchange: str = "SH"
) -> Decimal:
    """The limit-down price for a board/ST, rounded to the exchange tick.

    Applies the minimum-one-tick adjustment (SSE 3.3.17 / SZSE 3.3.19): if the
    rounded price would differ from ``prev_close`` by less than one tick, the
    limit-down price is ``prev_close - one tick``. The result is never below the
    exchange price floor (SZSE/BSE: one tick).
    """
    base = _to_decimal(prev_close)
    rule = _tick_rule(exchange)
    tick = rule.tick_size
    rounded = _tick_round(base * (Decimal("1") - limit_rate(board, is_st)), tick)
    if rule.min_tick_adjustment and base - rounded < tick:
        rounded = base - tick
    floor = tick * rule.price_floor_ticks
    if rounded < floor:
        return floor
    return rounded


def is_limit_up(
    close: Decimal | float,
    prev_close: Decimal | float,
    board: str,
    is_st: bool,
    *,
    exchange: str = "SH",
) -> bool:
    """Whether close touches the limit-up price (no price -> no judgement)."""
    base = _to_decimal(prev_close)
    if base <= 0:
        return False
    return _to_decimal(close) >= limit_up_price(base, board, is_st, exchange=exchange)


def is_limit_down(
    close: Decimal | float,
    prev_close: Decimal | float,
    board: str,
    is_st: bool,
    *,
    exchange: str = "SH",
) -> bool:
    """Whether close touches the limit-down price (no price -> no judgement)."""
    base = _to_decimal(prev_close)
    if base <= 0:
        return False
    return _to_decimal(close) <= limit_down_price(base, board, is_st, exchange=exchange)


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
class SnapshotObservationProvenance:
    """Provenance of one observation a snapshot actually used.

    Records the revision and source attribution of the winning observation for
    an instrument at the snapshot ``as_of``, so a point-in-time snapshot is
    auditable back to the exact data that produced it.
    """

    unified_code: str
    event_time: str
    available_time: str
    revision: int
    source: str
    source_version: str
    evidence_id: str


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
    provenance: tuple[SnapshotObservationProvenance, ...] = ()
