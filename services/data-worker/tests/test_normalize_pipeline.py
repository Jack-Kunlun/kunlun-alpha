"""Bar normalization pipeline tests.

Covers out-of-order, duplicate, negative-price, abnormal-volume and
missing-column handling — and verifies abnormal records are routed to the
rejection zone rather than silently dropped.
"""

from __future__ import annotations

from decimal import Decimal

from data_worker.normalize import process_bars


def _bar(timestamp: str, **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "unifiedCode": "600000.SH",
        "exchange": "SH",
        "date": "2026-08-13",
        "interval": "MINUTE_1",
        "session": "CONTINUOUS",
        "timestamp": timestamp,
        "open": Decimal("10.0"),
        "high": Decimal("10.5"),
        "low": Decimal("9.8"),
        "close": Decimal("10.2"),
        "volume": 1000,
        "amount": Decimal("10200.0"),
        "priceType": "RAW",
    }
    record.update(overrides)
    return record


def test_valid_bars_are_accepted() -> None:
    result = process_bars([_bar("2026-08-13T01:30:00.000Z"), _bar("2026-08-13T01:31:00.000Z")])
    assert len(result.accepted) == 2
    assert result.events == []
    assert len(result.rejection_zone) == 0


def test_out_of_order_bars_raise_event() -> None:
    result = process_bars([_bar("2026-08-13T01:31:00.000Z"), _bar("2026-08-13T01:30:00.000Z")])
    assert any(e.kind == "OUT_OF_ORDER" for e in result.events)


def test_duplicate_bars_raise_event() -> None:
    ts = "2026-08-13T01:30:00.000Z"
    result = process_bars([_bar(ts), _bar(ts)])
    assert any(e.kind == "DUPLICATE" for e in result.events)


def test_negative_price_is_rejected_with_event() -> None:
    result = process_bars([_bar("2026-08-13T01:30:00.000Z", close=Decimal("-1.0"))])
    assert len(result.accepted) == 0
    assert len(result.rejection_zone) == 1
    assert any(e.kind == "NEGATIVE_PRICE" for e in result.events)


def test_abnormal_volume_is_rejected_with_event() -> None:
    result = process_bars([_bar("2026-08-13T01:30:00.000Z", volume=-100)])
    assert len(result.accepted) == 0
    assert any(e.kind == "ABNORMAL_VOLUME" for e in result.events)


def test_missing_column_is_rejected_not_dropped() -> None:
    record = _bar("2026-08-13T01:30:00.000Z")
    record.pop("close")
    result = process_bars([record])

    assert len(result.accepted) == 0
    assert len(result.rejection_zone) == 1
    assert any(e.kind == "MISSING_FIELD" for e in result.events)
    # The abnormal record is retained with its reason, not silently dropped.
    rejected = result.rejection_zone.records()[0]
    assert "close" in rejected.reason
    assert "close" not in rejected.record


def test_suffix_exchange_mismatch_is_rejected_not_accepted() -> None:
    result = process_bars(
        [_bar("2026-08-13T01:30:00.000Z", unifiedCode="600000.SZ", exchange="SH")]
    )

    assert len(result.accepted) == 0
    assert len(result.rejection_zone) == 1
    rejected = result.rejection_zone.records()[0]
    assert "unifiedCode/exchange identity mismatch" in rejected.reason
