"""Sector snapshot tests.

Covers aggregation (change/turnover/breadth/leader/strength), member changes,
missing quotes and abnormal turnover.
"""

from __future__ import annotations

from market_core.models.validators import Bar
from rotation_core.snapshot import SnapshotAggregator, compute_snapshot


def _bar(code: str, close: float, amount: float) -> Bar:
    return Bar(
        unified_code=code,
        exchange="SH",
        date="2026-08-13",
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp="2026-08-13T02:00:00.000Z",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        amount=amount,
        price_type="RAW",
    )


def test_snapshot_aggregation() -> None:
    members = ["A", "B", "C"]
    bars = {
        "A": _bar("A", 11.0, 1000),  # +10%
        "B": _bar("B", 10.5, 2000),  # +5%
        "C": _bar("C", 9.5, 3000),  # -5%
    }
    prev_close = {"A": 10.0, "B": 10.0, "C": 10.0}

    snapshot = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", members, bars, prev_close
    )

    assert abs(snapshot.average_change - (0.10 + 0.05 - 0.05) / 3) < 1e-5
    assert snapshot.turnover == 6000
    assert abs(snapshot.breadth - 2 / 3) < 1e-5
    assert snapshot.leader == "A"
    assert snapshot.version == "sector_snapshot_v1"


def test_missing_quote_is_skipped() -> None:
    members = ["A", "B"]
    bars = {"A": _bar("A", 11.0, 1000)}  # B has no bar
    prev_close = {"A": 10.0, "B": 10.0}

    snapshot = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", members, bars, prev_close
    )

    assert abs(snapshot.average_change - 0.10) < 1e-9
    assert snapshot.turnover == 1000


def test_abnormal_turnover_is_skipped() -> None:
    members = ["A", "B"]
    bars = {"A": _bar("A", 11.0, 1000), "B": _bar("B", 10.5, -100)}  # negative amount
    prev_close = {"A": 10.0, "B": 10.0}

    snapshot = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", members, bars, prev_close
    )

    assert abs(snapshot.average_change - 0.10) < 1e-9


def test_member_change_uses_current_members() -> None:
    # The same snapshot computation with a different member set yields a
    # different aggregate — the set valid at the snapshot time is what matters.
    bars = {"A": _bar("A", 11.0, 1000), "B": _bar("B", 9.0, 1000)}
    prev_close = {"A": 10.0, "B": 10.0}

    with_a = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", ["A"], bars, prev_close
    )
    with_both = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", ["A", "B"], bars, prev_close
    )

    assert with_a.average_change > with_both.average_change


def test_aggregator_matches_batch() -> None:
    members = ["A", "B"]
    prev_close = {"A": 10.0, "B": 10.0}
    bars = [("A", _bar("A", 11.0, 1000)), ("B", _bar("B", 10.5, 2000))]

    batch = compute_snapshot(
        "s1", "2026-08-13", "2026-08-13T02:00:00.000Z", members, dict(bars), prev_close
    )

    aggregator = SnapshotAggregator("s1", "2026-08-13", members, prev_close)
    for _, bar in bars:
        aggregator.feed(bar)
    incremental = aggregator.snapshot("2026-08-13T02:00:00.000Z")

    assert batch == incremental
