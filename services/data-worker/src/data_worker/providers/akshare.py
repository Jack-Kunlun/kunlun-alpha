"""AKShare market-data adapter for free, local research synchronization.

AKShare returns a pandas ``DataFrame`` from public Tencent- and Sina-backed
functions. The adapter serializes that SDK-returned table before converting any
values so the collector can preserve the unnormalized adapter payload as raw
evidence. This is an adapter-payload capture, not a wire-level HTTP capture.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Literal, cast
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
    ProviderDataError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from market_core.providers.interfaces import MarketDataProvider

from data_worker.providers.models import (
    SINA_OVERFETCH_OUTSIDE_REQUEST,
    BarExclusion,
    ProviderParseResult,
)

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
ClientFactory = Callable[[], object]

_LEGACY_SOURCE = "akshare-eastmoney"
_DAILY_SOURCE = "akshare-tencent"
_MINUTE_SOURCE = "akshare-sina"
_SOURCE = _LEGACY_SOURCE
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_ADAPTER_VERSION = "v3"
_TENCENT_SHARES_V3 = "akshare:1.18.94:stock_zh_a_hist_tx:v3"
_MINUTE_INTERVALS = {"MINUTE_1": "1", "MINUTE_5": "5"}
_INDEX_PREFIXES = {"SH": "000", "SZ": "399"}
_VOLUME_MULTIPLIERS = {_LEGACY_SOURCE: 100, _DAILY_SOURCE: 1, _MINUTE_SOURCE: 1}
_CAPTURE_PROFILES = frozenset(
    {
        (_DAILY_SOURCE, "stock_zh_a_hist_tx", "DAILY", _TENCENT_SHARES_V3),
        (
            _MINUTE_SOURCE,
            "stock_zh_a_minute",
            "MINUTE_1",
            "akshare:1.18.94:stock_zh_a_minute:v3",
        ),
        (
            _MINUTE_SOURCE,
            "stock_zh_a_minute",
            "MINUTE_5",
            "akshare:1.18.94:stock_zh_a_minute:v3",
        ),
        (
            _DAILY_SOURCE,
            "stock_zh_a_hist_tx",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_hist_tx:v2",
        ),
        (
            _MINUTE_SOURCE,
            "stock_zh_a_minute",
            "MINUTE_1",
            "akshare:1.18.94:stock_zh_a_minute:v2",
        ),
        (
            _MINUTE_SOURCE,
            "stock_zh_a_minute",
            "MINUTE_5",
            "akshare:1.18.94:stock_zh_a_minute:v2",
        ),
        (
            _LEGACY_SOURCE,
            "stock_zh_a_hist",
            "DAILY",
            "akshare:1.18.94:stock_zh_a_hist:v1",
        ),
        (
            _LEGACY_SOURCE,
            "stock_zh_a_hist_min_em",
            "MINUTE_1",
            "akshare:1.18.94:stock_zh_a_hist_min_em:v1",
        ),
    }
)
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("日期", "交易日期", "date", "trade_date"),
    "time": ("时间", "日期时间", "day", "time", "datetime"),
    "code": ("股票代码", "证券代码", "代码", "symbol", "ts_code", "code"),
    "open": ("开盘", "open"),
    "close": ("收盘", "close"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "volume": ("成交量", "volume", "vol"),
    "amount": ("成交额", "amount"),
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AKShareConfig:
    """Non-secret AKShare adapter settings.

    The public AKShare functions do not provide a reliable per-request timeout
    boundary, so this configuration intentionally exposes bounded retry/backoff
    only and does not claim a hard request deadline.
    """

    sdk_version: str | None = None
    adapter_version: str = _ADAPTER_VERSION
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.sdk_version is not None and not self.sdk_version.strip():
            raise ValueError("sdk_version must be non-empty when provided")
        if not self.adapter_version.strip():
            raise ValueError("adapter_version must be non-empty")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if self.sdk_version is not None:
            object.__setattr__(self, "sdk_version", self.sdk_version.strip())
        object.__setattr__(self, "adapter_version", self.adapter_version.strip())


@dataclass(frozen=True, slots=True)
class AKShareBarCapture:
    """Immutable serialized SDK table and its non-secret request identity."""

    body: bytes
    api_name: str
    request: str
    unified_code: str
    interval: str
    start_date: str
    end_date: str
    received_at: datetime
    source: str = _SOURCE
    source_version: str = ""
    content_type: str = "application/json; charset=utf-8"

    def __post_init__(self) -> None:
        if type(self.body) is not bytes:
            raise TypeError("body must be bytes")
        for field_name in (
            "api_name",
            "request",
            "unified_code",
            "interval",
            "start_date",
            "end_date",
            "source",
            "content_type",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if not self.source_version.strip():
            fallback_version = "v1" if self.source == _LEGACY_SOURCE else _ADAPTER_VERSION
            object.__setattr__(
                self,
                "source_version",
                f"akshare:unknown:{self.api_name}:{fallback_version}",
            )

    @property
    def endpoint(self) -> str:
        """Alias for callers that refer to the public function as an endpoint."""

        return self.api_name


def validate_akshare_capture_profile(capture: object) -> AKShareBarCapture:
    """Return a capture only when its source route and semantic version are allowlisted."""

    if not isinstance(capture, AKShareBarCapture):
        raise ProviderDataError("AKShare capture type is invalid")
    if (
        capture.source == _LEGACY_SOURCE
        and capture.api_name == "index_zh_a_hist_min_em"
        and capture.interval == "MINUTE_5"
    ):
        raise ProviderDataError(
            "AKShare legacy index MINUTE_5 capture has unsupported/ambiguous price semantics"
        )
    profile = (capture.source, capture.api_name, capture.interval, capture.source_version)
    if profile not in _CAPTURE_PROFILES:
        raise ProviderDataError("unsupported AKShare capture profile")
    if capture.source == _LEGACY_SOURCE and _instrument_kind(capture.unified_code) != "stock":
        raise ProviderDataError("unsupported AKShare capture profile")
    return capture


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ProviderDataError(f"{field_name} must be an ISO date") from error


def _exchange(unified_code: str) -> ExchangeCode:
    parts = unified_code.rsplit(".", maxsplit=1)
    if len(parts) != 2 or parts[1] not in {"SH", "SZ", "BJ"}:
        raise ProviderDataError("unified_code is invalid")
    exchange = cast(ExchangeCode, parts[1])
    if not is_market_data_code_for_exchange(unified_code, exchange):
        raise ProviderDataError("unified_code is not a supported market identity")
    return exchange


def _is_index(unified_code: str) -> bool:
    code, exchange = unified_code.rsplit(".", maxsplit=1)
    prefix = _INDEX_PREFIXES.get(exchange)
    return prefix is not None and code.startswith(prefix)


InstrumentKind = Literal["stock", "index", "etf"]


def _instrument_kind(unified_code: str) -> InstrumentKind:
    exchange = _exchange(unified_code)
    code = unified_code[:6]
    if _is_index(unified_code):
        return "index"
    parsed = parse_instrument_code(code)
    if parsed is None or parsed.exchange != exchange:
        raise ProviderDataError("unified_code is not recognized by the instrument rules")
    if parsed.type == "ETF":
        return "etf"
    if parsed.type == "STOCK":
        return "stock"
    raise ProviderDataError("AKShare market bars support stocks, indices, and ETFs only")


def _route(unified_code: str, interval: str) -> tuple[str, dict[str, object], str]:
    _instrument_kind(unified_code)
    code, exchange = unified_code.rsplit(".", maxsplit=1)
    symbol = f"{exchange.lower()}{code}"
    if interval == "DAILY":
        return "stock_zh_a_hist_tx", {"symbol": symbol, "adjust": ""}, _DAILY_SOURCE

    period = _MINUTE_INTERVALS.get(interval)
    if period is None:
        raise ProviderDataError("interval is not supported")
    return (
        "stock_zh_a_minute",
        {
            "symbol": symbol,
            "period": period,
            "adjust": "",
        },
        _MINUTE_SOURCE,
    )


def _decimal(value: object, *, field_name: str, row_index: int) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ProviderDataError(f"row {row_index} has invalid {field_name}")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ProviderDataError(f"row {row_index} has invalid {field_name}") from error
    if not parsed.is_finite() or parsed < 0:
        raise ProviderDataError(f"row {row_index} has invalid {field_name}")
    return parsed


def _volume(value: object, row_index: int, *, multiplier: int) -> int:
    scaled = _decimal(value, field_name="volume", row_index=row_index) * multiplier
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ProviderDataError(f"row {row_index} has non-integral volume")
    return int(integral)


def _field(
    record: Mapping[str, object], name: str, row_index: int, *, required: bool = True
) -> object:
    for alias in _FIELD_ALIASES[name]:
        if alias in record:
            return record[alias]
    if required:
        raise ProviderDataError(f"row {row_index} missing required column {name}")
    return None


def _daily_timestamp(value: object, row_index: int) -> datetime:
    if isinstance(value, datetime):
        trading_date = value.astimezone(_SHANGHAI).date() if value.tzinfo else value.date()
    elif isinstance(value, date):
        trading_date = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise ProviderDataError(f"row {row_index} has invalid date") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            trading_date = parsed.date()
        else:
            trading_date = parsed.astimezone(_SHANGHAI).date()
    else:
        raise ProviderDataError(f"row {row_index} has invalid date")
    return datetime.combine(trading_date, time(15, 0), _SHANGHAI).astimezone(UTC)


def _minute_timestamp(value: object, row_index: int) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as error:
            raise ProviderDataError(f"row {row_index} has invalid time") from error
    else:
        raise ProviderDataError(f"row {row_index} has invalid time")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI)
    return parsed.astimezone(UTC)


def _serialize_dataframe(frame: object) -> bytes:
    to_json = getattr(frame, "to_json", None)
    if not callable(to_json):
        raise ProviderDataError("AKShare endpoint did not return a DataFrame")

    # This is deliberately the first DataFrame operation: preserve the raw
    # adapter payload before any field selection, Decimal conversion or checks.
    try:
        serialized = to_json(orient="records", date_format="iso", force_ascii=False)
    except Exception as error:
        raise ProviderDataError("AKShare DataFrame serialization failed") from error
    if isinstance(serialized, str):
        body = serialized.encode("utf-8")
    elif isinstance(serialized, bytes):
        body = serialized
    else:
        raise ProviderDataError("AKShare DataFrame serialization returned invalid bytes")

    return body


def _decode_capture_body(body: bytes) -> list[Mapping[str, object]]:
    try:
        decoded = json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderDataError("AKShare capture body is not valid JSON") from error
    if not isinstance(decoded, list):
        raise ProviderDataError("AKShare capture body must contain a JSON array")
    rows: list[Mapping[str, object]] = []
    for row_index, raw_record in enumerate(cast(list[object], decoded)):
        if not isinstance(raw_record, Mapping):
            raise ProviderDataError(f"row {row_index} is not a mapping")
        rows.append(dict(cast(Mapping[str, object], raw_record)))
    return rows


def _version(sdk_version: str | None, endpoint: str, adapter_version: str) -> str:
    resolved = sdk_version
    if resolved is None:
        try:
            resolved = importlib.metadata.version("akshare")
        except importlib.metadata.PackageNotFoundError:
            resolved = "unknown"
    return f"akshare:{resolved}:{endpoint}:{adapter_version}"


class AKShareMarketDataProvider(MarketDataProvider):
    """Concrete daily/minute Bar provider backed by public AKShare functions."""

    def __init__(
        self,
        config: AKShareConfig | None = None,
        *,
        client: object | None = None,
        client_factory: ClientFactory | None = None,
        clock: Clock = _utc_now,
        sleeper: Sleeper = time_module.sleep,
    ) -> None:
        if client is not None and client_factory is not None:
            raise ValueError("provide client or client_factory, not both")
        self._config = config or AKShareConfig()
        self._client = client
        self._client_factory = client_factory
        self._clock = clock
        self._sleeper = sleeper

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_DAILY_BARS, Capability.FETCH_MINUTE_BARS})

    def _client_instance(self) -> object:
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            return self._client_factory()
        try:
            return importlib.import_module("akshare")
        except Exception as error:
            raise ProviderUnavailableError("AKShare SDK is unavailable") from error

    def _fetch_frame(self, endpoint: str, params: Mapping[str, object]) -> object:
        transient_errors = (ProviderRateLimitError, ProviderTimeoutError, ProviderUnavailableError)
        for attempt in range(self._config.max_attempts):
            try:
                client = self._client_instance()
                function = getattr(client, endpoint, None)
                if not callable(function):
                    raise ProviderDataError(f"AKShare endpoint {endpoint} is unavailable")
                return function(**dict(params))
            except ProviderError as error:
                if not isinstance(error, transient_errors) or (
                    attempt + 1 >= self._config.max_attempts
                ):
                    raise
                self._sleeper(self._config.retry_backoff_seconds * (2**attempt))
            except (ValueError, TypeError, KeyError, IndexError) as error:
                raise ProviderDataError(
                    "AKShare rejected the request or returned invalid data"
                ) from error
            except (TimeoutError, OSError) as error:
                if attempt + 1 >= self._config.max_attempts:
                    raise ProviderUnavailableError("AKShare provider unavailable") from error
                self._sleeper(self._config.retry_backoff_seconds * (2**attempt))
            except Exception as error:
                if attempt + 1 >= self._config.max_attempts:
                    raise ProviderUnavailableError("AKShare provider unavailable") from error
                self._sleeper(self._config.retry_backoff_seconds * (2**attempt))
        raise ProviderUnavailableError("AKShare provider unavailable")

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: Cursor | None = None,
    ) -> AKShareBarCapture:
        if cursor is not None:
            raise ProviderDataError("AKShare bar endpoints do not use cursors")
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
        if end < start:
            raise ProviderDataError("end_date must not precede start_date")
        endpoint, params, source = _route(unified_code, interval)
        if interval == "DAILY":
            params.update(
                {"start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")}
            )
        frame = self._fetch_frame(endpoint, params)
        body = _serialize_dataframe(frame)
        received_at = self._clock()
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ProviderDataError("provider clock must be timezone-aware")
        received_at = received_at.astimezone(UTC)
        request = (
            f"GET /akshare/{endpoint}?code={unified_code[:6]}"
            f"&date={start.isoformat()}:{end.isoformat()}"
        )
        return AKShareBarCapture(
            body=body,
            api_name=endpoint,
            request=request,
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=received_at,
            source=source,
            source_version=_version(
                self._config.sdk_version,
                endpoint,
                self._config.adapter_version,
            ),
        )

    def parse_bars_with_evidence(self, capture: object) -> ProviderParseResult:
        capture = validate_akshare_capture_profile(capture)
        daily = capture.interval == "DAILY"
        if not daily and capture.interval not in _MINUTE_INTERVALS:
            raise ProviderDataError("interval is not supported")
        exchange = _exchange(capture.unified_code)
        expected_code = capture.unified_code[:6]
        requested_start = _parse_date(capture.start_date, "start_date")
        requested_end = _parse_date(capture.end_date, "end_date")
        multiplier = _VOLUME_MULTIPLIERS.get(capture.source)
        if multiplier is None:
            raise ProviderDataError("AKShare source is unsupported")
        # AKShare 1.18.94 exempts sz000 stocks along with indices from its
        # Tencent hands-to-shares conversion. Correct only this pinned v3
        # profile; preserve SDK payload bytes and historical v2 replay values.
        if (
            capture.source_version == _TENCENT_SHARES_V3
            and exchange == "SZ"
            and expected_code.startswith("000")
        ):
            multiplier = 100
        records = _decode_capture_body(capture.body)
        bars: list[Bar] = []
        exclusions: list[BarExclusion] = []
        for row_index, record in enumerate(records):
            raw_code = _field(record, "code", row_index, required=False)
            if raw_code is not None:
                if isinstance(raw_code, bool):
                    raise ProviderDataError(f"row {row_index} has invalid security code")
                row_code = str(raw_code).strip()
                if row_code and row_code not in {expected_code, capture.unified_code}:
                    raise ProviderDataError(f"row {row_index} has unexpected security code")
            raw_timestamp = _field(record, "date" if daily else "time", row_index)
            timestamp = (
                _daily_timestamp(raw_timestamp, row_index)
                if daily
                else _minute_timestamp(raw_timestamp, row_index)
            )
            trading_date = timestamp.astimezone(_SHANGHAI).date()
            if not requested_start <= trading_date <= requested_end:
                if capture.source == _MINUTE_SOURCE:
                    exclusions.append(
                        BarExclusion(
                            raw_row_index=row_index,
                            timestamp=timestamp,
                            requested_start=requested_start,
                            requested_end=requested_end,
                            reason_code=SINA_OVERFETCH_OUTSIDE_REQUEST,
                        )
                    )
                    continue
                raise ProviderDataError(f"row {row_index} is outside requested date range")
            try:
                bar = Bar.model_validate(
                    {
                        "unifiedCode": capture.unified_code,
                        "exchange": exchange,
                        "date": trading_date,
                        "interval": capture.interval,
                        "session": "CONTINUOUS",
                        "timestamp": timestamp,
                        "open": _decimal(
                            _field(record, "open", row_index),
                            field_name="open",
                            row_index=row_index,
                        ),
                        "high": _decimal(
                            _field(record, "high", row_index),
                            field_name="high",
                            row_index=row_index,
                        ),
                        "low": _decimal(
                            _field(record, "low", row_index),
                            field_name="low",
                            row_index=row_index,
                        ),
                        "close": _decimal(
                            _field(record, "close", row_index),
                            field_name="close",
                            row_index=row_index,
                        ),
                        "volume": _volume(
                            _field(record, "volume", row_index),
                            row_index,
                            multiplier=multiplier,
                        ),
                        "amount": _decimal(
                            _field(record, "amount", row_index),
                            field_name="amount",
                            row_index=row_index,
                        ),
                        "priceType": "RAW",
                    }
                )
            except ProviderDataError:
                raise
            except (TypeError, ValueError) as error:
                raise ProviderDataError(f"row {row_index} failed Bar validation") from error
            bars.append(bar)
        return ProviderParseResult(bars=bars, exclusions=exclusions)

    def parse_bars(self, capture: object) -> list[Bar]:
        return self.parse_bars_with_evidence(capture).bars

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
        raise NotImplementedError("AKShareMarketDataProvider does not expose executed ticks")


__all__ = [
    "AKShareBarCapture",
    "AKShareConfig",
    "AKShareMarketDataProvider",
    "ClientFactory",
    "validate_akshare_capture_profile",
]
