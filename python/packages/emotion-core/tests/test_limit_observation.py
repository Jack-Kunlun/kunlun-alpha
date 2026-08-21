"""Typed revisable observation + canonicalization tests (P2-R01 R3-3).

Blocking #1: batch and incremental paths must share one canonicalization of
typed, revisable observations. The observation identity is
``(trading_date, unified_code, canonical event_time)``. Revision rules:

* revision is a non-negative integer,
* a higher revision wins over a lower one,
* the same revision with the same payload is idempotent,
* the same revision with a *different* payload is a conflict and is rejected,
* the winner never depends on arrival order.

Blocking #4: canonical state is isolated per ``(trading_date, unified_code)``
and reset to normal each trading day, so two consecutive limit-up days each
produce their own LIMIT_UP and open_count / sealed / limit_down never inherit
across days.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from emotion_core.limit_pool import (
    InstrumentContext,
    LimitBarObservation,
    LimitPoolAggregator,
    LimitPoolCorrection,
    RevisionConflictError,
    canonicalize_observations,
    compute_limit_facts,
)
from emotion_core.models import LimitEvent
from emotion_core.pit import Instant
from market_core.models.validators import Bar, ExchangeId


def _bar(
    code: str,
    timestamp: str,
    close: Decimal,
    exchange: ExchangeId = "SH",
    date: str = "2026-08-13",
) -> Bar:
    return Bar(
        unified_code=code,
        exchange=exchange,
        date=date,
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=close * Decimal("1000"),
        price_type="RAW",
    )


def _obs(
    code: str,
    timestamp: str,
    close: Decimal,
    *,
    revision: int = 0,
    available_time: str | None = None,
    source: str = "vendor-a",
    source_version: str = "v1",
    evidence_id: str = "ev-1",
    exchange: ExchangeId = "SH",
    date: str = "2026-08-13",
) -> LimitBarObservation:
    bar = _bar(code, timestamp, close, exchange=exchange, date=date)
    avail = available_time if available_time is not None else timestamp
    return LimitBarObservation(
        bar=bar,
        event_time=Instant.parse(timestamp),
        available_time=Instant.parse(avail),
        revision=revision,
        source=source,
        source_version=source_version,
        evidence_id=evidence_id,
    )


def _context(
    code: str, prev_close: Decimal = Decimal("10.00"), board: str = "MAIN", is_st: bool = False
) -> InstrumentContext:
    return InstrumentContext(unified_code=code, prev_close=prev_close, board=board, is_st=is_st)


# --- revision winner + conflict rejection ----------------------------------


def test_higher_revision_wins_over_lower() -> None:
    # Same identity, two revisions with different payloads: the higher revision
    # is canonical regardless of arrival order.
    lo = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=0)
    hi = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"), revision=1)

    forward = canonicalize_observations([lo, hi])
    backward = canonicalize_observations([hi, lo])

    assert len(forward) == 1
    assert forward[0].bar.close == Decimal("10.80")  # revision 1 wins
    assert forward == backward  # arrival order does not matter


def test_same_revision_same_payload_is_idempotent() -> None:
    a = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=1)
    b = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=1)

    result = canonicalize_observations([a, b])
    assert len(result) == 1
    assert result[0].bar.close == Decimal("11.00")


def test_same_revision_different_payload_is_conflict() -> None:
    a = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=1)
    b = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"), revision=1)

    with pytest.raises(RevisionConflictError):
        canonicalize_observations([a, b])
    # Order independence: the conflict is raised either way.
    with pytest.raises(RevisionConflictError):
        canonicalize_observations([b, a])


def test_negative_revision_is_rejected() -> None:
    with pytest.raises(ValueError, match="revision"):
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=-1)


# --- revision type boundary (blocking #6) ----------------------------------


def test_revision_bool_true_is_rejected() -> None:
    # bool is an int subclass; a True/False must not be accepted as a revision.
    with pytest.raises(TypeError):
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=True)  # type: ignore[arg-type]


def test_revision_float_is_rejected() -> None:
    with pytest.raises(TypeError):
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=1.0)  # type: ignore[arg-type]


def test_revision_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision="1")  # type: ignore[arg-type]


def test_revision_none_is_rejected() -> None:
    with pytest.raises(TypeError):
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=None)  # type: ignore[arg-type]


def test_revision_zero_and_positive_int_allowed() -> None:
    zero = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=0)
    two = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=2)
    assert zero.revision == 0
    assert two.revision == 2


def test_identity_uses_canonical_event_time() -> None:
    # Two representations of the same instant (UTC and +08:00) are one identity;
    # the later revision wins after dedup.
    utc = _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=0)
    off = _obs("600000.SH", "2026-08-13T09:32:00.000+08:00", Decimal("10.80"), revision=1)

    result = canonicalize_observations([utc, off])
    assert len(result) == 1
    assert result[0].bar.close == Decimal("10.80")


def test_canonical_output_is_sorted_and_order_independent() -> None:
    obs = [
        _obs("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),
    ]
    forward = canonicalize_observations(obs)
    backward = canonicalize_observations(list(reversed(obs)))
    assert forward == backward
    times = [o.event_time.isoformat() for o in forward]
    assert times == sorted(times)


# --- batch uses canonicalize; order does not matter ------------------------


def test_batch_from_observations_is_order_independent() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    ordered = [
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),
        _obs("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]

    from_ordered = compute_limit_facts(ordered, contexts)
    from_shuffled = compute_limit_facts(shuffled, contexts)
    assert from_ordered == from_shuffled
    assert [e.event_type for e in from_ordered] == ["LIMIT_UP", "BREAK_SEAL"]


def test_batch_applies_revision_winner() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    obs = [
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=0),  # seal
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"), revision=1),  # corrected
    ]
    events = compute_limit_facts(obs, contexts)
    assert events == []  # revision 1 says it was never a limit-up


# --- cross-trading-day isolation (blocking #4) -----------------------------


def test_consecutive_limit_up_days_each_emit_limit_up() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    obs = [
        _obs(
            "600000.SH",
            "2026-08-13T01:32:00.000Z",
            Decimal("11.00"),
            date="2026-08-13",
        ),
        _obs(
            "600000.SH",
            "2026-08-14T01:32:00.000Z",
            Decimal("11.00"),
            date="2026-08-14",
        ),
    ]
    events = compute_limit_facts(obs, contexts)
    # Each day resets to normal, so each day's seal is its own LIMIT_UP.
    assert [e.event_type for e in events] == ["LIMIT_UP", "LIMIT_UP"]
    assert [e.date for e in events] == ["2026-08-13", "2026-08-14"]


def test_open_count_does_not_inherit_across_days() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    obs = [
        # Day 13: seal, break, reseal -> open_count 1
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("11.00"), date="2026-08-13"),
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.90"), date="2026-08-13"),
        _obs("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("11.00"), date="2026-08-13"),
        # Day 14: first seal only -> open_count 0, not inherited from day 13
        _obs("600000.SH", "2026-08-14T01:31:00.000Z", Decimal("11.00"), date="2026-08-14"),
    ]
    events = compute_limit_facts(obs, contexts)
    day14 = [e for e in events if e.date == "2026-08-14"]
    assert [e.event_type for e in day14] == ["LIMIT_UP"]
    assert day14[0].open_count == 0


# --- aggregator feed / events share the same canonicalization --------------


def test_feed_observations_match_batch() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    obs = [
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),
        _obs("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),
    ]
    batch = compute_limit_facts(obs, contexts)

    aggregator = LimitPoolAggregator(contexts)
    for o in [obs[2], obs[0], obs[1]]:  # shuffled arrival
        aggregator.feed(o)
    assert aggregator.events() == batch


def test_feed_higher_revision_retracts_stale_event() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    first = aggregator.feed(
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=0)
    )
    assert isinstance(first, LimitPoolCorrection)
    assert [e.event_type for e in first.upserts] == ["LIMIT_UP"]

    # Higher revision corrects the same identity: the LIMIT_UP is retracted.
    second = aggregator.feed(
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"), revision=1)
    )
    assert [e.event_type for e in second.retractions] == ["LIMIT_UP"]
    assert second.upserts == []


def test_feed_conflicting_revision_is_rejected() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)
    aggregator.feed(_obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), revision=1))
    with pytest.raises(RevisionConflictError):
        aggregator.feed(_obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"), revision=1))


def test_non_tail_correction_cascades_recompute() -> None:
    # A correction to a *non-tail* observation must recompute every downstream
    # event, not just append. Correcting the first seal to a non-seal removes
    # the whole chain that depended on it.
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    downstream: list[LimitEvent] = []
    feeds = [
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("11.00"), revision=0),  # seal
        _obs("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.90"), revision=0),  # break
        _obs("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("11.00"), revision=0),  # reseal
        # Correct the FIRST bar (non-tail) to a non-seal at higher revision.
        _obs("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50"), revision=1),
    ]
    for o in feeds:
        env = aggregator.feed(o)
        for retracted in env.retractions:
            downstream.remove(retracted)
        downstream.extend(env.upserts)

    assert downstream == aggregator.events()
    # After correcting the first bar, only the later reseal is a fresh LIMIT_UP.
    assert [e.event_type for e in aggregator.events()] == ["LIMIT_UP"]
    assert aggregator.events()[0].timestamp == "2026-08-13T01:33:00.000Z"
