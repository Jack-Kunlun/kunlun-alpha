"""Limit pool calculator.

Pure functions turn normalized minute bars into limit-up/down facts. A batch
function and an incremental aggregator share the same per-instrument state
machine, so replay of historical bars matches real-time processing. Bars are
sorted by timestamp first, so out-of-order input is corrected.

P2-R01: the incremental aggregator buffers bars by ``(code, timestamp)`` and
recomputes the canonical event list from the sorted buffer, so out-of-order
arrivals, duplicate timestamps and corrections never double-count or drift.
First/last seal times and total open counts are tracked for the snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from market_core.models.validators import Bar

from emotion_core.models import LimitEvent, LimitPoolSnapshot, is_limit_down, is_limit_up


@dataclass(frozen=True)
class InstrumentContext:
    """Reference data needed to judge a limit-up/down."""

    unified_code: str
    prev_close: Decimal
    board: str
    is_st: bool


@dataclass
class _InstrumentState:
    """Mutable per-instrument state for the limit state machine."""

    status: str = "normal"  # normal | sealed | opened | limit_down
    open_count: int = 0
    first_seal_time: str | None = None
    last_seal_time: str | None = None


def _sorted_bars(bars: list[Bar]) -> list[Bar]:
    return sorted(bars, key=lambda b: (b.timestamp, b.unified_code))


def _process_bar(
    bar: Bar,
    context: InstrumentContext,
    state: _InstrumentState,
) -> list[LimitEvent]:
    """Advance the per-instrument state machine by one bar.

    Limit-up and limit-down are mutually exclusive (a bar cannot be both). The
    state machine emits LIMIT_UP / SEAL / BREAK_SEAL / LIMIT_DOWN facts and
    tracks first/last seal times and the open count.
    """
    code = bar.unified_code
    events: list[LimitEvent] = []
    at_up = is_limit_up(bar.close, context.prev_close, context.board, context.is_st)
    at_down = is_limit_down(bar.close, context.prev_close, context.board, context.is_st)

    if at_up:
        if state.status in ("normal", "limit_down"):
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
            state.status = "sealed"
            state.open_count = 0
            if state.first_seal_time is None:
                state.first_seal_time = bar.timestamp
            state.last_seal_time = bar.timestamp
        elif state.status == "opened":
            state.open_count += 1
            events.append(
                LimitEvent(
                    unified_code=code,
                    exchange=bar.exchange,
                    date=bar.date,
                    event_type="SEAL",
                    timestamp=bar.timestamp,
                    price=bar.close,
                    open_count=state.open_count,
                )
            )
            state.status = "sealed"
            state.last_seal_time = bar.timestamp
    elif at_down:
        if state.status != "limit_down":
            events.append(
                LimitEvent(
                    unified_code=code,
                    exchange=bar.exchange,
                    date=bar.date,
                    event_type="LIMIT_DOWN",
                    timestamp=bar.timestamp,
                    price=bar.close,
                )
            )
            state.status = "limit_down"
    else:
        if state.status == "sealed":
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
            state.status = "opened"
        elif state.status == "limit_down":
            # Price moved off the limit-down price; the instrument leaves the pool.
            state.status = "normal"

    return events


def compute_limit_facts(
    bars: list[Bar], contexts: dict[str, InstrumentContext]
) -> list[LimitEvent]:
    """Compute limit facts from a (possibly out-of-order) bar sequence.

    Deterministic: the same input always yields the same events, independent of
    input order, because bars are sorted by timestamp first.
    """
    events: list[LimitEvent] = []
    states: dict[str, _InstrumentState] = {}

    for bar in _sorted_bars(bars):
        context = contexts.get(bar.unified_code)
        if context is None:
            continue
        state = states.setdefault(bar.unified_code, _InstrumentState())
        events.extend(_process_bar(bar, context, state))

    return events


class LimitPoolAggregator:
    """Incremental aggregator that replays bars one at a time.

    Bars are buffered by ``(code, timestamp)`` — last write wins, so duplicate
    timestamps are idempotent and corrections replace the prior observation.
    The canonical event list is recomputed from the sorted buffer on every
    feed, so out-of-order arrivals produce the same result as batch processing.
    """

    def __init__(self, contexts: dict[str, InstrumentContext]) -> None:
        self._contexts = contexts
        self._buffer: dict[tuple[str, str], Bar] = {}
        self._last_events: list[LimitEvent] = []

    def feed(self, bar: Bar) -> list[LimitEvent]:
        """Buffer the bar and return the events new or corrected since last feed."""
        self._buffer[(bar.unified_code, bar.timestamp)] = bar
        new_events = compute_limit_facts(list(self._buffer.values()), self._contexts)
        diverge = _divergence_point(self._last_events, new_events)
        delta = new_events[diverge:]
        self._last_events = new_events
        return delta

    def events(self) -> list[LimitEvent]:
        """The canonical event list recomputed from the buffered bars."""
        return compute_limit_facts(list(self._buffer.values()), self._contexts)

    def snapshot(self, date: str, timestamp: str) -> LimitPoolSnapshot:
        states = self._compute_states()
        limit_up = [code for code, s in states.items() if s.status == "sealed"]
        limit_down = [code for code, s in states.items() if s.status == "limit_down"]
        first_seal_times = [s.first_seal_time for s in states.values() if s.first_seal_time]
        last_seal_times = [s.last_seal_time for s in states.values() if s.last_seal_time]
        first_seal = min(first_seal_times) if first_seal_times else None
        last_seal = max(last_seal_times) if last_seal_times else None
        total_open = sum(s.open_count for s in states.values())
        return LimitPoolSnapshot(
            date=date,
            timestamp=timestamp,
            limit_up_count=len(limit_up),
            limit_down_count=len(limit_down),
            sealed_count=len(limit_up),
            limit_up_instruments=tuple(limit_up),
            limit_down_instruments=tuple(limit_down),
            first_seal_time=first_seal,
            last_seal_time=last_seal,
            total_open_count=total_open,
        )

    def _compute_states(self) -> dict[str, _InstrumentState]:
        states: dict[str, _InstrumentState] = {}
        for bar in _sorted_bars(list(self._buffer.values())):
            context = self._contexts.get(bar.unified_code)
            if context is None:
                continue
            state = states.setdefault(bar.unified_code, _InstrumentState())
            _process_bar(bar, context, state)
        return states


def _divergence_point(old: list[LimitEvent], new: list[LimitEvent]) -> int:
    """Index at which ``new`` first differs from ``old`` (len(old) if equal)."""
    for i, (prev, curr) in enumerate(zip(old, new, strict=False)):
        if prev != curr:
            return i
    return len(old)
