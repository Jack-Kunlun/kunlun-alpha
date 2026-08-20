"""Limit pool calculator tests.

Covers determinism (replay == real-time), out-of-order correction, first
limit-up / seal / break-seal / open-count events, limit-down facts, first/last
seal times and the snapshot.
"""

from __future__ import annotations

from decimal import Decimal

from emotion_core.limit_pool import InstrumentContext, LimitPoolAggregator, compute_limit_facts
from emotion_core.models import LimitEvent
from market_core.models.validators import Bar, ExchangeId


def _bar(code: str, timestamp: str, close: Decimal, exchange: ExchangeId = "SH") -> Bar:
    return Bar(
        unified_code=code,
        exchange=exchange,
        date="2026-08-13",
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


def _context(
    code: str, prev_close: Decimal = Decimal("10.00"), board: str = "MAIN", is_st: bool = False
) -> InstrumentContext:
    return InstrumentContext(unified_code=code, prev_close=prev_close, board=board, is_st=is_st)


def test_first_limit_up_then_break_then_reseal() -> None:
    bars = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),  # limit up
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),  # break seal
        _bar("600000.SH", "2026-08-13T01:34:00.000Z", Decimal("11.00")),  # reseal
    ]
    events = compute_limit_facts(bars, {"600000.SH": _context("600000.SH")})

    assert [e.event_type for e in events] == ["LIMIT_UP", "BREAK_SEAL", "SEAL"]
    assert events[2].open_count == 1


def test_out_of_order_input_is_corrected() -> None:
    ordered = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    contexts = {"600000.SH": _context("600000.SH")}

    assert compute_limit_facts(shuffled, contexts) == compute_limit_facts(ordered, contexts)


def test_replay_matches_real_time() -> None:
    bars = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),
    ]
    contexts = {"600000.SH": _context("600000.SH")}

    batch = compute_limit_facts(bars, contexts)

    aggregator = LimitPoolAggregator(contexts)
    incremental: list[LimitEvent] = []
    for bar in bars:
        incremental.extend(aggregator.feed(bar))

    assert batch == incremental


def test_snapshot_reports_sealed_pool() -> None:
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))

    snapshot = aggregator.snapshot("2026-08-13", "2026-08-13T01:32:00.000Z")
    assert snapshot.limit_up_count == 1
    assert snapshot.sealed_count == 1
    assert snapshot.limit_up_instruments == ("600000.SH",)


def test_limit_down_facts_emitted() -> None:
    bars = [
        _bar("000001.SZ", "2026-08-13T01:31:00.000Z", Decimal("9.50"), exchange="SZ"),
        _bar("000001.SZ", "2026-08-13T01:32:00.000Z", Decimal("9.00"), exchange="SZ"),  # limit down
    ]
    events = compute_limit_facts(bars, {"000001.SZ": _context("000001.SZ")})
    assert [e.event_type for e in events] == ["LIMIT_DOWN"]
    assert events[0].price == Decimal("9.00")


def test_snapshot_reports_limit_down_pool() -> None:
    aggregator = LimitPoolAggregator({"000001.SZ": _context("000001.SZ")})
    aggregator.feed(_bar("000001.SZ", "2026-08-13T01:32:00.000Z", Decimal("9.00"), exchange="SZ"))

    snapshot = aggregator.snapshot("2026-08-13", "2026-08-13T01:32:00.000Z")
    assert snapshot.limit_down_count == 1
    assert snapshot.limit_down_instruments == ("000001.SZ",)


def test_first_and_last_seal_time_and_open_count() -> None:
    bars = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("11.00")),  # first seal
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.90")),  # break
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("11.00")),  # reseal (open_count=1)
        _bar("600000.SH", "2026-08-13T01:34:00.000Z", Decimal("10.90")),  # break
        _bar("600000.SH", "2026-08-13T01:35:00.000Z", Decimal("11.00")),  # reseal (open_count=2)
    ]
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    for bar in bars:
        aggregator.feed(bar)

    snapshot = aggregator.snapshot("2026-08-13", "2026-08-13T01:35:00.000Z")
    assert snapshot.first_seal_time == "2026-08-13T01:31:00.000Z"
    assert snapshot.last_seal_time == "2026-08-13T01:35:00.000Z"
    assert snapshot.total_open_count == 2


def test_incremental_out_of_order_events_match_batch() -> None:
    # An aggregator fed bars out of order must expose the same canonical event
    # list as the batch function on the ordered bars.
    ordered = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")),
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),  # limit up
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("10.90")),  # break seal
        _bar("600000.SH", "2026-08-13T01:34:00.000Z", Decimal("11.00")),  # reseal
    ]
    contexts = {"600000.SH": _context("600000.SH")}
    batch = compute_limit_facts(ordered, contexts)

    aggregator = LimitPoolAggregator(contexts)
    for bar in [ordered[2], ordered[0], ordered[3], ordered[1]]:  # shuffled arrival
        aggregator.feed(bar)

    assert aggregator.events() == batch


def test_duplicate_timestamp_is_idempotent() -> None:
    # Feeding the same (code, timestamp) bar twice must not double-count.
    bar = _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"))
    contexts = {"600000.SH": _context("600000.SH")}

    aggregator = LimitPoolAggregator(contexts)
    aggregator.feed(bar)
    second_delta = aggregator.feed(bar)

    assert second_delta == []  # nothing new
    assert aggregator.events() == compute_limit_facts([bar], contexts)
    assert len(aggregator.events()) == 1


def test_correction_replaces_prior_observation() -> None:
    # A corrected bar at the same timestamp changes the fact; state must not
    # drift or keep the stale event.
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    # First observation: a limit-up seal.
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))
    assert [e.event_type for e in aggregator.events()] == ["LIMIT_UP"]

    # Correction at the same timestamp: it was actually not a limit-up.
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80")))
    assert aggregator.events() == []

    corrected_batch = compute_limit_facts(
        [_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80"))], contexts
    )
    assert aggregator.events() == corrected_batch


def test_feed_returns_only_new_or_corrected_events() -> None:
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    d1 = aggregator.feed(_bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")))
    assert d1 == []  # not a limit-up yet
    d2 = aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))
    assert [e.event_type for e in d2] == ["LIMIT_UP"]
