"""Limit pool calculator tests.

Covers determinism (replay == real-time), out-of-order correction, first
limit-up / seal / break-seal / open-count events and the snapshot.
"""

from __future__ import annotations

from emotion_core.limit_pool import InstrumentContext, LimitPoolAggregator, compute_limit_facts
from emotion_core.models import LimitEvent
from market_core.models.validators import Bar


def _bar(code: str, timestamp: str, close: float) -> Bar:
    return Bar(
        unified_code=code,
        exchange="SH",
        date="2026-08-13",
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=close * 1000,
        price_type="RAW",
    )


def _context(
    code: str, prev_close: float = 10.0, board: str = "MAIN", is_st: bool = False
) -> InstrumentContext:
    return InstrumentContext(unified_code=code, prev_close=prev_close, board=board, is_st=is_st)


def test_first_limit_up_then_break_then_reseal() -> None:
    bars = [
        _bar("SH.600000", "2026-08-13T01:31:00.000Z", 10.50),
        _bar("SH.600000", "2026-08-13T01:32:00.000Z", 11.00),  # limit up
        _bar("SH.600000", "2026-08-13T01:33:00.000Z", 10.90),  # break seal
        _bar("SH.600000", "2026-08-13T01:34:00.000Z", 11.00),  # reseal
    ]
    events = compute_limit_facts(bars, {"SH.600000": _context("SH.600000")})

    assert [e.event_type for e in events] == ["LIMIT_UP", "BREAK_SEAL", "SEAL"]
    assert events[2].open_count == 1


def test_out_of_order_input_is_corrected() -> None:
    ordered = [
        _bar("SH.600000", "2026-08-13T01:31:00.000Z", 10.50),
        _bar("SH.600000", "2026-08-13T01:32:00.000Z", 11.00),
        _bar("SH.600000", "2026-08-13T01:33:00.000Z", 10.90),
    ]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    contexts = {"SH.600000": _context("SH.600000")}

    assert compute_limit_facts(shuffled, contexts) == compute_limit_facts(ordered, contexts)


def test_replay_matches_real_time() -> None:
    bars = [
        _bar("SH.600000", "2026-08-13T01:31:00.000Z", 10.50),
        _bar("SH.600000", "2026-08-13T01:32:00.000Z", 11.00),
        _bar("SH.600000", "2026-08-13T01:33:00.000Z", 10.90),
    ]
    contexts = {"SH.600000": _context("SH.600000")}

    batch = compute_limit_facts(bars, contexts)

    aggregator = LimitPoolAggregator(contexts)
    incremental: list[LimitEvent] = []
    for bar in bars:
        incremental.extend(aggregator.feed(bar))

    assert batch == incremental


def test_snapshot_reports_sealed_pool() -> None:
    aggregator = LimitPoolAggregator({"SH.600000": _context("SH.600000")})
    aggregator.feed(_bar("SH.600000", "2026-08-13T01:32:00.000Z", 11.00))

    snapshot = aggregator.snapshot("2026-08-13", "2026-08-13T01:32:00.000Z")
    assert snapshot.limit_up_count == 1
    assert snapshot.sealed_count == 1
    assert snapshot.limit_up_instruments == ("SH.600000",)
