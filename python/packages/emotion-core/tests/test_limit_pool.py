"""Limit pool calculator tests.

Covers determinism (replay == real-time), out-of-order correction, first
limit-up / seal / break-seal / open-count events, limit-down facts, first/last
seal times and the snapshot.
"""

from __future__ import annotations

from decimal import Decimal

from emotion_core.limit_pool import (
    InstrumentContext,
    LimitPoolAggregator,
    LimitPoolCorrection,
    compute_limit_facts,
)
from emotion_core.models import LimitEvent
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
        env = aggregator.feed(bar)
        for retracted in env.retractions:
            incremental.remove(retracted)
        incremental.extend(env.upserts)

    assert batch == incremental


def test_snapshot_reports_sealed_pool() -> None:
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))

    snapshot = aggregator.snapshot(as_of="2026-08-13T01:32:00.000Z", trading_date="2026-08-13")
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

    snapshot = aggregator.snapshot(as_of="2026-08-13T01:32:00.000Z", trading_date="2026-08-13")
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

    snapshot = aggregator.snapshot(as_of="2026-08-13T01:35:00.000Z", trading_date="2026-08-13")
    assert snapshot.first_seal_time == "2026-08-13T01:31:00+00:00"
    assert snapshot.last_seal_time == "2026-08-13T01:35:00+00:00"
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
    second = aggregator.feed(bar)

    assert second.upserts == []  # nothing new
    assert second.retractions == []
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
    assert d1.upserts == []  # not a limit-up yet
    d2 = aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))
    assert [e.event_type for e in d2.upserts] == ["LIMIT_UP"]


# --- Round 2 blocking fixes -------------------------------------------------


def test_feed_returns_correction_envelope_with_revision() -> None:
    # Blocking #1: an incremental consumer must be able to replay events even
    # when a correction empties the canonical tail. feed() returns an explicit
    # envelope (upserts + retractions + revision), never a bare delta that may
    # be empty while stale facts remain downstream.
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    first = aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")))
    assert isinstance(first, LimitPoolCorrection)
    assert [e.event_type for e in first.upserts] == ["LIMIT_UP"]
    assert first.retractions == []
    assert first.revision == 1

    # Correction at the same timestamp: no longer a limit-up. The previously
    # emitted LIMIT_UP must be retracted so the downstream consumer drops it.
    second = aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80")))
    assert second.upserts == []
    assert [e.event_type for e in second.retractions] == ["LIMIT_UP"]
    assert second.revision == 2


def test_replay_of_correction_envelopes_reconstructs_canonical() -> None:
    # Applying successive envelopes (upserts add, retractions remove) must
    # reconstruct exactly the canonical event list — proving no stale fact is
    # retained after a correction.
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    downstream: list[LimitEvent] = []
    for bar in [
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00")),  # LIMIT_UP
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80")),  # retracts it
    ]:
        env = aggregator.feed(bar)
        for retracted in env.retractions:
            downstream.remove(retracted)
        downstream.extend(env.upserts)

    assert downstream == aggregator.events()
    assert downstream == []


def test_sealed_to_limit_down_records_break_seal_and_keeps_open_count() -> None:
    # Blocking #5: a sealed instrument that flips straight to limit-down must
    # emit BREAK_SEAL (the seal opened) before LIMIT_DOWN, and the open count
    # accumulated while sealed must not be lost.
    bars = [
        _bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("11.00")),  # seal
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.90")),  # break
        _bar("600000.SH", "2026-08-13T01:33:00.000Z", Decimal("11.00")),  # reseal (open=1)
        _bar("600000.SH", "2026-08-13T01:34:00.000Z", Decimal("9.00")),  # -> limit down
    ]
    events = compute_limit_facts(bars, {"600000.SH": _context("600000.SH")})
    assert [e.event_type for e in events] == [
        "LIMIT_UP",
        "BREAK_SEAL",
        "SEAL",
        "BREAK_SEAL",
        "LIMIT_DOWN",
    ]
    # The BREAK_SEAL before LIMIT_DOWN preserves the accumulated open count.
    break_before_down = events[-2]
    assert break_before_down.event_type == "BREAK_SEAL"
    assert break_before_down.open_count == 1


def test_snapshot_ignores_bars_after_as_of() -> None:
    # Blocking #2: a historical snapshot must not include future data. A bar
    # whose timestamp is after as_of must not affect the snapshot.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:31:00.000Z", Decimal("10.50")))  # not sealed
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:40:00.000Z", Decimal("11.00")))  # future seal

    # as_of is before the sealing bar -> pool is empty at that instant.
    snapshot = aggregator.snapshot(as_of="2026-08-13T01:32:00.000Z", trading_date="2026-08-13")
    assert snapshot.limit_up_count == 0
    assert snapshot.limit_up_instruments == ()


def test_snapshot_isolates_by_trading_date() -> None:
    # Blocking #2: state must not carry across trading days. A seal on one day
    # must not appear in another day's snapshot.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(
        _bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("11.00"), date="2026-08-13")
    )
    aggregator.feed(
        _bar("600000.SH", "2026-08-14T01:32:00.000Z", Decimal("10.50"), date="2026-08-14")
    )

    day13 = aggregator.snapshot(as_of="2026-08-13T02:00:00.000Z", trading_date="2026-08-13")
    assert day13.limit_up_count == 1

    day14 = aggregator.snapshot(as_of="2026-08-14T02:00:00.000Z", trading_date="2026-08-14")
    assert day14.limit_up_count == 0  # day 14 never sealed; day 13 must not leak in


def test_sorting_and_dedup_use_canonical_instant() -> None:
    # Blocking #7: two bars whose timestamps are the same instant in different
    # timezone representations must be treated as one (last write wins), and
    # ordering must use the canonical instant, not the raw string.
    contexts = {"600000.SH": _context("600000.SH")}
    aggregator = LimitPoolAggregator(contexts)

    aggregator.feed(_bar("600000.SH", "2026-08-13T09:32:00.000+08:00", Decimal("11.00")))
    # Same instant (01:32Z) expressed as UTC, corrected value -> not a limit-up.
    aggregator.feed(_bar("600000.SH", "2026-08-13T01:32:00.000Z", Decimal("10.80")))

    # Deduped to one bar by canonical instant; the correction wins.
    assert aggregator.events() == []


def test_first_last_seal_time_use_canonical_instant() -> None:
    # first/last seal must be computed on canonical instants, so a later wall
    # time in an earlier-offset zone still orders correctly.
    aggregator = LimitPoolAggregator({"600000.SH": _context("600000.SH")})
    aggregator.feed(_bar("600000.SH", "2026-08-13T09:31:00.000+08:00", Decimal("11.00")))  # 01:31Z
    snapshot = aggregator.snapshot(as_of="2026-08-13T02:00:00.000Z", trading_date="2026-08-13")
    assert snapshot.first_seal_time == "2026-08-13T01:31:00+00:00"
