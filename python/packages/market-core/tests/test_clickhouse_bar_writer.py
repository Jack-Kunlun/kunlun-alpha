"""Tests for the production ClickHouse bar writer."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import cast

import pytest
from market_core.models.validators import Bar, BarInterval, ExchangeId
from market_core.storage import ClickHouseBarConfig, ClickHouseBarWriter, StoredBar


def _stored(
    code: str,
    interval: str,
    event_time: str,
    *,
    amount: Decimal = Decimal("12072.50"),
    metadata_time: datetime | None = None,
) -> StoredBar:
    bar = Bar(
        unified_code=code,
        exchange=cast(ExchangeId, code.rsplit(".", maxsplit=1)[1]),
        date="2026-08-27" if interval != "DAILY" else "2026-08-26",
        interval=cast(BarInterval, interval),
        session="CONTINUOUS",
        timestamp=event_time,
        open=Decimal("10.01"),
        high=Decimal("10.08"),
        low=Decimal("9.99"),
        close=Decimal("10.06"),
        volume=1200,
        amount=amount,
        price_type="RAW",
    )
    metadata_time = metadata_time or datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    return StoredBar(
        bar=bar,
        data_version="bar-v1",
        source="tushare-pro",
        source_version="tushare:rt_min_daily:v1",
        raw_capture_id="capture-1",
        ingest_time=metadata_time,
        available_time=metadata_time,
        processing_time=metadata_time,
        replacement_version=1_777_000_000_000_000,
    )


def _failed_transport(
    _url: str,
    _headers: Mapping[str, str],
    _body: bytes,
    _timeout: float,
) -> tuple[int, bytes]:
    return 500, b"secret diagnostics"


def test_writer_splits_tables_and_preserves_exact_metadata() -> None:
    calls: list[tuple[str, Mapping[str, str], bytes, float]] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
    ) -> tuple[int, bytes]:
        calls.append((url, headers, body, timeout))
        return 200, b""

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(
            url="http://clickhouse:8123",
            database="kunlun",
            user="writer",
            password="secret",
        ),
        transport=transport,
    )
    minute = _stored(
        "600000.SH",
        "MINUTE_1",
        "2026-08-27T09:31:00.123999+08:00",
        amount=Decimal("7821060.9478"),
        metadata_time=datetime(
            2026,
            8,
            27,
            12,
            34,
            56,
            789654,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )
    daily = _stored("600000.SH", "DAILY", "2026-08-26T07:00:00.000Z")

    assert writer.write_bars([minute, daily, minute]) == 2
    assert len(calls) == 2
    minute_call = next(call for call in calls if b"bars_minute_v2" in call[2])
    row = json.loads(minute_call[2].splitlines()[1])
    assert row["open"] == "10.01"
    assert row["amount"] == "7821060.95"
    assert row["raw_capture_id"] == "capture-1"
    assert row["event_time"] == "2026-08-27 01:31:00.123"
    assert row["available_time"] == "2026-08-27 04:34:56.789"
    assert row["ingest_time"] == "2026-08-27 04:34:56.789"
    assert row["processing_time"] == "2026-08-27 04:34:56.789"
    assert minute_call[1]["x-clickhouse-key"] == "secret"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("12072.5"), "12072.50"),
        (Decimal("7821060.944"), "7821060.94"),
        (Decimal("7821060.945"), "7821060.95"),
    ],
)
def test_writer_rounds_amount_half_up_to_cny_cents(
    amount: Decimal,
    expected: str,
) -> None:
    calls: list[bytes] = []

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        calls.append(body)
        return 200, b""

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=transport,
    )

    assert (
        writer.write_bars([_stored("600000.SH", "MINUTE_1", "2026-08-27T01:31:00Z", amount=amount)])
        == 1
    )
    row = json.loads(calls[0].splitlines()[1])

    assert row["amount"] == expected


def test_writer_sanitizes_clickhouse_failure() -> None:
    def query_transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        return 200, b'{"row_count":0,"fingerprint_count":0}\n'

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=_failed_transport,
        query_transport=query_transport,
    )

    with pytest.raises(RuntimeError) as exc_info:
        writer.write_bars([_stored("600000.SH", "MINUTE_1", "2026-08-27T01:31:00Z")])

    assert str(exc_info.value) == "ClickHouse bar write transient failure (500)"
    assert "secret diagnostics" not in str(exc_info.value)


def test_writer_confirms_an_uncertain_write_before_reporting_success() -> None:
    writes = 0
    queries: list[bytes] = []

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal writes
        writes += 1
        raise TimeoutError("response was lost")

    def query_transport(
        _url: str,
        _headers: Mapping[str, str],
        body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        queries.append(body)
        return 200, b'{"row_count":1,"fingerprint_count":1}\n'

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=transport,
        query_transport=query_transport,
    )

    assert writer.write_bars([_stored("600000.SH", "MINUTE_1", "2026-08-27T01:31:00Z")]) == 1
    assert writes == 1
    assert len(queries) == 1
    assert b"revision_fingerprint" in queries[0]


def test_writer_retries_an_uncertain_write_only_after_absence_is_confirmed() -> None:
    writes = 0
    queries = 0

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal writes
        writes += 1
        if writes == 1:
            raise TimeoutError("response was lost")
        return 200, b""

    def query_transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal queries
        queries += 1
        return 200, b'{"row_count":0,"fingerprint_count":0}\n'

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=transport,
        query_transport=query_transport,
    )

    assert writer.write_bars([_stored("600000.SH", "MINUTE_1", "2026-08-27T01:31:00Z")]) == 1
    assert writes == 2
    assert queries == 1


def test_writer_uses_bounded_exponential_backoff_for_retries() -> None:
    writes = 0
    sleeps: list[float] = []

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal writes
        writes += 1
        return (200, b"") if writes == 3 else (503, b"")

    def query_transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        return 200, b'{"row_count":0,"fingerprint_count":0}\n'

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(
            url="http://clickhouse:8123",
            database="kunlun",
            user="writer",
            max_attempts=3,
            retry_backoff_seconds=0.2,
        ),
        transport=transport,
        query_transport=query_transport,
        sleeper=sleeps.append,
    )

    assert writer.write_bars([_stored("600000.SH", "DAILY", "2026-08-26T07:00:00Z")]) == 1
    assert writes == 3
    assert sleeps == [0.2, 0.4]


@pytest.mark.parametrize(
    ("status", "expected_message"),
    [
        (400, "ClickHouse bar write validation failed (400)"),
        (401, "ClickHouse bar write authorization failed (401)"),
    ],
)
def test_writer_does_not_retry_permanent_client_failures(
    status: int,
    expected_message: str,
) -> None:
    writes = 0
    queries = 0
    sleeps: list[float] = []

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal writes
        writes += 1
        return status, b"secret diagnostics"

    def query_transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal queries
        queries += 1
        return 200, b'{"row_count":0,"fingerprint_count":0}\n'

    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(url="http://clickhouse:8123", database="kunlun", user="writer"),
        transport=transport,
        query_transport=query_transport,
        sleeper=sleeps.append,
    )

    with pytest.raises(
        RuntimeError, match=expected_message.replace("(", r"\(").replace(")", r"\)")
    ):
        writer.write_bars([_stored("600000.SH", "DAILY", "2026-08-26T07:00:00Z")])

    assert writes == 1
    assert queries == 0
    assert sleeps == []


def test_writer_rejects_unsafe_database_identifier() -> None:
    with pytest.raises(ValueError, match="database"):
        ClickHouseBarConfig(
            url="http://clickhouse:8123", database="kunlun; DROP TABLE x", user="writer"
        )


def test_writer_config_repr_does_not_expose_password() -> None:
    config = ClickHouseBarConfig(
        url="http://clickhouse:8123",
        database="kunlun",
        user="writer",
        password="repr-secret",
    )

    assert "repr-secret" not in repr(config)
