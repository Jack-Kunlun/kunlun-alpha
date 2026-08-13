"""Limit pool calculator.

Pure functions turn normalized minute bars into limit-up/down facts. A batch
function and an incremental aggregator produce identical results, so replay of
historical bars matches real-time processing. Bars are sorted by timestamp
first, so out-of-order input is corrected.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_core.models.validators import Bar

from emotion_core.models import LimitEvent, LimitPoolSnapshot, is_limit_up


@dataclass(frozen=True)
class InstrumentContext:
    """Reference data needed to judge a limit-up/down."""

    unified_code: str
    prev_close: float
    board: str
    is_st: bool


def _sorted_bars(bars: list[Bar]) -> list[Bar]:
    return sorted(bars, key=lambda b: b.timestamp)


def compute_limit_facts(
    bars: list[Bar], contexts: dict[str, InstrumentContext]
) -> list[LimitEvent]:
    """Compute limit facts from a (possibly out-of-order) bar sequence.

    Deterministic: the same input always yields the same events, independent of
    input order, because bars are sorted by timestamp first.
    """
    events: list[LimitEvent] = []
    state: dict[str, str] = {}
    open_counts: dict[str, int] = {}

    for bar in _sorted_bars(bars):
        context = contexts.get(bar.unified_code)
        if context is None:
            continue
        code = bar.unified_code
        at_limit_up = is_limit_up(bar.close, context.prev_close, context.board, context.is_st)
        current = state.get(code, "normal")

        if at_limit_up:
            if current == "normal":
                events.append(
                    LimitEvent(
                        unified_code=code,
                        exchange=bar.exchange,
                        date=bar.date,
                        event_type="LIMIT_UP",
                        timestamp=bar.timestamp,
                        price=bar.close,
                    )
                )
                state[code] = "sealed"
                open_counts[code] = 0
            elif current == "opened":
                open_counts[code] += 1
                events.append(
                    LimitEvent(
                        unified_code=code,
                        exchange=bar.exchange,
                        date=bar.date,
                        event_type="SEAL",
                        timestamp=bar.timestamp,
                        price=bar.close,
                        open_count=open_counts[code],
                    )
                )
                state[code] = "sealed"
        elif current == "sealed":
            events.append(
                LimitEvent(
                    unified_code=code,
                    exchange=bar.exchange,
                    date=bar.date,
                    event_type="BREAK_SEAL",
                    timestamp=bar.timestamp,
                    price=bar.close,
                )
            )
            state[code] = "opened"

    return events


class LimitPoolAggregator:
    """Incremental aggregator that replays bars one at a time.

    Feeding the same bars one-by-one produces the same events as
    :func:`compute_limit_facts`, so real-time and replay stay consistent.
    """

    def __init__(self, contexts: dict[str, InstrumentContext]) -> None:
        self._contexts = contexts
        self._state: dict[str, str] = {}
        self._open_counts: dict[str, int] = {}

    def feed(self, bar: Bar) -> list[LimitEvent]:
        return self._feed(bar)

    def _feed(self, bar: Bar) -> list[LimitEvent]:
        context = self._contexts.get(bar.unified_code)
        if context is None:
            return []
        code = bar.unified_code
        at_limit_up = is_limit_up(bar.close, context.prev_close, context.board, context.is_st)
        current = self._state.get(code, "normal")
        events: list[LimitEvent] = []

        if at_limit_up:
            if current == "normal":
                events.append(
                    LimitEvent(
                        unified_code=code,
                        exchange=bar.exchange,
                        date=bar.date,
                        event_type="LIMIT_UP",
                        timestamp=bar.timestamp,
                        price=bar.close,
                    )
                )
                self._state[code] = "sealed"
                self._open_counts[code] = 0
            elif current == "opened":
                self._open_counts[code] += 1
                events.append(
                    LimitEvent(
                        unified_code=code,
                        exchange=bar.exchange,
                        date=bar.date,
                        event_type="SEAL",
                        timestamp=bar.timestamp,
                        price=bar.close,
                        open_count=self._open_counts[code],
                    )
                )
                self._state[code] = "sealed"
        elif current == "sealed":
            events.append(
                LimitEvent(
                    unified_code=code,
                    exchange=bar.exchange,
                    date=bar.date,
                    event_type="BREAK_SEAL",
                    timestamp=bar.timestamp,
                    price=bar.close,
                )
            )
            self._state[code] = "opened"

        return events

    def snapshot(self, date: str, timestamp: str) -> LimitPoolSnapshot:
        limit_up = [code for code, s in self._state.items() if s == "sealed"]
        return LimitPoolSnapshot(
            date=date,
            timestamp=timestamp,
            limit_up_count=len(limit_up),
            limit_down_count=0,
            sealed_count=len(limit_up),
            limit_up_instruments=tuple(limit_up),
        )
