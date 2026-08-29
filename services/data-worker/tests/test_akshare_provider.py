"""Contract tests for the public-function AKShare market-data adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from ashare_contracts.providers import Capability
from data_worker.providers.akshare import (
    AKShareBarCapture,
    AKShareConfig,
    AKShareMarketDataProvider,
)
from market_core.providers import ProviderDataError, ProviderUnavailableError


class FakeDataFrame:
    """Small DataFrame double exposing only the public methods we consume."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.columns = tuple(rows[0]) if rows else ()

    def to_json(self, **_kwargs: object) -> str:
        return json.dumps(
            self._rows,
            ensure_ascii=False,
            default=str,
        )


class FakeAKShareClient:
    def __init__(self, frames: Mapping[str, FakeDataFrame] | None = None) -> None:
        self.frames = dict(frames or {})
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __getattr__(self, name: str):
        if name not in self.frames:
            raise AttributeError(name)

        def endpoint(**kwargs: object) -> FakeDataFrame:
            self.calls.append((name, kwargs))
            return self.frames[name]

        return endpoint


def _daily_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "日期": "2026-08-26",
        "股票代码": "600000",
        "开盘": "10.01",
        "收盘": "10.06",
        "最高": "10.08",
        "最低": "9.99",
        "成交量": "12345",
        "成交额": "67891.25",
    }
    row.update(overrides)
    return row


def _minute_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "day": "2026-08-27 09:31:00",
        "股票代码": "600000",
        "开盘": "10.01",
        "收盘": "10.06",
        "最高": "10.08",
        "最低": "9.99",
        "成交量": "1234",
        "成交额": "1234.50",
    }
    row.update(overrides)
    return row


def _profile_capture(
    *,
    source: str,
    api_name: str,
    interval: str,
    source_version: str,
    unified_code: str = "600000.SH",
) -> AKShareBarCapture:
    row = _daily_row() if interval == "DAILY" else _minute_row()
    row["股票代码"] = unified_code[:6]
    body = json.dumps(
        [row],
        ensure_ascii=False,
    ).encode("utf-8")
    return AKShareBarCapture(
        body=body,
        api_name=api_name,
        request=f"GET /akshare/{api_name}?code=600000",
        unified_code=unified_code,
        interval=interval,
        start_date="2026-08-26" if interval == "DAILY" else "2026-08-27",
        end_date="2026-08-26" if interval == "DAILY" else "2026-08-27",
        received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        source=source,
        source_version=source_version,
    )


@pytest.mark.parametrize(
    ("unified_code", "interval", "method", "source", "period", "symbol"),
    [
        ("600000.SH", "DAILY", "stock_zh_a_hist_tx", "akshare-tencent", None, "sh600000"),
        ("600000.SH", "MINUTE_1", "stock_zh_a_minute", "akshare-sina", "1", "sh600000"),
        ("600000.SH", "MINUTE_5", "stock_zh_a_minute", "akshare-sina", "5", "sh600000"),
        ("518880.SH", "DAILY", "stock_zh_a_hist_tx", "akshare-tencent", None, "sh518880"),
        ("518880.SH", "MINUTE_1", "stock_zh_a_minute", "akshare-sina", "1", "sh518880"),
        ("000001.SH", "DAILY", "stock_zh_a_hist_tx", "akshare-tencent", None, "sh000001"),
        ("000001.SH", "MINUTE_5", "stock_zh_a_minute", "akshare-sina", "5", "sh000001"),
        ("399001.SZ", "DAILY", "stock_zh_a_hist_tx", "akshare-tencent", None, "sz399001"),
        ("399001.SZ", "MINUTE_1", "stock_zh_a_minute", "akshare-sina", "1", "sz399001"),
        ("300750.SZ", "MINUTE_5", "stock_zh_a_minute", "akshare-sina", "5", "sz300750"),
    ],
)
def test_public_endpoint_routing_uses_prefixed_symbols(
    unified_code: str,
    interval: str,
    method: str,
    source: str,
    period: str | None,
    symbol: str,
) -> None:
    frame = FakeDataFrame([_daily_row()] if interval == "DAILY" else [_minute_row()])
    client = FakeAKShareClient({method: frame})
    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=client,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    capture = provider.fetch_raw_bars(unified_code, interval, "2026-08-26", "2026-08-27")

    assert capture.api_name == method
    assert capture.source == source
    assert capture.source_version == f"akshare:1.18.94:{method}:v2"
    assert capture.content_type == "application/json; charset=utf-8"
    assert len(client.calls) == 1
    called_method, kwargs = client.calls[0]
    assert called_method == method
    assert kwargs["symbol"] == symbol
    if interval == "DAILY":
        assert kwargs["start_date"] == "20260826"
        assert kwargs["end_date"] == "20260827"
        assert kwargs["adjust"] == ""
        assert "period" not in kwargs
    else:
        assert kwargs["period"] == period
        assert kwargs["adjust"] == ""
        assert "start_date" not in kwargs
        assert "end_date" not in kwargs


def test_dataframe_payload_is_captured_before_exact_normalization() -> None:
    client = FakeAKShareClient({"stock_zh_a_hist_tx": FakeDataFrame([_daily_row()])})
    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=client,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    payload = json.loads(capture.body)

    assert payload[0]["成交量"] == "12345"
    bars = provider.parse_bars(capture)
    assert bars[0].timestamp == datetime(2026, 8, 26, 7, 0, tzinfo=UTC)
    assert bars[0].open == Decimal("10.01")
    assert bars[0].amount == Decimal("67891.25")
    assert bars[0].volume == 12345
    assert provider.capabilities() == frozenset(
        {Capability.FETCH_DAILY_BARS, Capability.FETCH_MINUTE_BARS}
    )


def test_serialized_capture_body_is_the_only_replay_input() -> None:
    client = FakeAKShareClient({"stock_zh_a_hist_tx": FakeDataFrame([_daily_row()])})
    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=client,
    )

    captured = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    replayed = AKShareBarCapture(
        body=captured.body,
        api_name=captured.api_name,
        request=captured.request,
        unified_code=captured.unified_code,
        interval=captured.interval,
        start_date=captured.start_date,
        end_date=captured.end_date,
        received_at=captured.received_at,
        source=captured.source,
        source_version=captured.source_version,
        content_type=captured.content_type,
    )

    assert provider.parse_bars(replayed)[0].close == Decimal("10.06")


def test_serialized_pandas_iso_datetime_in_capture_body_replays_as_daily_bar() -> None:
    body = json.dumps([_daily_row(**{"日期": "2026-08-20T00:00:00.000"})]).encode("utf-8")
    capture = AKShareBarCapture(
        body=body,
        api_name="stock_zh_a_hist",
        request="GET /akshare/stock_zh_a_hist?code=600000&date=2026-08-20:2026-08-20",
        unified_code="600000.SH",
        interval="DAILY",
        start_date="2026-08-20",
        end_date="2026-08-20",
        received_at=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
        source_version="akshare:1.18.94:stock_zh_a_hist:v1",
    )

    provider = AKShareMarketDataProvider()

    assert provider.parse_bars(capture)[0].timestamp == datetime(2026, 8, 20, 7, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-20T00:00:00.000+08:00",
        "2026-08-20T00:00:00Z",
    ],
)
def test_daily_timestamp_accepts_iso_datetime_with_timezone(value: str) -> None:
    body = json.dumps([_daily_row(**{"日期": value})]).encode("utf-8")
    capture = AKShareBarCapture(
        body=body,
        api_name="stock_zh_a_hist",
        request="GET /akshare/stock_zh_a_hist?code=600000&date=2026-08-20:2026-08-20",
        unified_code="600000.SH",
        interval="DAILY",
        start_date="2026-08-20",
        end_date="2026-08-20",
        received_at=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
        source_version="akshare:1.18.94:stock_zh_a_hist:v1",
    )

    assert AKShareMarketDataProvider().parse_bars(capture)[0].timestamp == datetime(
        2026, 8, 20, 7, 0, tzinfo=UTC
    )


@pytest.mark.parametrize("value", ["2026/08/20", "2026-08-20T", "not-a-date"])
def test_daily_timestamp_still_rejects_malformed_iso_datetime(value: str) -> None:
    body = json.dumps([_daily_row(**{"日期": value})]).encode("utf-8")
    capture = AKShareBarCapture(
        body=body,
        api_name="stock_zh_a_hist",
        request="GET /akshare/stock_zh_a_hist?code=600000&date=2026-08-20:2026-08-20",
        unified_code="600000.SH",
        interval="DAILY",
        start_date="2026-08-20",
        end_date="2026-08-20",
        received_at=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
        source_version="akshare:1.18.94:stock_zh_a_hist:v1",
    )

    with pytest.raises(ProviderDataError, match="invalid date"):
        AKShareMarketDataProvider().parse_bars(capture)


def test_received_at_is_taken_after_sdk_call_and_payload_serialization() -> None:
    events: list[str] = []

    class SequencedFrame(FakeDataFrame):
        def to_json(self, **kwargs: object) -> str:
            events.append("serialize")
            return super().to_json(**kwargs)

    class SequencedClient:
        def stock_zh_a_hist_tx(self, **_kwargs: object) -> SequencedFrame:
            events.append("sdk")
            return SequencedFrame([_daily_row()])

    def clock() -> datetime:
        events.append("clock")
        return datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC)

    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=SequencedClient(),
        clock=clock,
    )

    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    assert events == ["sdk", "serialize", "clock"]
    assert capture.received_at == datetime(2026, 8, 27, 4, 0, 5, tzinfo=UTC)


def test_minute_timestamp_and_sina_shares_are_not_scaled() -> None:
    client = FakeAKShareClient({"stock_zh_a_minute": FakeDataFrame([_minute_row()])})
    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=client,
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")
    bar = provider.parse_bars(capture)[0]

    assert bar.timestamp == datetime(2026, 8, 27, 1, 31, tzinfo=UTC)
    assert bar.date == date(2026, 8, 27)
    assert capture.source == "akshare-sina"
    assert bar.volume == 1234
    assert bar.amount == Decimal("1234.50")


def test_historical_eastmoney_capture_still_converts_hands_to_shares() -> None:
    row = _minute_row(**{"成交量": "12.34"})
    row["时间"] = row.pop("day")
    capture = AKShareBarCapture(
        body=json.dumps([row], ensure_ascii=False).encode("utf-8"),
        api_name="stock_zh_a_hist_min_em",
        request="GET /akshare/stock_zh_a_hist_min_em?code=600000",
        unified_code="600000.SH",
        interval="MINUTE_1",
        start_date="2026-08-27",
        end_date="2026-08-27",
        received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        source="akshare-eastmoney",
        source_version="akshare:1.18.94:stock_zh_a_hist_min_em:v1",
    )

    assert AKShareMarketDataProvider().parse_bars(capture)[0].volume == 1234


def test_historical_eastmoney_index_minute_5_rejects_ambiguous_price_semantics() -> None:
    row = _minute_row(**{"成交量": "1234"})
    capture = AKShareBarCapture(
        body=json.dumps([row], ensure_ascii=False).encode("utf-8"),
        api_name="index_zh_a_hist_min_em",
        request="GET /akshare/index_zh_a_hist_min_em?code=000001",
        unified_code="000001.SH",
        interval="MINUTE_5",
        start_date="2026-08-27",
        end_date="2026-08-27",
        received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        source="akshare-eastmoney",
        source_version="akshare:1.18.94:index_zh_a_hist_min_em:v1",
    )

    with pytest.raises(ProviderDataError, match="unsupported|ambiguous.*price semantics"):
        AKShareMarketDataProvider().parse_bars(capture)


@pytest.mark.parametrize(
    ("source", "api_name", "interval", "source_version"),
    [
        (
            "akshare-sina",
            "stock_zh_a_hist_tx",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_hist_tx:v2",
        ),
        (
            "akshare-tencent",
            "stock_zh_a_hist",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_hist:v1",
        ),
        (
            "akshare-sina",
            "stock_zh_a_minute",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_minute:v2",
        ),
        (
            "akshare-sina",
            "stock_zh_a_minute",
            "MINUTE_1",
            "akshare:99.0.0:stock_zh_a_minute:v99",
        ),
    ],
)
def test_capture_profile_mismatch_is_rejected_before_row_parsing(
    source: str,
    api_name: str,
    interval: str,
    source_version: str,
) -> None:
    capture = _profile_capture(
        source=source,
        api_name=api_name,
        interval=interval,
        source_version=source_version,
    )

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile"):
        AKShareMarketDataProvider().parse_bars(capture)


@pytest.mark.parametrize(
    ("api_name", "interval", "unified_code"),
    [
        ("stock_zh_a_hist", "DAILY", "518880.SH"),
        ("stock_zh_a_hist", "DAILY", "000001.SH"),
        ("stock_zh_a_hist", "DAILY", "399001.SZ"),
        ("stock_zh_a_hist_min_em", "MINUTE_1", "518880.SH"),
        ("stock_zh_a_hist_min_em", "MINUTE_1", "000001.SH"),
        ("stock_zh_a_hist_min_em", "MINUTE_1", "399001.SZ"),
    ],
)
def test_legacy_allowlisted_profile_requires_stock_instrument_kind(
    api_name: str,
    interval: str,
    unified_code: str,
) -> None:
    capture = _profile_capture(
        source="akshare-eastmoney",
        api_name=api_name,
        interval=interval,
        source_version=f"akshare:1.18.94:{api_name}:v1",
        unified_code=unified_code,
    )

    with pytest.raises(ProviderDataError, match="unsupported.*capture profile"):
        AKShareMarketDataProvider().parse_bars(capture)


def test_minute_rows_preserve_upstream_order_after_capture_replay() -> None:
    rows = [
        _minute_row(**{"day": "2026-08-27 09:32:00", "收盘": "10.07"}),
        _minute_row(**{"day": "2026-08-27 09:31:00", "收盘": "10.06"}),
    ]
    client = FakeAKShareClient({"stock_zh_a_minute": FakeDataFrame(rows)})
    provider = AKShareMarketDataProvider(
        AKShareConfig(sdk_version="1.18.94", max_attempts=1),
        client=client,
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")
    bars = provider.parse_bars(capture)

    assert [bar.timestamp for bar in bars] == [
        datetime(2026, 8, 27, 1, 32, tzinfo=UTC),
        datetime(2026, 8, 27, 1, 31, tzinfo=UTC),
    ]


def test_sina_minute_overfetch_is_retained_in_raw_and_filtered_by_requested_date() -> None:
    rows = [
        _minute_row(**{"day": "2026-08-26 09:31:00"}),
        _minute_row(**{"day": "2026-08-27 09:31:00"}),
    ]
    client = FakeAKShareClient({"stock_zh_a_minute": FakeDataFrame(rows)})
    provider = AKShareMarketDataProvider(
        AKShareConfig(max_attempts=1),
        client=client,
    )

    capture = provider.fetch_raw_bars("600000.SH", "MINUTE_1", "2026-08-27", "2026-08-27")

    assert len(json.loads(capture.body)) == 2
    assert client.calls[0][1] == {"symbol": "sh600000", "period": "1", "adjust": ""}
    bars = provider.parse_bars(capture)
    assert len(bars) == 1
    assert bars[0].date == date(2026, 8, 27)

    evidenced = provider.parse_bars_with_evidence(capture)
    assert evidenced.bars == bars
    assert len(evidenced.exclusions) == 1
    exclusion = evidenced.exclusions[0]
    assert exclusion.raw_row_index == 0
    assert exclusion.timestamp == datetime(2026, 8, 26, 1, 31, tzinfo=UTC)
    assert exclusion.requested_start == date(2026, 8, 27)
    assert exclusion.requested_end == date(2026, 8, 27)
    assert exclusion.reason_code == "SINA_OVERFETCH_OUTSIDE_REQUEST"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("开盘", True),
        ("收盘", float("nan")),
        ("最高", float("inf")),
        ("最低", "-0.01"),
        ("成交量", "-1"),
        ("成交额", "-1"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    client = FakeAKShareClient(
        {"stock_zh_a_hist_tx": FakeDataFrame([_daily_row(**{field: value})])}
    )
    provider = AKShareMarketDataProvider(
        AKShareConfig(max_attempts=1),
        client=client,
    )
    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    with pytest.raises(ProviderDataError, match="row 0"):
        provider.parse_bars(capture)


def test_missing_column_is_rejected_instead_of_dropped() -> None:
    row = _daily_row()
    del row["最低"]
    client = FakeAKShareClient({"stock_zh_a_hist_tx": FakeDataFrame([row])})
    provider = AKShareMarketDataProvider(AKShareConfig(max_attempts=1), client=client)
    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    with pytest.raises(ProviderDataError, match="missing.*low"):
        provider.parse_bars(capture)


def test_unexpected_row_code_and_out_of_range_date_are_rejected() -> None:
    client = FakeAKShareClient(
        {
            "stock_zh_a_hist_tx": FakeDataFrame([_daily_row(**{"股票代码": "600001"})]),
        }
    )
    provider = AKShareMarketDataProvider(AKShareConfig(max_attempts=1), client=client)
    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    with pytest.raises(ProviderDataError, match="unexpected.*code"):
        provider.parse_bars(capture)

    client.frames["stock_zh_a_hist_tx"] = FakeDataFrame([_daily_row(**{"日期": "2026-08-25"})])
    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    with pytest.raises(ProviderDataError, match="outside requested date range"):
        provider.parse_bars(capture)


def test_empty_dataframe_is_a_valid_empty_capture() -> None:
    client = FakeAKShareClient({"stock_zh_a_hist_tx": FakeDataFrame([])})
    provider = AKShareMarketDataProvider(AKShareConfig(max_attempts=1), client=client)

    capture = provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")

    assert isinstance(capture, AKShareBarCapture)
    assert provider.parse_bars(capture) == []
    assert json.loads(capture.body) == []


def test_sdk_failures_retry_with_bounded_backoff_and_sanitized_error() -> None:
    attempts = 0
    sleeps: list[float] = []

    class FlakyClient:
        def stock_zh_a_hist_tx(self, **_kwargs: object) -> FakeDataFrame:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("upstream payload contains secret-value")
            return FakeDataFrame([_daily_row()])

    provider = AKShareMarketDataProvider(
        AKShareConfig(max_attempts=3, retry_backoff_seconds=0.25, sdk_version="1.18.94"),
        client=FlakyClient(),
        sleeper=sleeps.append,
    )

    assert provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26").body
    assert attempts == 3
    assert sleeps == [0.25, 0.5]

    class DownClient:
        def stock_zh_a_hist_tx(self, **_kwargs: object) -> FakeDataFrame:
            raise RuntimeError("secret-value upstream body")

    provider = AKShareMarketDataProvider(
        AKShareConfig(max_attempts=2, retry_backoff_seconds=0.01),
        client=DownClient(),
        sleeper=lambda _delay: None,
    )
    with pytest.raises(ProviderUnavailableError) as exc_info:
        provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    assert "secret-value" not in str(exc_info.value)


def test_schema_exception_is_classified_as_data_error_without_retry() -> None:
    attempts = 0

    class BadClient:
        def stock_zh_a_hist_tx(self, **_kwargs: object) -> FakeDataFrame:
            nonlocal attempts
            attempts += 1
            raise ValueError("bad provider schema")

    provider = AKShareMarketDataProvider(
        AKShareConfig(max_attempts=3),
        client=BadClient(),
        sleeper=lambda _delay: None,
    )

    with pytest.raises(ProviderDataError):
        provider.fetch_raw_bars("600000.SH", "DAILY", "2026-08-26", "2026-08-26")
    assert attempts == 1
