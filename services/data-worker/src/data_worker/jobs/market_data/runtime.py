"""One-shot or continuous runtime for raw-first real market-data synchronization."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import time as time_module
from collections.abc import Callable, Mapping
from contextlib import suppress
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
from data_worker.jobs.market_data.quality_export import MarketQualityPublicPublisher
from data_worker.jobs.market_data.remote_settings import (
    RemoteMarketDataSettingsError,
    RemoteSettingsTransport,
    fetch_remote_market_data_settings,
    load_remote_market_data_settings,
    remote_market_data_settings_source,
    validate_remote_settings_worker_token,
)
from data_worker.jobs.market_data.status import (
    MarketDataSyncStatusError,
    MarketDataSyncStatusPublisher,
    WorkerStatusErrorCode,
)
from data_worker.providers.akshare import AKShareMarketDataProvider, ClientFactory
from data_worker.raw import LocalFileStorage
from market_core.instrument.code_parser import (
    ExchangeCode,
    is_market_data_code_for_exchange,
)
from market_core.providers import ProviderDataError, ProviderError
from market_core.providers.tushare import TushareConfig, TushareMarketDataProvider
from market_core.storage import ClickHouseBarConfig, ClickHouseBarWriter

Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
ProviderFactory = Callable[["MarketDataSyncSettings", Clock], RawBarProvider]
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_DEFAULT_AKSHARE_SYMBOLS = "600519.SH"
_DEFAULT_TUSHARE_SYMBOLS = "600519.SH"
_MANAGED_TUSHARE_ENDPOINT = "https://api.tushare.pro"
_MANAGED_CHECKPOINT_DIRECTORY = "managed-checkpoints"
_MANAGED_STATE_FILENAME = ".managed-settings-state-v1.json"
_MANAGED_STATE_VERSION = "market-data-managed-settings-v1"


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


class QualityCyclePublisher(Protocol):
    """Optional cycle-end hook for explicitly enabled public evidence."""

    def publish_cycle(self) -> object: ...


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
    managed_settings_url: str | None = field(default=None, repr=False)
    managed_settings_worker_token: str | None = field(default=None, repr=False)
    managed_settings_allow_local_http: bool = False
    managed_revision: int | None = None
    quality_public_root: Path | None = None
    status_public_root: Path | None = None

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


def load_market_data_settings(
    environ: Mapping[str, str],
    *,
    remote_transport: RemoteSettingsTransport | None = None,
) -> MarketDataSyncSettings:
    """Parse the explicit process environment without loading credential files."""

    remote_source = remote_market_data_settings_source(environ)
    provider = environ.get("MARKET_DATA_PROVIDER", "akshare").strip()
    if remote_source is None and provider not in {"akshare", "tushare"}:
        raise RuntimeError("MARKET_DATA_PROVIDER must be akshare or tushare")
    managed = (
        None
        if remote_source is None
        else load_remote_market_data_settings(environ, transport=remote_transport)
    )
    if managed is not None:
        provider = managed.provider
        token = managed.token
        tushare_endpoint = _MANAGED_TUSHARE_ENDPOINT
    else:
        raw_token = environ.get("TUSHARE_TOKEN")
        token = raw_token.strip() if raw_token is not None and raw_token.strip() else None
        if provider == "tushare" and token is None:
            raise RuntimeError("TUSHARE_TOKEN is required when MARKET_DATA_PROVIDER=tushare")
        tushare_endpoint = environ.get("TUSHARE_API_URL", _MANAGED_TUSHARE_ENDPOINT).strip()
    mode = environ.get("MARKET_DATA_RUN_MODE", "once").strip().lower()
    if mode not in {"once", "continuous"}:
        raise RuntimeError("MARKET_DATA_RUN_MODE must be once or continuous")
    minute_interval = environ.get("MARKET_DATA_MINUTE_INTERVAL", "MINUTE_1").strip()
    if minute_interval not in {"MINUTE_1", "MINUTE_5"}:
        raise RuntimeError("MARKET_DATA_MINUTE_INTERVAL must be MINUTE_1 or MINUTE_5")
    password = environ.get("CLICKHOUSE_PASSWORD")
    default_symbols = (
        _DEFAULT_AKSHARE_SYMBOLS if provider == "akshare" else _DEFAULT_TUSHARE_SYMBOLS
    )
    poll_seconds = _positive_int(environ, "MARKET_DATA_POLL_SECONDS", 60)
    if mode == "continuous" and poll_seconds < 60:
        raise RuntimeError("continuous market-data mode requires poll_seconds at least 60")
    quality_public_root_value = environ.get("MARKET_DATA_QUALITY_PUBLIC_ROOT")
    quality_public_root = (
        None
        if quality_public_root_value is None or not quality_public_root_value.strip()
        else Path(quality_public_root_value.strip())
    )
    status_public_root_value = environ.get("MARKET_DATA_STATUS_PUBLIC_ROOT")
    status_public_root = (
        None
        if status_public_root_value is None or not status_public_root_value.strip()
        else Path(status_public_root_value.strip())
    )
    return MarketDataSyncSettings(
        token=token,
        tushare_endpoint=tushare_endpoint,
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
        managed_settings_url=None if remote_source is None else remote_source.url,
        managed_settings_worker_token=(
            None if remote_source is None else remote_source.worker_token
        ),
        managed_settings_allow_local_http=(
            False if remote_source is None else remote_source.allow_local_http
        ),
        managed_revision=None if managed is None else managed.revision,
        quality_public_root=quality_public_root,
        status_public_root=status_public_root,
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
        quality_publisher: QualityCyclePublisher | None = None,
        provider: str = "akshare",
        status_public_root: Path | None = None,
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
        self._quality_publisher = quality_publisher
        status_symbols = tuple(dict.fromkeys((*symbols, *minute_symbols)))
        self._status_publisher = (
            None
            if status_public_root is None
            else MarketDataSyncStatusPublisher(
                status_public_root,
                provider=provider,
                symbols=status_symbols,
                clock=clock,
            )
        )
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
        summary = MarketDataSyncSummary(
            trading_date=trading_date.isoformat(),
            requests=len(results),
            received_bars=sum(result.received_bars for result in results),
            written_bars=sum(result.written_bars for result in results),
            daily_refreshed=refresh_daily,
            raw_capture_ids=tuple(result.raw_capture_id for result in results),
        )
        if self._quality_publisher is not None:
            self._quality_publisher.publish_cycle()
        return summary

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
        summary = MarketDataSyncSummary(
            trading_date=trading_date.isoformat(),
            requests=len(results),
            received_bars=sum(result.received_bars for result in results),
            written_bars=sum(result.written_bars for result in results),
            daily_refreshed=daily_refreshed,
            raw_capture_ids=tuple(result.raw_capture_id for result in results),
        )
        if self._quality_publisher is not None:
            self._quality_publisher.publish_cycle()
        return summary

    @staticmethod
    def _status_error_code(error: Exception) -> WorkerStatusErrorCode:
        if isinstance(error, ProviderDataError):
            return "VALIDATION_ERROR"
        if isinstance(error, ProviderError):
            return "SOURCE_ERROR"
        if isinstance(error, (TypeError, ValueError)):
            return "VALIDATION_ERROR"
        return "SYNC_ERROR"

    def _run_with_status(
        self, operation: Callable[[], MarketDataSyncSummary]
    ) -> MarketDataSyncSummary:
        publisher = self._status_publisher
        if publisher is None:
            return operation()

        publisher.publish_running()
        try:
            summary = operation()
        except Exception as error:
            try:
                publisher.publish_failed(self._status_error_code(error))
            except MarketDataSyncStatusError as status_error:
                raise error from status_error
            raise

        publisher.publish_succeeded(
            requests=summary.requests,
            received_bars=summary.received_bars,
            written_bars=summary.written_bars,
            daily_refreshed=summary.daily_refreshed,
        )
        return summary

    def run_cycle(self) -> MarketDataSyncSummary:
        checkpoint_store = self._checkpoint_store
        if checkpoint_store is None:
            return self._run_with_status(self._run_cycle_without_checkpoint)
        with checkpoint_store.locked():

            def run_locked() -> MarketDataSyncSummary:
                checkpoint = checkpoint_store.load_or_create(self._requested_run_id)
                self._run_id = checkpoint.run_id
                return self._run_cycle_with_checkpoint(checkpoint)

            return self._run_with_status(run_locked)


def _managed_settings_digest(settings: MarketDataSyncSettings) -> str:
    worker_token = settings.managed_settings_worker_token
    if worker_token is None:
        raise RuntimeError("managed market-data worker credential is invalid")
    validate_remote_settings_worker_token(worker_token)
    token = settings.token or ""
    material = f"{settings.provider}\x00{token}".encode()
    return hmac.new(worker_token.encode(), material, hashlib.sha256).hexdigest()


def _managed_checkpoint_root(settings: MarketDataSyncSettings) -> Path:
    revision = settings.managed_revision
    if settings.managed_settings_url is None:
        if revision is not None:
            raise RuntimeError("managed market-data settings source is incomplete")
        return settings.raw_root
    if type(revision) is not int or revision < 0:
        raise RuntimeError("managed market-data settings revision is invalid")
    if settings.provider not in {"akshare", "tushare"}:
        raise RuntimeError("managed market-data provider is invalid")
    return settings.raw_root / _MANAGED_CHECKPOINT_DIRECTORY / settings.provider / str(revision)


def managed_market_data_checkpoint_root(settings: MarketDataSyncSettings) -> Path:
    """Return the checkpoint namespace while preserving the raw archive root."""

    return _managed_checkpoint_root(settings)


def _managed_state_path(settings: MarketDataSyncSettings) -> Path:
    return settings.raw_root / _MANAGED_CHECKPOINT_DIRECTORY / _MANAGED_STATE_FILENAME


def _read_managed_state(path: Path) -> tuple[int, str, str] | None:
    if not path.exists():
        return None
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise RuntimeError("managed market-data settings state is invalid") from None
    if not isinstance(raw, dict):
        raise RuntimeError("managed market-data settings state is invalid")
    payload = cast(dict[object, object], raw)
    expected = {"version", "revision", "provider", "digest"}
    if set(payload) != expected:
        raise RuntimeError("managed market-data settings state is invalid")
    revision = payload.get("revision")
    provider = payload.get("provider")
    digest = payload.get("digest")
    if (
        type(revision) is not int
        or revision < 0
        or revision > 2**53 - 1
        or not isinstance(provider, str)
        or provider not in {"akshare", "tushare"}
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or payload.get("version") != _MANAGED_STATE_VERSION
    ):
        raise RuntimeError("managed market-data settings state is invalid")
    return revision, provider, digest


def _write_managed_state(path: Path, settings: MarketDataSyncSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _MANAGED_STATE_VERSION,
        "revision": settings.managed_revision,
        "provider": settings.provider,
        "digest": _managed_settings_digest(settings),
    }
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{_MANAGED_STATE_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        temporary_path = None
    except OSError:
        raise RuntimeError("managed market-data settings state is unavailable") from None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                os.unlink(temporary_path)


def _reconcile_managed_settings_state(settings: MarketDataSyncSettings) -> None:
    if settings.managed_settings_url is None:
        return
    revision = settings.managed_revision
    if type(revision) is not int or revision < 0:
        raise RuntimeError("managed market-data settings revision is invalid")
    if settings.managed_settings_worker_token is None:
        raise RuntimeError("managed market-data settings source is incomplete")
    state_path = _managed_state_path(settings)
    try:
        with MarketDataCheckpointStore(state_path.parent).locked():
            previous = _read_managed_state(state_path)
            current_digest = _managed_settings_digest(settings)
            if previous is None:
                _write_managed_state(state_path, settings)
                return
            previous_revision, previous_provider, previous_digest = previous
            if revision < previous_revision:
                raise RuntimeError("managed market-data settings revision rolled back")
            if revision == previous_revision:
                if settings.provider != previous_provider or current_digest != previous_digest:
                    raise RuntimeError("managed market-data settings changed without a revision")
                return
            _write_managed_state(state_path, settings)
    except MarketDataCheckpointError:
        raise RuntimeError("managed market-data settings state is unavailable") from None


def refresh_managed_market_data_settings(
    settings: MarketDataSyncSettings,
    *,
    remote_transport: RemoteSettingsTransport | None = None,
) -> MarketDataSyncSettings:
    """Fetch the next managed settings snapshot at a run-cycle boundary."""

    if settings.managed_settings_url is None:
        return settings
    worker_token = settings.managed_settings_worker_token
    current_revision = settings.managed_revision
    if worker_token is None or type(current_revision) is not int:
        raise RemoteMarketDataSettingsError("managed market-data settings source is incomplete")
    remote = fetch_remote_market_data_settings(
        settings.managed_settings_url,
        worker_token,
        allow_local_http=settings.managed_settings_allow_local_http,
        transport=remote_transport,
    )
    if remote.revision < current_revision:
        raise RemoteMarketDataSettingsError("managed market-data settings revision rolled back")
    if remote.revision == current_revision:
        if remote.provider != settings.provider or remote.token != settings.token:
            raise RemoteMarketDataSettingsError(
                "managed market-data settings changed without a revision"
            )
        return settings
    return replace(
        settings,
        provider=remote.provider,
        token=remote.token,
        tushare_endpoint=_MANAGED_TUSHARE_ENDPOINT,
        managed_revision=remote.revision,
    )


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
        endpoint = (
            _MANAGED_TUSHARE_ENDPOINT
            if settings.managed_settings_url is not None
            else settings.tushare_endpoint
        )
        provider = TushareMarketDataProvider(
            TushareConfig(token=settings.token, endpoint=endpoint),
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
    checkpoint_root: Path | None = None,
) -> MarketDataRunner:
    """Compose the selected provider, immutable raw storage, and ClickHouse writer."""

    _reconcile_managed_settings_state(settings)
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
    quality_publisher = (
        None
        if settings.quality_public_root is None
        else MarketQualityPublicPublisher(
            settings.raw_root, settings.quality_public_root, clock=clock
        )
    )
    quality_sink = MarketDataQualitySink(
        settings.raw_root / "market-quality", clock=clock, publisher=quality_publisher
    )
    collector = MarketDataCollector(
        provider,
        raw_storage,
        writer,
        quality_sink=quality_sink,
    )
    selected_checkpoint_root = (
        checkpoint_root if checkpoint_root is not None else _managed_checkpoint_root(settings)
    )
    return MarketDataRunner(
        collector,
        symbols=settings.symbols,
        minute_symbols=settings.minute_symbols,
        daily_lookback_days=settings.daily_lookback_days,
        minute_interval=settings.minute_interval,
        checkpoint_root=selected_checkpoint_root,
        clock=clock,
        quality_publisher=quality_publisher,
        provider=settings.provider,
        status_public_root=settings.status_public_root,
    )


def run_market_data_sync(
    settings: MarketDataSyncSettings,
    *,
    clock: Clock = _utc_now,
    sleeper: Sleeper = time_module.sleep,
    remote_transport: RemoteSettingsTransport | None = None,
) -> None:
    """Run once by default, or continuously when explicitly configured."""

    current_settings = settings
    runner = build_market_data_runner(current_settings, clock=clock)
    while True:
        refreshed_settings = refresh_managed_market_data_settings(
            current_settings,
            remote_transport=remote_transport,
        )
        if (
            refreshed_settings.managed_revision != current_settings.managed_revision
            or refreshed_settings.provider != current_settings.provider
            or refreshed_settings.token != current_settings.token
        ):
            current_settings = refreshed_settings
            runner = build_market_data_runner(current_settings, clock=clock)
        else:
            current_settings = refreshed_settings
        summary = runner.run_cycle()
        print(json.dumps(summary.to_dict(), ensure_ascii=False, sort_keys=True), flush=True)
        if not current_settings.continuous:
            return
        sleeper(float(current_settings.poll_seconds))


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
    "managed_market_data_checkpoint_root",
    "refresh_managed_market_data_settings",
    "run_market_data_sync",
]
