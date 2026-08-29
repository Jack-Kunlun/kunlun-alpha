"""Contract tests for the concrete Tushare Pro market-data adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ashare_contracts.providers import Capability
from market_core.providers import ProviderAuthError, ProviderDataError, ProviderUnavailableError
from market_core.providers.tushare import (
    TushareBarCapture,
    TushareConfig,
    TushareMarketDataProvider,
)


def _response(fields: list[str], items: list[list[object]], *, code: int = 0) -> bytes:
    return json.dumps(
        {"code": code, "msg": "credential diagnostics", "data": {"fields": fields, "items": items}},
        ensure_ascii=False,
    ).encode("utf-8")


def _permission_denied_transport(
    _url: str,
    _headers: Mapping[str, str],
    _body: bytes,
    _timeout: float,
) -> tuple[int, bytes]:
    return 200, _response([], [], code=40101)


def _malformed_row_transport(
    _url: str,
    _headers: Mapping[str, str],
    _body: bytes,
    _timeout: float,
) -> tuple[int, bytes]:
    return 200, _response(
        ["ts_code", "time", "open", "high", "low", "close", "vol", "amount"],
        [["600000.SH", "2026-08-27 09:31:00", None, 10.08, 9.99, 10.06, 1200, 12072]],
    )


def _outside_range_transport(
    _url: str,
    _headers: Mapping[str, str],
    _body: bytes,
    _timeout: float,
) -> tuple[int, bytes]:
    return 200, _response(
        ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
        [["600000.SH", "20260825", 10, 10, 10, 10, 1, 1]],
    )


def test_realtime_minute_capture_is_safe_and_parses_exact_values() -> None:
    calls: list[tuple[str, Mapping[str, str], bytes, float]] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        calls.append((url, headers, body, timeout_seconds))
        return 200, _response(
            ["ts_code", "time", "open", "high", "low", "close", "vol", "amount"],
            [["600000.SH", "2026-08-27 09:31:00", 10.01, 10.08, 9.99, 10.06, 1200, 12072.5]],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="top-secret", endpoint="https://api.tushare.pro"),
        transport=transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")
    bars = provider.parse_bars(capture)

    payload = json.loads(calls[0][2])
    assert payload["api_name"] == "rt_min_daily"
    assert payload["params"] == {"freq": "1MIN", "ts_code": "600000.SH"}
    assert payload["token"] == "top-secret"
    assert "top-secret" not in capture.request
    assert bars[0].timestamp == datetime(2026, 8, 27, 1, 31, tzinfo=UTC)
    assert bars[0].open == Decimal("10.01")
    assert bars[0].amount == Decimal("12072.5")
    assert bars[0].volume == 1200
    assert provider.capabilities() == frozenset(
        {Capability.FETCH_DAILY_BARS, Capability.FETCH_MINUTE_BARS}
    )


def test_received_at_is_response_completion_after_minute_date_check() -> None:
    events: list[str] = []
    request_time = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    response_time = datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC)
    clock_values = iter((request_time, response_time))

    def clock() -> datetime:
        events.append("clock")
        return next(clock_values)

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        events.append("transport")
        return 200, _response(
            ["ts_code", "time", "open", "high", "low", "close", "vol", "amount"],
            [["600000.SH", "2026-08-27 09:31:00", 10, 10, 10, 10, 1, 1]],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=transport,
        clock=clock,
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")

    assert events == ["clock", "transport", "clock"]
    assert capture.received_at == response_time


def test_minute_rows_preserve_upstream_order_after_capture_replay() -> None:
    def transport(
        _url: str, _headers: Mapping[str, str], body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        assert json.loads(body)["api_name"] == "rt_min_daily"
        return 200, _response(
            ["ts_code", "time", "open", "high", "low", "close", "vol", "amount"],
            [
                ["600000.SH", "2026-08-27 09:32:00", 10.01, 10.08, 9.99, 10.07, 1200, 12084],
                ["600000.SH", "2026-08-27 09:31:00", 10.01, 10.08, 9.99, 10.06, 1200, 12072],
            ],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    page = provider.fetch_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")

    assert [bar.timestamp for bar in page.items] == [
        datetime(2026, 8, 27, 1, 32, tzinfo=UTC),
        datetime(2026, 8, 27, 1, 31, tzinfo=UTC),
    ]


def test_index_minute_uses_dedicated_api_and_market_bar_contract() -> None:
    def transport(
        _url: str, _headers: Mapping[str, str], body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        assert json.loads(body)["api_name"] == "rt_idx_min_daily"
        return 200, _response(
            ["ts_code", "time", "open", "high", "low", "close", "vol", "amount"],
            [["000001.SH", "2026-08-27 11:29:00", 3820.1, 3825.2, 3818.4, 3824.6, 12345, 456789]],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    page = provider.fetch_bars("000001.SH", "MINUTE_1", "2026-08-27", "2026-08-27")

    assert page.next_cursor is None
    assert page.items[0].unified_code == "000001.SH"
    assert page.items[0].close == Decimal("3824.6")


def test_daily_units_are_converted_from_lots_and_thousand_yuan() -> None:
    def transport(
        _url: str, _headers: Mapping[str, str], body: bytes, _timeout: float
    ) -> tuple[int, bytes]:
        assert json.loads(body)["api_name"] == "daily"
        return 200, _response(
            ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
            [["600000.SH", "20260826", 10.0, 10.2, 9.8, 10.1, 123.45, 67.891]],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    page = provider.fetch_bars("600000.SH", "DAILY", "2026-08-20", "2026-08-26")

    assert page.items[0].timestamp == datetime(2026, 8, 26, 7, 0, tzinfo=UTC)
    assert page.items[0].volume == 12345
    assert page.items[0].amount == Decimal("67891")


@pytest.mark.parametrize(
    ("unified_code", "interval", "api_name"),
    [
        ("600000.SH", "DAILY", "daily"),
        ("600000.SH", "MINUTE_1", "rt_min_daily"),
        ("600000.SH", "MINUTE_5", "rt_min_daily"),
        ("000001.SH", "DAILY", "index_daily"),
        ("000001.SH", "MINUTE_1", "rt_idx_min_daily"),
        ("000001.SH", "MINUTE_5", "rt_idx_min_daily"),
        ("518880.SH", "DAILY", "fund_daily"),
        ("518880.SH", "MINUTE_1", "rt_etf_min_daily"),
        ("518880.SH", "MINUTE_5", "rt_etf_min_daily"),
    ],
)
def test_supported_capture_profiles_accept_all_instrument_interval_routes(
    unified_code: str,
    interval: str,
    api_name: str,
) -> None:
    capture = TushareBarCapture(
        body=_response([], []),
        api_name=api_name,
        request="POST /?api_name=profile-test",
        unified_code=unified_code,
        interval=interval,
        start_date="2026-08-26",
        end_date="2026-08-26",
        received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    assert TushareMarketDataProvider(TushareConfig(token="secret")).parse_bars(capture) == []


@pytest.mark.parametrize(
    ("source", "api_name", "interval", "source_version"),
    [
        ("tushare-sandbox", "daily", "DAILY", "tushare:daily:v1"),
        ("tushare-pro", "fund_daily", "DAILY", "tushare:fund_daily:v1"),
        ("tushare-pro", "daily", "MINUTE_1", "tushare:daily:v1"),
        ("tushare-pro", "daily", "DAILY", "tushare:daily:v2"),
    ],
)
def test_capture_profile_mismatch_is_rejected_before_body_parsing(
    source: str,
    api_name: str,
    interval: str,
    source_version: str,
) -> None:
    capture = TushareBarCapture(
        body=b"provider-body-secret",
        api_name=api_name,
        request="POST /?token=request-secret",
        unified_code="600000.SH",
        interval=interval,
        start_date="2026-08-26",
        end_date="2026-08-26",
        received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        source=source,
        source_version=source_version,
    )

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile") as exc_info:
        TushareMarketDataProvider(TushareConfig(token="token-secret")).parse_bars(capture)

    assert "provider-body-secret" not in str(exc_info.value)
    assert "request-secret" not in str(exc_info.value)
    assert "token-secret" not in str(exc_info.value)


def test_permission_error_is_classified_without_leaking_token_or_vendor_message() -> None:
    provider = TushareMarketDataProvider(
        TushareConfig(token="top-secret"),
        transport=_permission_denied_transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    with pytest.raises(ProviderAuthError) as exc_info:
        provider.fetch_bars("600000.SH", "DAILY", "2026-08-20", "2026-08-26")

    assert "top-secret" not in str(exc_info.value)
    assert "credential diagnostics" not in str(exc_info.value)


def test_malformed_row_is_rejected_instead_of_silently_dropped() -> None:
    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=_malformed_row_transport,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")
    with pytest.raises(ProviderDataError, match="row 0"):
        provider.parse_bars(capture)


def test_row_outside_requested_date_range_is_rejected() -> None:
    provider = TushareMarketDataProvider(
        TushareConfig(token="secret"),
        transport=_outside_range_transport,
    )

    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    with pytest.raises(ProviderDataError, match="outside requested date range"):
        provider.parse_bars(capture)


def test_plain_http_endpoint_is_rejected_before_credentials_can_be_sent() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        TushareConfig(token="secret", endpoint="http://api.tushare.pro")


def test_transient_failures_use_bounded_exponential_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return 503, b"upstream diagnostics"
        return 200, _response(
            ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"],
            [["600000.SH", "20260826", 10, 10, 10, 10, 1, 1]],
        )

    provider = TushareMarketDataProvider(
        TushareConfig(token="secret", max_attempts=3, retry_backoff_seconds=0.25),
        transport=transport,
        sleeper=sleeps.append,
    )

    assert provider.fetch_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26").items
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_transient_retry_exhaustion_is_bounded_and_credentials_are_not_repr_visible() -> None:
    attempts = 0

    def transport(
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        nonlocal attempts
        attempts += 1
        return 503, b"upstream diagnostics"

    config = TushareConfig(token="repr-secret", max_attempts=2, retry_backoff_seconds=0.01)
    provider = TushareMarketDataProvider(config, transport=transport, sleeper=lambda _delay: None)

    with pytest.raises(ProviderUnavailableError):
        provider.fetch_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    assert attempts == 2
    assert "repr-secret" not in repr(config)
