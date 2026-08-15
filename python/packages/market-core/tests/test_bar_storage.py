"""Market data storage tests.

Verifies idempotent batch writes (ReplacingMergeTree dedupe by key) and
time-range queries against the (unified_code, timestamp) ordering key.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest
from market_core import storage as storage_module
from market_core.models.validators import Bar, BarInterval, ExchangeId, PriceType
from market_core.storage import InMemoryBarStorage


def _bar(
    code: str,
    timestamp: str,
    *,
    interval: BarInterval = "MINUTE_1",
    price_type: PriceType = "RAW",
    close: Decimal = Decimal("10.2"),
) -> Bar:
    return Bar(
        unified_code=code,
        exchange=cast(ExchangeId, code.rsplit(".", maxsplit=1)[1]),
        date="2026-08-13",
        interval=interval,
        session="CONTINUOUS",
        timestamp=timestamp,
        open=Decimal("10.0"),
        high=Decimal("10.5"),
        low=Decimal("9.8"),
        close=close,
        volume=1000,
        amount=Decimal("10200.0"),
        price_type=price_type,
    )


def _stored_bar(
    bar: Bar,
    *,
    data_version: str = "bar-v1",
    source: str = "vendor-a",
    source_version: str = "2026-08-13",
    available_time: str = "2026-08-13T02:00:00.000Z",
    replacement_version: int = 1,
    raw_capture_id: str = "raw-1",
) -> storage_module.StoredBar:
    ingest_time = datetime(2026, 8, 13, 1, 45, tzinfo=UTC)
    available = datetime.fromisoformat(available_time.replace("Z", "+00:00"))
    return storage_module.StoredBar(
        bar=bar,
        data_version=data_version,
        source=source,
        source_version=source_version,
        raw_capture_id=raw_capture_id,
        available_time=available_time,
        ingest_time=ingest_time,
        processing_time=available.replace(minute=available.minute + 1),
        replacement_version=replacement_version,
    )


def test_storage_exposes_immutable_envelope() -> None:
    assert hasattr(storage_module, "StoredBar"), "storage envelope is not exported"


def test_storage_envelope_is_immutable() -> None:
    stored = _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"))

    with pytest.raises(FrozenInstanceError):
        stored.source = "other-vendor"  # pyright: ignore[reportAttributeAccessIssue]


def test_storage_rejects_bare_bar_without_provenance() -> None:
    storage = InMemoryBarStorage()

    with pytest.raises(TypeError, match="explicit StoredBar metadata"):
        storage.write_bars(
            [cast(storage_module.StoredBar, _bar("600000.SH", "2026-08-13T01:30:00.000Z"))]
        )


def test_exact_full_envelope_replay_is_idempotent() -> None:
    storage = InMemoryBarStorage()
    stored = _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"))

    storage.write_bars([stored])
    storage.write_bars([stored])

    rows = storage.query_bars("600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert rows == [stored]


def test_conflicting_same_identity_and_version_is_rejected_atomically() -> None:
    storage = InMemoryBarStorage()
    original = _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"))
    storage.write_bars([original])
    conflict = _stored_bar(
        _bar("600000.SH", "2026-08-13T01:30:00.000Z", close=Decimal("10.4")),
        raw_capture_id="raw-conflict",
    )
    new_identity = _stored_bar(
        _bar("600000.SH", "2026-08-13T01:31:00.000Z"), raw_capture_id="raw-new"
    )

    with pytest.raises(ValueError, match="conflicting revision"):
        storage.write_bars([new_identity, conflict])

    rows = storage.query_bars("600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert rows == [original]


def test_conflict_on_available_time_or_provenance_is_rejected() -> None:
    storage = InMemoryBarStorage()
    original = _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"))
    storage.write_bars([original])
    conflict = _stored_bar(
        _bar("600000.SH", "2026-08-13T01:30:00.000Z"),
        available_time="2026-08-13T04:00:00.000Z",
        raw_capture_id="raw-late",
    )

    with pytest.raises(ValueError, match="conflicting revision"):
        storage.write_bars([conflict])

    assert storage.query_bars(
        "600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z"
    ) == [original]


def test_batch_write_is_idempotent() -> None:
    storage = InMemoryBarStorage()
    bars = [
        _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"), raw_capture_id="raw-1"),
        _stored_bar(_bar("600000.SH", "2026-08-13T01:31:00.000Z"), raw_capture_id="raw-2"),
    ]

    storage.write_bars(bars)
    storage.write_bars(bars)  # re-insert same keys

    assert (
        len(storage.query_bars("600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z"))
        == 2
    )


def test_rewriting_key_replaces_row() -> None:
    storage = InMemoryBarStorage()
    original = _stored_bar(
        _bar("600000.SH", "2026-08-13T01:30:00.000Z"), raw_capture_id="raw-original"
    )
    storage.write_bars([original])

    updated = _stored_bar(
        _bar("600000.SH", "2026-08-13T01:30:00.000Z"),
        raw_capture_id="raw-updated",
        replacement_version=2,
    )
    storage.write_bars([updated])

    rows = storage.query_bars("600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert len(rows) == 1


def test_range_query_orders_by_timestamp() -> None:
    storage = InMemoryBarStorage()
    storage.write_bars(
        [
            _stored_bar(_bar("600000.SH", "2026-08-13T01:31:00.000Z"), raw_capture_id="raw-1"),
            _stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"), raw_capture_id="raw-2"),
            _stored_bar(_bar("000001.SZ", "2026-08-13T01:30:00.000Z"), raw_capture_id="raw-3"),
        ]
    )

    rows = storage.query_bars("600000.SH", "2026-08-13T00:00:00.000Z", "2026-08-13T23:59:59.000Z")
    assert [r.timestamp for r in rows] == ["2026-08-13T01:30:00.000Z", "2026-08-13T01:31:00.000Z"]


def test_range_query_filters_bounds() -> None:
    storage = InMemoryBarStorage()
    storage.write_bars(
        [_stored_bar(_bar("600000.SH", "2026-08-13T01:30:00.000Z"), raw_capture_id="raw-1")]
    )

    assert (
        storage.query_bars("600000.SH", "2026-08-14T00:00:00.000Z", "2026-08-14T23:59:59.000Z")
        == []
    )


def test_semantic_series_coexist_at_one_event_time() -> None:
    storage = InMemoryBarStorage()
    timestamp = "2026-08-13T01:30:00.000Z"
    storage.write_bars(
        [
            _stored_bar(_bar("600000.SH", timestamp, interval="MINUTE_1", price_type="RAW")),
            _stored_bar(
                _bar("600000.SH", timestamp, interval="MINUTE_1", price_type="FORWARD_ADJUSTED"),
                data_version="bar-v2",
            ),
            _stored_bar(
                _bar("600000.SH", timestamp, interval="MINUTE_1", price_type="BACKWARD_ADJUSTED"),
                source="vendor-b",
                source_version="2026-08-14",
            ),
            _stored_bar(
                _bar("600000.SH", timestamp, interval="DAILY", price_type="RAW"),
                data_version="daily-v1",
            ),
        ]
    )

    rows = storage.query_bars(
        "600000.SH",
        "2026-08-13T00:00:00.000Z",
        "2026-08-13T23:59:59.000Z",
    )

    assert len(rows) == 4
    assert {(row.interval, row.price_type) for row in rows} == {
        ("MINUTE_1", "RAW"),
        ("MINUTE_1", "FORWARD_ADJUSTED"),
        ("MINUTE_1", "BACKWARD_ADJUSTED"),
        ("DAILY", "RAW"),
    }


def test_highest_replacement_version_wins_for_full_identity() -> None:
    storage = InMemoryBarStorage()
    timestamp = "2026-08-13T01:30:00.000Z"
    identity = _bar("600000.SH", timestamp, price_type="RAW")
    storage.write_bars(
        [
            _stored_bar(identity, replacement_version=1, raw_capture_id="raw-old"),
            _stored_bar(
                _bar("600000.SH", timestamp, price_type="RAW", close=Decimal("10.4")),
                replacement_version=3,
                raw_capture_id="raw-new",
            ),
        ]
    )

    rows = storage.query_bars(
        "600000.SH",
        "2026-08-13T00:00:00.000Z",
        "2026-08-13T23:59:59.000Z",
    )

    assert len(rows) == 1
    assert rows[0].replacement_version == 3
    assert rows[0].close == Decimal("10.4")
    assert rows[0].raw_capture_id == "raw-new"


def test_as_of_query_excludes_rows_not_yet_available() -> None:
    storage = InMemoryBarStorage()
    timestamp = "2026-08-13T01:30:00.000Z"
    storage.write_bars(
        [
            _stored_bar(
                _bar("600000.SH", timestamp, close=Decimal("10.6")),
                available_time="2026-08-13T04:00:00.000Z",
                replacement_version=2,
                raw_capture_id="raw-future",
            ),
        ]
    )

    rows = storage.query_bars(
        "600000.SH",
        "2026-08-13T00:00:00.000Z",
        "2026-08-13T23:59:59.000Z",
        as_of=datetime(2026, 8, 13, 3, tzinfo=UTC),
    )

    assert rows == []

    storage.write_bars(
        [
            _stored_bar(
                _bar("600000.SH", timestamp),
                available_time="2026-08-13T02:00:00.000Z",
                replacement_version=1,
                raw_capture_id="raw-known",
            )
        ]
    )
    rows = storage.query_bars(
        "600000.SH",
        "2026-08-13T00:00:00.000Z",
        "2026-08-13T23:59:59.000Z",
        as_of=datetime(2026, 8, 13, 3, tzinfo=UTC),
    )

    assert len(rows) == 1
    assert rows[0].replacement_version == 1
    assert rows[0].close == Decimal("10.2")
