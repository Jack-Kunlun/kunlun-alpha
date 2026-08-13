"""Market data storage tests.

Verifies idempotent batch writes (ReplacingMergeTree dedupe by key) and
time-range queries against the (unified_code, timestamp) ordering key.
"""

from __future__ import annotations

from market_core.models.validators import Bar
from market_core.storage import InMemoryBarStorage


def _bar(code: str, timestamp: str) -> Bar:
    return Bar(
        unified_code=code,
        exchange="SH",
        date="2026-08-13",
        interval="MINUTE_1",
        session="CONTINUOUS",
        timestamp=timestamp,
        open=10.0,
        high=10.5,
        low=9.8,
        close=10.2,
        volume=1000,
        amount=10200.0,
        price_type="RAW",
    )


def test_batch_write_is_idempotent() -> None:
    storage = InMemoryBarStorage()
    bars = [
        _bar("SH.600000", "2026-08-13T01:30:00.000Z"),
        _bar("SH.600000", "2026-08-13T01:31:00.000Z"),
    ]

    storage.write_bars(bars)
    storage.write_bars(bars)  # re-insert same keys

    assert (
        len(storage.query_bars("SH.600000", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z"))
        == 2
    )


def test_rewriting_key_replaces_row() -> None:
    storage = InMemoryBarStorage()
    original = _bar("SH.600000", "2026-08-13T01:30:00.000Z")
    storage.write_bars([original])

    updated = _bar("SH.600000", "2026-08-13T01:30:00.000Z")
    storage.write_bars([updated])

    rows = storage.query_bars("SH.600000", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert len(rows) == 1


def test_range_query_orders_by_timestamp() -> None:
    storage = InMemoryBarStorage()
    storage.write_bars(
        [
            _bar("SH.600000", "2026-08-13T01:31:00.000Z"),
            _bar("SH.600000", "2026-08-13T01:30:00.000Z"),
            _bar("SZ.000001", "2026-08-13T01:30:00.000Z"),
        ]
    )

    rows = storage.query_bars("SH.600000", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert [r.timestamp for r in rows] == ["2026-08-13T01:30:00.000Z", "2026-08-13T01:31:00.000Z"]


def test_range_query_filters_bounds() -> None:
    storage = InMemoryBarStorage()
    storage.write_bars([_bar("SH.600000", "2026-08-13T01:30:00.000Z")])

    assert (
        storage.query_bars("SH.600000", "2026-08-14T00:00:00.000Z", "2026-08-14T23:59:59.000Z")
        == []
    )
