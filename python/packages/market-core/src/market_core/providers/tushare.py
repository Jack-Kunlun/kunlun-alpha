"""Tushare Pro market-data adapter with a raw-first parsing boundary.

The adapter talks to the documented HTTP JSON protocol without importing the
vendor SDK. Credentials are accepted only through configuration, sent only in
the request body, and never retained in the capture identity or error text.
"""

from __future__ import annotations

import json
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ashare_contracts.market_data_bar import Bar
from ashare_contracts.market_data_tick import Tick
from ashare_contracts.providers import Capability, Cursor, Page

from market_core.instrument.code_parser import (
    ExchangeCode,
    is_market_data_code_for_exchange,
    parse_instrument_code,
)
from market_core.providers.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from market_core.providers.interfaces import MarketDataProvider

HttpTransport = Callable[[str, Mapping[str, str], bytes, float], tuple[int, bytes]]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MINUTE_INTERVALS = {"MINUTE_1": "1MIN", "MINUTE_5": "5MIN"}
_AUTH_CODES = {-2002, 2002, 40101}
_DAILY_FIELDS = "ts_code,trade_date,open,high,low,close,vol,amount"
_MINUTE_FIELDS = "ts_code,time,open,high,low,close,vol,amount"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stdlib_http_transport(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return int(response.status), response.read()
    except HTTPError as error:
        return error.code, b""
    except TimeoutError as error:
        raise ProviderTimeoutError() from error
    except URLError as error:
        raise ProviderUnavailableError() from error


@dataclass(frozen=True, slots=True)
class TushareConfig:
    """Connection settings for the Tushare HTTP API."""

    token: str = field(repr=False)
    endpoint: str = "https://api.tushare.pro"
    timeout_seconds: float = 8.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        token = self.token.strip()
        if not token:
            raise ValueError("token must be non-empty")
        endpoint = self.endpoint.strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Tushare endpoint must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Tushare endpoint must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Tushare endpoint must not contain query or fragment")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "endpoint", endpoint)


@dataclass(frozen=True, slots=True)
class TushareBarCapture:
    """Immutable raw response and non-secret request identity for one bar call."""

    body: bytes
    api_name: str
    request: str
    unified_code: str
    interval: str
    start_date: str
    end_date: str
    received_at: datetime
    source: str = "tushare-pro"
    source_version: str = ""
    content_type: str = "application/json; charset=utf-8"

    def __post_init__(self) -> None:
        for field_name in (
            "api_name",
            "request",
            "unified_code",
            "interval",
            "start_date",
            "end_date",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        for field_name in ("source", "content_type"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not self.source_version.strip():
            object.__setattr__(self, "source_version", f"tushare:{self.api_name}:v1")


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ProviderDataError(f"{field} must be an ISO date") from error


def _exchange(unified_code: str) -> ExchangeCode:
    parts = unified_code.rsplit(".", maxsplit=1)
    if len(parts) != 2 or parts[1] not in {"SH", "SZ", "BJ"}:
        raise ProviderDataError("unified_code is invalid")
    exchange = cast(ExchangeCode, parts[1])
    if not is_market_data_code_for_exchange(unified_code, exchange):
        raise ProviderDataError("unified_code is not a supported market identity")
    return exchange


def _is_exchange_index(unified_code: str) -> bool:
    code, exchange = unified_code.rsplit(".", maxsplit=1)
    return (exchange == "SH" and code.startswith("000")) or (
        exchange == "SZ" and code.startswith("399")
    )


def _api_name(unified_code: str, interval: str) -> tuple[str, dict[str, str]]:
    exchange = _exchange(unified_code)
    code = unified_code[:6]
    instrument = parse_instrument_code(code)
    is_index = _is_exchange_index(unified_code)
    is_fund = (
        not is_index
        and instrument is not None
        and instrument.exchange == exchange
        and instrument.type in {"ETF", "FUND", "LOF"}
    )

    if interval == "DAILY":
        api_name = "index_daily" if is_index else "fund_daily" if is_fund else "daily"
        return api_name, {}
    frequency = _MINUTE_INTERVALS.get(interval)
    if frequency is None:
        raise ProviderDataError("interval is not supported")
    api_name = "rt_idx_min_daily" if is_index else "rt_etf_min_daily" if is_fund else "rt_min_daily"
    return api_name, {"freq": frequency}


def validate_tushare_capture_profile(capture: object) -> TushareBarCapture:
    """Return a capture only when its route and semantic version are exact."""

    if not isinstance(capture, TushareBarCapture):
        raise ProviderDataError("Tushare capture type is invalid")
    try:
        expected_api_name, _ = _api_name(capture.unified_code, capture.interval)
    except ProviderDataError as error:
        raise ProviderDataError("unsupported Tushare capture profile") from error
    expected_source_version = f"tushare:{expected_api_name}:v1"
    if (
        capture.source != "tushare-pro"
        or capture.api_name != expected_api_name
        or capture.source_version != expected_source_version
    ):
        raise ProviderDataError("unsupported Tushare capture profile")
    return capture


def _decimal(value: object, *, field: str, row_index: int) -> Decimal:
    if value is None or isinstance(value, bool | float):
        raise ProviderDataError(f"row {row_index} has invalid {field}")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ProviderDataError(f"row {row_index} has invalid {field}") from error
    if not parsed.is_finite() or parsed < 0:
        raise ProviderDataError(f"row {row_index} has invalid {field}")
    return parsed


def _whole_units(
    value: object,
    *,
    field: str,
    row_index: int,
    multiplier: int = 1,
) -> int:
    scaled = _decimal(value, field=field, row_index=row_index) * multiplier
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ProviderDataError(f"row {row_index} has non-integral {field}")
    return int(integral)


def _timestamp(record: Mapping[str, object], *, daily: bool, row_index: int) -> datetime:
    if daily:
        raw = record.get("trade_date")
        if not isinstance(raw, str):
            raise ProviderDataError(f"row {row_index} has invalid trade_date")
        try:
            trading_date = datetime.strptime(raw, "%Y%m%d").date()
        except ValueError as error:
            raise ProviderDataError(f"row {row_index} has invalid trade_date") from error
        return datetime.combine(trading_date, time(15, 0), _SHANGHAI).astimezone(UTC)

    raw = record.get("time")
    if not isinstance(raw, str):
        raise ProviderDataError(f"row {row_index} has invalid time")
    try:
        local_time = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SHANGHAI)
    except ValueError as error:
        raise ProviderDataError(f"row {row_index} has invalid time") from error
    return local_time.astimezone(UTC)


def _response_records(body: bytes) -> list[dict[str, object]]:
    try:
        decoded = json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderDataError("provider returned malformed JSON") from error
    if not isinstance(decoded, dict):
        raise ProviderDataError("provider response must be an object")
    root = cast(dict[str, object], decoded)
    code = root.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        raise ProviderDataError("provider response code is invalid")
    if code in _AUTH_CODES:
        raise ProviderAuthError()
    if code != 0:
        raise ProviderDataError("provider rejected the request")
    data = root.get("data")
    if not isinstance(data, dict):
        raise ProviderDataError("provider response data is invalid")
    data_record = cast(dict[str, object], data)
    raw_fields = data_record.get("fields")
    raw_items = data_record.get("items")
    if not isinstance(raw_fields, list):
        raise ProviderDataError("provider response fields are invalid")
    field_values = cast(list[object], raw_fields)
    if not all(isinstance(field, str) for field in field_values):
        raise ProviderDataError("provider response fields are invalid")
    fields = cast(list[str], field_values)
    if len(fields) != len(set(fields)):
        raise ProviderDataError("provider response fields contain duplicates")
    if not isinstance(raw_items, list):
        raise ProviderDataError("provider response items are invalid")

    records: list[dict[str, object]] = []
    for row_index, raw_item in enumerate(cast(list[object], raw_items)):
        if not isinstance(raw_item, list):
            raise ProviderDataError(f"row {row_index} does not match provider fields")
        row = cast(list[object], raw_item)
        if len(row) != len(fields):
            raise ProviderDataError(f"row {row_index} does not match provider fields")
        records.append(dict(zip(fields, row, strict=True)))
    return records


class TushareMarketDataProvider(MarketDataProvider):
    """Concrete daily and current-day minute Bar provider."""

    def __init__(
        self,
        config: TushareConfig,
        *,
        transport: HttpTransport = _stdlib_http_transport,
        clock: Clock = _utc_now,
        sleeper: Sleeper = time_module.sleep,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock
        self._sleeper = sleeper

    def _request(self, body: bytes) -> bytes:
        transient_errors = (
            ProviderRateLimitError,
            ProviderTimeoutError,
            ProviderUnavailableError,
        )
        for attempt in range(self._config.max_attempts):
            try:
                try:
                    status, response_body = self._transport(
                        self._config.endpoint,
                        {"content-type": "application/json; charset=utf-8"},
                        body,
                        self._config.timeout_seconds,
                    )
                except ProviderError:
                    raise
                except TimeoutError as error:
                    raise ProviderTimeoutError() from error
                except OSError as error:
                    raise ProviderUnavailableError() from error
                except Exception as error:
                    raise ProviderUnavailableError() from error
                if status in {401, 403}:
                    raise ProviderAuthError()
                if status == 404:
                    raise ProviderNotFoundError()
                if status == 429:
                    raise ProviderRateLimitError()
                if status >= 500:
                    raise ProviderUnavailableError()
                if not 200 <= status < 300:
                    raise ProviderDataError(f"provider HTTP request failed ({status})")
                return response_body
            except transient_errors:
                if attempt + 1 >= self._config.max_attempts:
                    raise
                self._sleeper(self._config.retry_backoff_seconds * (2**attempt))
        raise ProviderUnavailableError("provider retry budget exhausted")

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_DAILY_BARS, Capability.FETCH_MINUTE_BARS})

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: Cursor | None = None,
    ) -> TushareBarCapture:
        if cursor is not None:
            raise ProviderDataError("Tushare bar endpoints do not use cursors")
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
        if end < start:
            raise ProviderDataError("end_date must not precede start_date")
        api_name, params = _api_name(unified_code, interval)
        request_time: datetime | None = None
        if interval == "DAILY":
            params.update(
                {
                    "ts_code": unified_code,
                    "start_date": start.strftime("%Y%m%d"),
                    "end_date": end.strftime("%Y%m%d"),
                }
            )
        else:
            request_time = self._clock()
            if request_time.tzinfo is None or request_time.utcoffset() is None:
                raise ProviderDataError("provider clock must be timezone-aware")
            request_time = request_time.astimezone(UTC)
            local_date = request_time.astimezone(_SHANGHAI).date()
            if start != local_date or end != local_date:
                raise ProviderDataError("realtime minute endpoints only support the current date")
            params["ts_code"] = unified_code

        payload = {
            "api_name": api_name,
            "token": self._config.token,
            "params": params,
            "fields": _DAILY_FIELDS if interval == "DAILY" else _MINUTE_FIELDS,
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        response_body = self._request(body)
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ProviderDataError("provider clock must be timezone-aware")
        received_at = received_at.astimezone(UTC)

        safe_params = urlencode(sorted(params.items()))
        return TushareBarCapture(
            body=response_body,
            api_name=api_name,
            request=f"POST /?api_name={api_name}&{safe_params}",
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=received_at,
        )

    def parse_bars(self, capture: object) -> list[Bar]:
        capture = validate_tushare_capture_profile(capture)
        records = _response_records(capture.body)
        exchange = _exchange(capture.unified_code)
        daily = capture.interval == "DAILY"
        requested_start = _parse_date(capture.start_date, "start_date")
        requested_end = _parse_date(capture.end_date, "end_date")
        bars: list[Bar] = []
        for row_index, record in enumerate(records):
            row_code = record.get("ts_code", record.get("code"))
            if row_code != capture.unified_code:
                raise ProviderDataError(f"row {row_index} has unexpected ts_code")
            timestamp = _timestamp(record, daily=daily, row_index=row_index)
            trading_date = timestamp.astimezone(_SHANGHAI).date()
            if not requested_start <= trading_date <= requested_end:
                raise ProviderDataError(f"row {row_index} is outside requested date range")
            volume = _whole_units(
                record.get("vol"),
                field="vol",
                row_index=row_index,
                multiplier=100 if daily else 1,
            )
            amount = _decimal(record.get("amount"), field="amount", row_index=row_index)
            if daily:
                amount *= 1000
            try:
                bar = Bar.model_validate(
                    {
                        "unifiedCode": capture.unified_code,
                        "exchange": exchange,
                        "date": trading_date,
                        "interval": capture.interval,
                        "session": "CONTINUOUS",
                        "timestamp": timestamp,
                        "open": _decimal(record.get("open"), field="open", row_index=row_index),
                        "high": _decimal(record.get("high"), field="high", row_index=row_index),
                        "low": _decimal(record.get("low"), field="low", row_index=row_index),
                        "close": _decimal(record.get("close"), field="close", row_index=row_index),
                        "volume": volume,
                        "amount": amount,
                        "priceType": "RAW",
                    }
                )
            except (TypeError, ValueError) as error:
                raise ProviderDataError(f"row {row_index} failed Bar validation") from error
            bars.append(bar)
        return bars

    def fetch_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: Cursor | None = None,
    ) -> Page[Bar]:
        capture = self.fetch_raw_bars(
            unified_code,
            interval,
            start_date,
            end_date,
            cursor,
        )
        return Page(items=self.parse_bars(capture), next_cursor=None)

    def fetch_ticks(
        self,
        unified_code: str,
        date: str,
        cursor: Cursor | None = None,
    ) -> Page[Tick]:
        del unified_code, date, cursor
        raise NotImplementedError("TushareMarketDataProvider does not expose executed ticks")


__all__ = [
    "HttpTransport",
    "TushareBarCapture",
    "TushareConfig",
    "TushareMarketDataProvider",
    "validate_tushare_capture_profile",
]
