"""Limit pool calculator.

Pure functions turn normalized minute bars into limit-up/down facts. A batch
function and an incremental aggregator share the same per-instrument state
machine, so replay of historical bars matches real-time processing. Bars are
ordered by their canonical UTC :class:`~emotion_core.pit.Instant`, so
out-of-order input and mixed timezone representations of the same moment are
corrected and deduped identically.

P2-R01 (round 2):

* Ordering, identity keys, dedupe and first/last-seal use a normalized
  :class:`Instant`, never a raw timestamp string.
* ``feed`` returns an explicit :class:`LimitPoolCorrection` envelope (upserts +
  retractions + monotonically increasing revision), so an incremental consumer
  can always reconstruct the canonical event list — even when a correction
  empties the tail — without retaining stale facts.
* ``snapshot(as_of, trading_date)`` is point-in-time: it only considers bars for
  that ``trading_date`` whose instant is at or before ``as_of``, so no future
  data and no cross-day state ever leak into a historical snapshot.
* A sealed instrument that flips to limit-down emits BREAK_SEAL before
  LIMIT_DOWN and preserves the accumulated open count.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from market_core.models.validators import Bar

from emotion_core.models import LimitEvent, LimitPoolSnapshot, is_limit_down, is_limit_up
from emotion_core.pit import Instant


@dataclass(frozen=True)
class InstrumentContext:
    """Reference data needed to judge a limit-up/down."""

    unified_code: str
    prev_close: Decimal
    board: str
    is_st: bool


@dataclass(frozen=True)
class LimitPoolCorrection:
    """The revision an incremental ``feed`` produced.

    ``upserts`` are events that are now canonical and new-or-changed since the
    previous feed; ``retractions`` are previously emitted events that are no
    longer canonical and must be dropped by the consumer. ``revision`` increases
    by one per feed so consumers can order and deduplicate corrections.
    """

    upserts: list[LimitEvent]
    retractions: list[LimitEvent]
    revision: int


@dataclass
class _InstrumentState:
    """Mutable per-instrument state for the limit state machine."""

    status: str = "normal"  # normal | sealed | opened | limit_down
    open_count: int = 0
    first_seal_time: Instant | None = None
    last_seal_time: Instant | None = None


def _sorted_bars(bars: list[Bar]) -> list[Bar]:
    """Order bars by canonical instant, then code, for deterministic replay."""
    return sorted(bars, key=lambda b: (Instant.parse(b.timestamp), b.unified_code))


def _process_bar(
    bar: Bar,
    context: InstrumentContext,
    state: _InstrumentState,
) -> list[LimitEvent]:
    """Advance the per-instrument state machine by one bar.

    Limit-up and limit-down are mutually exclusive (a bar cannot be both). The
    state machine emits LIMIT_UP / SEAL / BREAK_SEAL / LIMIT_DOWN facts and
    tracks first/last seal times and the open count. A sealed instrument that
    flips directly to limit-down emits BREAK_SEAL (preserving the open count)
    before LIMIT_DOWN.
    """
    code = bar.unified_code
    instant = Instant.parse(bar.timestamp)
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
                state.first_seal_time = instant
            state.last_seal_time = instant
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
            state.last_seal_time = instant
    elif at_down:
        if state.status == "sealed":
            # The seal opened on the way to limit-down; record BREAK_SEAL first
            # so the accumulated open count is not lost.
            events.append(
                LimitEvent(
                    unified_code=code,
                    exchange=bar.exchange,
                    date=bar.date,
                    event_type="BREAK_SEAL",
                    timestamp=bar.timestamp,
                    price=bar.close,
                    open_count=state.open_count,
                )
            )
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
                    open_count=state.open_count,
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
    input order or timezone representation, because bars are ordered by their
    canonical instant first.
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

    Bars are buffered by ``(code, canonical-instant)`` — last write wins, so
    duplicate timestamps and mixed timezone representations of the same moment
    are idempotent and corrections replace the prior observation. The canonical
    event list is recomputed from the sorted buffer on every feed, and ``feed``
    returns the :class:`LimitPoolCorrection` (upserts + retractions + revision)
    needed to reconcile a downstream consumer.
    """

    def __init__(self, contexts: dict[str, InstrumentContext]) -> None:
        self._contexts = contexts
        self._buffer: dict[tuple[str, str], Bar] = {}
        self._last_events: list[LimitEvent] = []
        self._revision = 0

    def feed(self, bar: Bar) -> LimitPoolCorrection:
        """Buffer the bar and return the correction envelope since last feed."""
        key = (bar.unified_code, Instant.parse(bar.timestamp).isoformat())
        self._buffer[key] = bar
        new_events = compute_limit_facts(list(self._buffer.values()), self._contexts)
        diverge = _divergence_point(self._last_events, new_events)
        retractions = self._last_events[diverge:]
        upserts = new_events[diverge:]
        self._last_events = new_events
        self._revision += 1
        return LimitPoolCorrection(
            upserts=upserts,
            retractions=retractions,
            revision=self._revision,
        )

    def events(self) -> list[LimitEvent]:
        """The canonical event list recomputed from the buffered bars."""
        return compute_limit_facts(list(self._buffer.values()), self._contexts)

    def snapshot(self, *, as_of: str, trading_date: str) -> LimitPoolSnapshot:
        """A point-in-time snapshot of the pool for one trading day.

        Only bars whose ``date`` equals ``trading_date`` and whose instant is at
        or before ``as_of`` are considered, so the snapshot never includes
        future data and never carries state across trading days.
        """
        cutoff = Instant.parse(as_of)
        states = self._compute_states(trading_date=trading_date, cutoff=cutoff)
        limit_up = sorted(code for code, s in states.items() if s.status == "sealed")
        limit_down = sorted(code for code, s in states.items() if s.status == "limit_down")
        first_seal_times = [s.first_seal_time for s in states.values() if s.first_seal_time]
        last_seal_times = [s.last_seal_time for s in states.values() if s.last_seal_time]
        first_seal = min(first_seal_times) if first_seal_times else None
        last_seal = max(last_seal_times) if last_seal_times else None
        total_open = sum(s.open_count for s in states.values())
        return LimitPoolSnapshot(
            date=trading_date,
            timestamp=as_of,
            limit_up_count=len(limit_up),
            limit_down_count=len(limit_down),
            sealed_count=len(limit_up),
            limit_up_instruments=tuple(limit_up),
            limit_down_instruments=tuple(limit_down),
            first_seal_time=first_seal.isoformat() if first_seal else None,
            last_seal_time=last_seal.isoformat() if last_seal else None,
            total_open_count=total_open,
        )

    def _compute_states(self, *, trading_date: str, cutoff: Instant) -> dict[str, _InstrumentState]:
        states: dict[str, _InstrumentState] = {}
        for bar in _sorted_bars(list(self._buffer.values())):
            if bar.date != trading_date:
                continue
            if Instant.parse(bar.timestamp) > cutoff:
                continue
            context = self._contexts.get(bar.unified_code)
            if context is None:
                continue
            state = states.setdefault(bar.unified_code, _InstrumentState())
            _process_bar(bar, context, state)
        return states


def _divergence_point(old: list[LimitEvent], new: list[LimitEvent]) -> int:
    """Index at which ``new`` first differs from ``old`` (len if one is a prefix)."""
    for i, (prev, curr) in enumerate(zip(old, new, strict=False)):
        if prev != curr:
            return i
    return min(len(old), len(new))
