"""Limit pool calculator.

Pure functions turn normalized minute bars into limit-up/down facts. A batch
function and an incremental aggregator share a single canonicalization of
typed, revisable observations, so replay of historical observations matches
real-time processing regardless of arrival order.

P2-R01 (round 3):

* Observations are typed :class:`LimitBarObservation` values carrying the bar,
  its canonical ``event_time`` / ``available_time`` :class:`Instant`, a
  non-negative ``revision`` and provenance (source / source_version /
  evidence_id). A bare :class:`Bar` is accepted for backward compatibility and
  wrapped as ``revision 0`` with ``available_time == event_time``.
* The observation identity is ``(trading_date, unified_code, canonical
  event_time)``. :func:`canonicalize_observations` applies the revision rules
  (higher revision wins; same revision + same payload is idempotent; same
  revision + different payload is a :class:`RevisionConflictError`) and never
  depends on arrival order. Batch, ``events()``, ``feed`` and ``snapshot`` all
  go through this one function.
* The per-instrument state machine is isolated per ``(trading_date,
  unified_code)`` and reset to normal each trading day, so two consecutive
  limit-up days each emit their own LIMIT_UP and open_count / sealed /
  limit_down never inherit across days.
* ``feed`` returns an explicit :class:`LimitPoolCorrection` envelope (upserts +
  retractions + monotonically increasing revision) recomputed from the whole
  canonical buffer, so a non-tail correction cascades and no stale fact is
  retained downstream.
* A sealed instrument that flips to limit-down emits BREAK_SEAL before
  LIMIT_DOWN and preserves the accumulated open count.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from market_core.models.validators import Bar

from emotion_core.models import (
    LimitEvent,
    LimitPoolSnapshot,
    SnapshotObservationProvenance,
    is_limit_down,
    is_limit_up,
)
from emotion_core.pit import Instant


class RevisionConflictError(Exception):
    """Two observations share an identity and revision but differ in payload.

    The winner cannot be decided without depending on arrival order, so the
    canonicalization fails closed rather than silently picking one.
    """


def _as_instant(value: object) -> Instant:
    """Normalize an ISO string (or pass through an existing :class:`Instant`)."""
    if isinstance(value, Instant):
        return value
    return Instant.parse(value)


@dataclass(frozen=True)
class InstrumentContext:
    """Reference data needed to judge a limit-up/down."""

    unified_code: str
    prev_close: Decimal
    board: str
    is_st: bool


@dataclass(frozen=True)
class LimitBarObservation:
    """A typed, revisable observation of one minute bar.

    ``event_time`` is when the bar happened; ``available_time`` is when the
    observation became knowable (never before the event). ``revision`` is a
    non-negative integer; a higher revision supersedes a lower one for the same
    identity. Provenance (``source`` / ``source_version`` / ``evidence_id``) is
    carried so a snapshot can record exactly which observation it used.

    The identity is ``(bar.date, bar.unified_code, event_time)`` where
    ``event_time`` is the canonical UTC :class:`Instant`.
    """

    bar: Bar
    event_time: Instant
    available_time: Instant
    revision: int = 0
    source: str = ""
    source_version: str = ""
    evidence_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", _as_instant(self.event_time))
        object.__setattr__(self, "available_time", _as_instant(self.available_time))
        if self.revision < 0:
            raise ValueError("revision must be a non-negative integer")
        if self.event_time > self.available_time:
            raise ValueError("event_time must be <= available_time")

    @property
    def identity(self) -> tuple[str, str, str]:
        """Observation identity: (trading_date, unified_code, canonical event_time)."""
        return (self.bar.date, self.bar.unified_code, self.event_time.isoformat())

    @property
    def payload(self) -> Bar:
        """The payload compared for idempotency / conflict at the same revision."""
        return self.bar


def _as_observation(item: Bar | LimitBarObservation) -> LimitBarObservation:
    """Wrap a bare :class:`Bar` as a ``revision 0`` observation (compat path)."""
    if isinstance(item, LimitBarObservation):
        return item
    instant = Instant.parse(item.timestamp)
    return LimitBarObservation(
        bar=item,
        event_time=instant,
        available_time=instant,
        revision=0,
    )


def canonicalize_observations(
    observations: Sequence[Bar | LimitBarObservation],
    *,
    as_of: Instant | None = None,
) -> list[LimitBarObservation]:
    """Reduce observations to the canonical winner per identity, order-independent.

    Revision rules (independent of arrival order):

    * a higher revision wins over a lower one for the same identity;
    * the same revision with the same payload is idempotent;
    * the same revision with a different payload raises
      :class:`RevisionConflictError`.

    When ``as_of`` is given, observations are first filtered to those already
    available (``available_time <= as_of``) *before* the revision winner is
    chosen, so a snapshot uses the highest revision available at the decision
    time and a not-yet-available later correction never wins.

    The result is sorted by ``(event_time, unified_code)`` so downstream replay
    is deterministic.
    """
    winners: dict[tuple[str, str, str], LimitBarObservation] = {}
    for raw in observations:
        obs = _as_observation(raw)
        if as_of is not None and obs.available_time > as_of:
            continue  # not yet available at the decision time
        key = obs.identity
        current = winners.get(key)
        if current is None or obs.revision > current.revision:
            winners[key] = obs
        elif obs.revision == current.revision and obs.payload != current.payload:
            raise RevisionConflictError(
                f"conflicting observations for {key!r} at revision {obs.revision}"
            )
        # revision < current.revision, or equal-and-identical: keep current.
    return sorted(winners.values(), key=lambda o: (o.event_time, o.bar.unified_code))


@dataclass
class _InstrumentState:
    """Mutable per-instrument state for the limit state machine."""

    status: str = "normal"  # normal | sealed | opened | limit_down
    open_count: int = 0
    first_seal_time: Instant | None = None
    last_seal_time: Instant | None = None


def _process_bar(
    obs: LimitBarObservation,
    context: InstrumentContext,
    state: _InstrumentState,
) -> list[LimitEvent]:
    """Advance the per-instrument state machine by one observation.

    Limit-up and limit-down are mutually exclusive (a bar cannot be both). The
    state machine emits LIMIT_UP / SEAL / BREAK_SEAL / LIMIT_DOWN facts and
    tracks first/last seal times and the open count. A sealed instrument that
    flips directly to limit-down emits BREAK_SEAL (preserving the open count)
    before LIMIT_DOWN.
    """
    bar = obs.bar
    code = bar.unified_code
    instant = obs.event_time
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


def _replay(
    canonical: Sequence[LimitBarObservation], contexts: dict[str, InstrumentContext]
) -> list[LimitEvent]:
    """Replay canonical observations, isolating state per (trading_date, code)."""
    events: list[LimitEvent] = []
    states: dict[tuple[str, str], _InstrumentState] = {}
    for obs in canonical:
        context = contexts.get(obs.bar.unified_code)
        if context is None:
            continue
        day_key = (obs.bar.date, obs.bar.unified_code)
        state = states.setdefault(day_key, _InstrumentState())
        events.extend(_process_bar(obs, context, state))
    return events


def compute_limit_facts(
    bars: Sequence[Bar | LimitBarObservation], contexts: dict[str, InstrumentContext]
) -> list[LimitEvent]:
    """Compute limit facts from a (possibly out-of-order) observation sequence.

    Deterministic: the same input always yields the same events, independent of
    input order, timezone representation or arrival order, because observations
    are canonicalized (revision winner + identity dedup) first and state is
    isolated per trading day.
    """
    canonical = canonicalize_observations(bars)
    return _replay(canonical, contexts)


class LimitPoolAggregator:
    """Incremental aggregator that replays observations one at a time.

    Observations are buffered by identity ``(trading_date, unified_code,
    canonical event_time)``. The canonical winner per identity is recomputed on
    every feed via :func:`canonicalize_observations`, so a non-tail correction
    cascades and duplicate/lower revisions are ignored. ``feed`` returns the
    :class:`LimitPoolCorrection` (upserts + retractions + revision) needed to
    reconcile a downstream consumer.
    """

    def __init__(self, contexts: dict[str, InstrumentContext]) -> None:
        self._contexts = contexts
        self._buffer: list[LimitBarObservation] = []
        self._last_events: list[LimitEvent] = []
        self._revision = 0

    def feed(self, item: Bar | LimitBarObservation) -> LimitPoolCorrection:
        """Buffer the observation and return the correction envelope since last feed."""
        self._buffer.append(_as_observation(item))
        canonical = canonicalize_observations(list(self._buffer))
        new_events = _replay(canonical, self._contexts)
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
        """The canonical event list recomputed from the buffered observations."""
        return _replay(canonicalize_observations(list(self._buffer)), self._contexts)

    def snapshot(self, *, as_of: str, trading_date: str) -> LimitPoolSnapshot:
        """A point-in-time snapshot of the pool for one trading day.

        Point-in-time on both axes: only observations for ``trading_date`` whose
        ``event_time <= as_of`` AND ``available_time <= as_of`` are considered.
        The revision winner is chosen *after* the availability filter, so the
        snapshot uses the highest revision available at ``as_of`` and a
        not-yet-available later correction never rewrites it. The snapshot
        records the provenance of every observation it actually used.
        """
        cutoff = Instant.parse(as_of)
        states, used = self._compute_states(trading_date=trading_date, cutoff=cutoff)
        limit_up = sorted(code for code, s in states.items() if s.status == "sealed")
        limit_down = sorted(code for code, s in states.items() if s.status == "limit_down")
        first_seal_times = [s.first_seal_time for s in states.values() if s.first_seal_time]
        last_seal_times = [s.last_seal_time for s in states.values() if s.last_seal_time]
        first_seal = min(first_seal_times) if first_seal_times else None
        last_seal = max(last_seal_times) if last_seal_times else None
        total_open = sum(s.open_count for s in states.values())
        provenance = tuple(
            SnapshotObservationProvenance(
                unified_code=obs.bar.unified_code,
                event_time=obs.event_time.isoformat(),
                available_time=obs.available_time.isoformat(),
                revision=obs.revision,
                source=obs.source,
                source_version=obs.source_version,
                evidence_id=obs.evidence_id,
            )
            for obs in used
        )
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
            provenance=provenance,
        )

    def _compute_states(
        self, *, trading_date: str, cutoff: Instant
    ) -> tuple[dict[str, _InstrumentState], list[LimitBarObservation]]:
        # Point-in-time on both axes: filter to observations available at the
        # cutoff BEFORE choosing the revision winner, then keep only this
        # trading day's observations whose event_time is at or before the cutoff.
        states: dict[str, _InstrumentState] = {}
        used: list[LimitBarObservation] = []
        canonical = canonicalize_observations(list(self._buffer), as_of=cutoff)
        for obs in canonical:
            bar = obs.bar
            if bar.date != trading_date:
                continue
            if obs.event_time > cutoff:
                continue
            context = self._contexts.get(bar.unified_code)
            if context is None:
                continue
            state = states.setdefault(bar.unified_code, _InstrumentState())
            _process_bar(obs, context, state)
            used.append(obs)
        return states, used


@dataclass(frozen=True)
class LimitPoolCorrection:
    """The revision an incremental ``feed`` produced.

    ``upserts`` are events that are now canonical and new-or-changed since the
    previous feed; ``retractions`` are previously emitted events that are no
    longer canonical and must be dropped by the consumer. ``revision`` increases
    by one per feed so consumers can order and deduplicate corrections.
    """

    upserts: list[LimitEvent] = field(default_factory=list)
    retractions: list[LimitEvent] = field(default_factory=list)
    revision: int = 0


def _divergence_point(old: list[LimitEvent], new: list[LimitEvent]) -> int:
    """Index at which ``new`` first differs from ``old`` (len if one is a prefix)."""
    for i, (prev, curr) in enumerate(zip(old, new, strict=False)):
        if prev != curr:
            return i
    return min(len(old), len(new))
