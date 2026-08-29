"""One-shot or continuous runtime for raw-first real market-data synchronization."""

from __future__ import annotations

import json
import os
import time as time_module
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from data_worker.jobs.market_data.checkpoint import (
    InFlightRequest,
    MarketDataCheckpoint,
    MarketDataCheckpointError,
    MarketDataCheckpointStore,
)
from data_worker.jobs.market_data.collector import (
    MarketDataCollectionResult,
    MarketDataCollector,
    RawBarProvider,
)
from data_worker.jobs.market_data.quality import MarketDataQualitySink
from data_worker.providers.akshare import AKShareMarketDataProvider, ClientFactory
from data_worker.raw import LocalFileStorage
from market_core.instrument.code_parser import (
    ExchangeCode,
    is_market_data_code_for_exchange,
)
from market_core.providers import ProviderError
from market_core.providers.tushare import TushareConfig, TushareMarketDataProvider
from market_core.storage import ClickHouseBarConfig, ClickHouseBarWriter

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
ProviderFactory = Callable[["MarketDataSyncSettings", Clock], RawBarProvider]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DEFAULT_AKSHARE_SYMBOLS = "600519.SH"
_DEFAULT_TUSHARE_SYMBOLS = "600519.SH"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Collector(Protocol):
    """Runtime-facing collector boundary."""

    def collect(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        *,
        run_id: str,
        capture_ordinal: int,
        processing_time: datetime | None = None,
    ) -> MarketDataCollectionResult: ...


@dataclass(frozen=True, slots=True)
class MarketDataSyncSettings:
    """Validated environment settings; credentials are excluded from repr."""

    token: str | None = field(repr=False)
    tushare_endpoint: str
    symbols: tuple[str, ...]
    raw_root: Path
    clickhouse_url: str
    clickhouse_database: str
    clickhouse_user: str
    clickhouse_password: str | None = field(default=None, repr=False)
    clickhouse_timeout_seconds: float = 5.0
    poll_seconds: int = 60
    daily_lookback_days: int = 730
    minute_interval: str = "MINUTE_1"
    continuous: bool = False
    provider: str = "akshare"
    minute_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.continuous and self.poll_seconds < 60:
            raise ValueError("continuous market-data mode requires poll_seconds at least 60")


@dataclass(frozen=True, slots=True)
class MarketDataSyncSummary:
    """Non-secret observable result for one synchronization cycle."""

    trading_date: str
    requests: int
    received_bars: int
    written_bars: int
    daily_refreshed: bool
    raw_capture_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "tradingDate": self.trading_date,
            "requests": self.requests,
            "receivedBars": self.received_bars,
            "writtenBars": self.written_bars,
            "dailyRefreshed": self.daily_refreshed,
            "rawCaptureIds": list(self.raw_capture_ids),
        }


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name, str(default))
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be numeric") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


def _symbols(raw: str) -> tuple[str, ...]:
    symbols = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    if not symbols:
        raise RuntimeError("MARKET_DATA_SYMBOLS must contain at least one code")
    for symbol in symbols:
        parts = symbol.rsplit(".", maxsplit=1)
        if len(parts) != 2 or parts[1] not in {"SH", "SZ", "BJ"}:
            raise RuntimeError(f"unsupported market-data symbol: {symbol}")
        exchange = cast(ExchangeCode, parts[1])
        if not is_market_data_code_for_exchange(symbol, exchange):
            raise RuntimeError(f"unsupported market-data symbol: {symbol}")
    return symbols


def _optional_symbols(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return ()
    return _symbols(raw)


def load_market_data_settings(environ: Mapping[str, str]) -> MarketDataSyncSettings:
    """Parse the explicit process environment without loading credential files."""

    provider = environ.get("MARKET_DATA_PROVIDER", "akshare").strip()
    if provider not in {"akshare", "tushare"}:
        raise RuntimeError("MARKET_DATA_PROVIDER must be akshare or tushare")
    mode = environ.get("MARKET_DATA_RUN_MODE", "once").strip().lower()
    if mode not in {"once", "continuous"}:
        raise RuntimeError("MARKET_DATA_RUN_MODE must be once or continuous")
    minute_interval = environ.get("MARKET_DATA_MINUTE_INTERVAL", "MINUTE_1").strip()
    if minute_interval not in {"MINUTE_1", "MINUTE_5"}:
        raise RuntimeError("MARKET_DATA_MINUTE_INTERVAL must be MINUTE_1 or MINUTE_5")
    raw_token = environ.get("TUSHARE_TOKEN")
    token = raw_token.strip() if raw_token is not None and raw_token.strip() else None
    if provider == "tushare" and token is None:
        raise RuntimeError("TUSHARE_TOKEN is required when MARKET_DATA_PROVIDER=tushare")
    password = environ.get("CLICKHOUSE_PASSWORD")
    default_symbols = (
        _DEFAULT_AKSHARE_SYMBOLS if provider == "akshare" else _DEFAULT_TUSHARE_SYMBOLS
    )
    poll_seconds = _positive_int(environ, "MARKET_DATA_POLL_SECONDS", 60)
    if mode == "continuous" and poll_seconds < 60:
        raise RuntimeError("continuous market-data mode requires poll_seconds at least 60")
    return MarketDataSyncSettings(
        token=token,
        tushare_endpoint=environ.get("TUSHARE_API_URL", "https://api.tushare.pro").strip(),
        symbols=_symbols(environ.get("MARKET_DATA_SYMBOLS", default_symbols)),
        raw_root=Path(environ.get("MARKET_DATA_RAW_ROOT", "var/market-raw")),
        clickhouse_url=environ.get("CLICKHOUSE_URL", "http://localhost:8123").strip(),
        clickhouse_database=environ.get("CLICKHOUSE_DATABASE", "kunlun").strip(),
        clickhouse_user=environ.get("CLICKHOUSE_USER", "kunlun").strip(),
        clickhouse_password=password if password and password.strip() else None,
        clickhouse_timeout_seconds=_positive_float(environ, "CLICKHOUSE_TIMEOUT_SECONDS", 5.0),
        poll_seconds=poll_seconds,
        daily_lookback_days=_positive_int(environ, "MARKET_DATA_DAILY_LOOKBACK_DAYS", 730),
        minute_interval=minute_interval,
        continuous=mode == "continuous",
        provider=provider,
        minute_symbols=_optional_symbols(environ.get("MARKET_DATA_MINUTE_SYMBOLS")),
    )


class MarketDataRunner:
    """Refresh daily context once per date and intraday Bars every cycle."""

    def __init__(
        self,
        collector: Collector,
        *,
        symbols: tuple[str, ...],
        minute_symbols: tuple[str, ...] = (),
        daily_lookback_days: int,
        minute_interval: str = "MINUTE_1",
        run_id: str | None = None,
        checkpoint_root: Path | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        if not symbols:
            raise ValueError("symbols must not be empty")
        if daily_lookback_days <= 0:
            raise ValueError("daily_lookback_days must be positive")
        if minute_interval not in {"MINUTE_1", "MINUTE_5"}:
            raise ValueError("minute_interval is unsupported")
        self._collector = collector
        self._symbols = symbols
        self._minute_symbols = minute_symbols
        self._daily_lookback_days = daily_lookback_days
        self._minute_interval = minute_interval
        self._requested_run_id = run_id
        self._run_id = run_id or (None if checkpoint_root is not None else f"market-{uuid4().hex}")
        self._clock = clock
        self._capture_ordinal = 0
        self._daily_refreshed_for: date | None = None
        self._checkpoint_store = (
            None if checkpoint_root is None else MarketDataCheckpointStore(checkpoint_root)
        )

    def _processing_time(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("market-data clock must be timezone-aware")
        return value.astimezone(UTC)

    def _collect(
        self,
        symbol: str,
        interval: str,
        start_date: date,
        end_date: date,
    ) -> MarketDataCollectionResult:
        self._capture_ordinal += 1
        if self._run_id is None:
            raise RuntimeError("market-data run identity is not initialized")
        return self._collector.collect(
            symbol,
            interval,
            start_date.isoformat(),
            end_date.isoformat(),
            run_id=self._run_id,
            capture_ordinal=self._capture_ordinal,
            processing_time=self._processing_time(),
        )

    def _request(
        self,
        *,
        kind: str,
        trading_date: date,
        symbol: str,
        interval: str,
        start_date: date,
        end_date: date,
        checkpoint: MarketDataCheckpoint,
    ) -> InFlightRequest:
        if self._run_id is None:
            raise RuntimeError("market-data run identity is not initialized")
        return InFlightRequest(
            kind=kind,
            trading_date=trading_date.isoformat(),
            unified_code=symbol,
            interval=interval,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            capture_ordinal=checkpoint.next_capture_ordinal,
            processing_time=self._processing_time(),
        )

    def _execute_checkpointed_request(
        self,
        checkpoint: MarketDataCheckpoint,
        request: InFlightRequest,
    ) -> tuple[MarketDataCheckpoint, MarketDataCollectionResult]:
        if checkpoint.in_flight is None:
            checkpoint = replace(checkpoint, in_flight=request)
            self._checkpoint_store_save(checkpoint)
        elif checkpoint.in_flight != request:
            raise MarketDataCheckpointError("checkpoint in-flight request does not match")
        self._run_id = checkpoint.run_id
        result = self._collector.collect(
            request.unified_code,
            request.interval,
            request.start_date,
            request.end_date,
            run_id=checkpoint.run_id,
            capture_ordinal=request.capture_ordinal,
            processing_time=request.processing_time,
        )
        completed_symbols = checkpoint.daily_completed_symbols
        if request.kind == "DAILY":
            if checkpoint.daily_trading_date != request.trading_date:
                completed_symbols = ()
            completed_symbols = tuple(dict.fromkeys((*completed_symbols, request.unified_code)))
        next_checkpoint = replace(
            checkpoint,
            next_capture_ordinal=request.capture_ordinal + 1,
            daily_completed_symbols=completed_symbols,
            in_flight=None,
        )
        self._checkpoint_store_save(next_checkpoint)
        self._capture_ordinal = request.capture_ordinal
        return next_checkpoint, result

    def _checkpoint_store_save(self, checkpoint: MarketDataCheckpoint) -> None:
        if self._checkpoint_store is None:
            raise RuntimeError("market-data checkpoint store is not initialized")
        self._checkpoint_store.save(checkpoint)

    def _run_cycle_without_checkpoint(self) -> MarketDataSyncSummary:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("market-data clock must be timezone-aware")
        trading_date = now.astimezone(_SHANGHAI).date()
        results: list[MarketDataCollectionResult] = []
        refresh_daily = self._daily_refreshed_for != trading_date
        if refresh_daily:
            daily_end = trading_date - timedelta(days=1)
            daily_start = daily_end - timedelta(days=self._daily_lookback_days - 1)
            for symbol in self._symbols:
                results.append(self._collect(symbol, "DAILY", daily_start, daily_end))
            self._daily_refreshed_for = trading_date
        for symbol in self._minute_symbols:
            results.append(self._collect(symbol, self._minute_interval, trading_date, trading_date))
        return MarketDataSyncSummary(
            trading_date=trading_date.isoformat(),
            requests=len(results),
            received_bars=sum(result.received_bars for result in results),
            written_bars=sum(result.written_bars for result in results),
            daily_refreshed=refresh_daily,
            raw_capture_ids=tuple(result.raw_capture_id for result in results),
        )

    def _run_cycle_with_checkpoint(self, checkpoint: MarketDataCheckpoint) -> MarketDataSyncSummary:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("market-data clock must be timezone-aware")
        trading_date = now.astimezone(_SHANGHAI).date()
        results: list[MarketDataCollectionResult] = []
        resumed_minute: InFlightRequest | None = None
        resumed_daily = False

        if checkpoint.in_flight is not None:
            resumed = checkpoint.in_flight
            allowed_symbols = self._symbols if resumed.kind == "DAILY" else self._minute_symbols
            if resumed.unified_code not in allowed_symbols:
                raise MarketDataCheckpointError(
                    "checkpoint in-flight symbol does not match configuration"
                )
            checkpoint, result = self._execute_checkpointed_request(checkpoint, resumed)
            results.append(result)
            if resumed.kind == "MINUTE":
                resumed_minute = resumed
            elif resumed.kind == "DAILY" and resumed.trading_date == trading_date.isoformat():
                resumed_daily = True

        configured_symbols = set(self._symbols)
        if not set(checkpoint.daily_completed_symbols).issubset(configured_symbols):
            raise MarketDataCheckpointError("checkpoint daily symbols do not match configuration")
        if checkpoint.daily_trading_date != trading_date.isoformat():
            checkpoint = replace(
                checkpoint,
                daily_trading_date=trading_date.isoformat(),
                daily_completed_symbols=(),
            )
            self._checkpoint_store_save(checkpoint)

        daily_end = trading_date - timedelta(days=1)
        daily_start = daily_end - timedelta(days=self._daily_lookback_days - 1)
        daily_refreshed = resumed_daily
        for symbol in self._symbols:
            if symbol in checkpoint.daily_completed_symbols:
                continue
            request = self._request(
                kind="DAILY",
                trading_date=trading_date,
                symbol=symbol,
                interval="DAILY",
                start_date=daily_start,
                end_date=daily_end,
                checkpoint=checkpoint,
            )
            checkpoint, result = self._execute_checkpointed_request(checkpoint, request)
            results.append(result)
            daily_refreshed = True

        for symbol in self._minute_symbols:
            if (
                resumed_minute is not None
                and resumed_minute.trading_date == trading_date.isoformat()
                and resumed_minute.unified_code == symbol
            ):
                continue
            request = self._request(
                kind="MINUTE",
                trading_date=trading_date,
                symbol=symbol,
                interval=self._minute_interval,
                start_date=trading_date,
                end_date=trading_date,
                checkpoint=checkpoint,
            )
            checkpoint, result = self._execute_checkpointed_request(checkpoint, request)
            results.append(result)

        self._run_id = checkpoint.run_id
        self._capture_ordinal = checkpoint.next_capture_ordinal - 1
        return MarketDataSyncSummary(
            trading_date=trading_date.isoformat(),
            requests=len(results),
            received_bars=sum(result.received_bars for result in results),
            written_bars=sum(result.written_bars for result in results),
            daily_refreshed=daily_refreshed,
            raw_capture_ids=tuple(result.raw_capture_id for result in results),
        )

    def run_cycle(self) -> MarketDataSyncSummary:
        if self._checkpoint_store is None:
            return self._run_cycle_without_checkpoint()
        with self._checkpoint_store.locked():
            checkpoint = self._checkpoint_store.load_or_create(self._requested_run_id)
            self._run_id = checkpoint.run_id
            return self._run_cycle_with_checkpoint(checkpoint)


def build_market_data_provider(
    settings: MarketDataSyncSettings,
    *,
    clock: Clock = _utc_now,
    provider_factory: ProviderFactory | None = None,
    akshare_client_factory: ClientFactory | None = None,
) -> RawBarProvider:
    """Build the selected provider without initializing external network I/O."""

    if provider_factory is not None:
        provider = provider_factory(settings, clock)
    elif settings.provider == "akshare":
        provider = AKShareMarketDataProvider(client_factory=akshare_client_factory, clock=clock)
    elif settings.provider == "tushare":
        if settings.token is None:
            raise RuntimeError("TUSHARE_TOKEN is required when MARKET_DATA_PROVIDER=tushare")
        provider = TushareMarketDataProvider(
            TushareConfig(token=settings.token, endpoint=settings.tushare_endpoint),
            clock=clock,
        )
    else:
        raise RuntimeError("MARKET_DATA_PROVIDER must be akshare or tushare")

    return provider


def build_market_data_runner(
    settings: MarketDataSyncSettings,
    *,
    clock: Clock = _utc_now,
    provider_factory: ProviderFactory | None = None,
    akshare_client_factory: ClientFactory | None = None,
) -> MarketDataRunner:
    """Compose the selected provider, immutable raw storage, and ClickHouse writer."""

    provider = build_market_data_provider(
        settings,
        clock=clock,
        provider_factory=provider_factory,
        akshare_client_factory=akshare_client_factory,
    )
    writer = ClickHouseBarWriter(
        ClickHouseBarConfig(
            url=settings.clickhouse_url,
            database=settings.clickhouse_database,
            user=settings.clickhouse_user,
            password=settings.clickhouse_password,
            timeout_seconds=settings.clickhouse_timeout_seconds,
        )
    )
    raw_storage = LocalFileStorage(settings.raw_root)
    quality_sink = MarketDataQualitySink(settings.raw_root / "market-quality", clock=clock)
    collector = MarketDataCollector(
        provider,
        raw_storage,
        writer,
        quality_sink=quality_sink,
    )
    return MarketDataRunner(
        collector,
        symbols=settings.symbols,
        minute_symbols=settings.minute_symbols,
        daily_lookback_days=settings.daily_lookback_days,
        minute_interval=settings.minute_interval,
        checkpoint_root=settings.raw_root,
        clock=clock,
    )


def run_market_data_sync(
    settings: MarketDataSyncSettings,
    *,
    clock: Clock = _utc_now,
    sleeper: Sleeper = time_module.sleep,
) -> None:
    """Run once by default, or continuously when explicitly configured."""

    runner = build_market_data_runner(settings, clock=clock)
    while True:
        summary = runner.run_cycle()
        print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True), flush=True)
        if not settings.continuous:
            return
        sleeper(float(settings.poll_seconds))


def main() -> None:
    try:
        run_market_data_sync(load_market_data_settings(os.environ))
    except (ProviderError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()


__all__ = [
    "MarketDataRunner",
    "MarketDataSyncSettings",
    "MarketDataSyncSummary",
    "build_market_data_provider",
    "build_market_data_runner",
    "load_market_data_settings",
    "run_market_data_sync",
]
