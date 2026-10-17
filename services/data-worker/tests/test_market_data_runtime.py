"""Runtime composition tests for continuous real market-data sync."""

from __future__ import annotations

import errno
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Never, cast
from unittest.mock import Mock
from urllib.request import Request

import pytest
from ashare_contracts.market_data_bar import Bar
from data_worker.jobs.market_data import checkpoint as checkpoint_module
from data_worker.jobs.market_data.checkpoint import (
    MarketDataCheckpointBusyError,
    MarketDataCheckpointError,
    MarketDataCheckpointStore,
)
from data_worker.jobs.market_data.collector import (
    MarketDataCollectionResult,
    MarketDataCollector,
    RawBarCapture,
    RawBarProvider,
)
from data_worker.jobs.market_data.quality import MarketDataQualitySink
from data_worker.jobs.market_data.runtime import (
    MarketDataRunner,
    MarketDataSyncSettings,
    build_market_data_provider,
    build_market_data_runner,
    load_market_data_settings,
)
from data_worker.jobs.market_data.status import (
    STATUS_FILENAME,
    MarketDataSyncStatusError,
)
from data_worker.providers.akshare import AKShareMarketDataProvider
from data_worker.raw.storage import LocalFileStorage
from market_core.providers import ProviderAuthError, ProviderDataError
from market_core.providers.tushare import TushareMarketDataProvider
from market_core.storage import StoredBar


class RecordingCollector:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, str, int]] = []

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
    ) -> MarketDataCollectionResult:
        _ = processing_time
        self.calls.append((unified_code, interval, start_date, end_date, run_id, capture_ordinal))
        return MarketDataCollectionResult(
            raw_capture_id=f"capture-{capture_ordinal}",
            received_bars=2,
            written_bars=2,
        )


def _environment() -> dict[str, str]:
    return {
        "TUSHARE_TOKEN": "runtime-secret",
        "MARKET_DATA_SYMBOLS": "000001.SH,399001.SZ",
        "MARKET_DATA_RAW_ROOT": "/tmp/kunlun-market-raw-test",
        "CLICKHOUSE_URL": "http://clickhouse:8123",
        "CLICKHOUSE_DATABASE": "kunlun",
        "CLICKHOUSE_USER": "writer",
        "CLICKHOUSE_PASSWORD": "local-only",
        "MARKET_DATA_POLL_SECONDS": "30",
        "MARKET_DATA_DAILY_LOOKBACK_DAYS": "10",
    }


def test_settings_default_to_akshare_without_token() -> None:
    settings = load_market_data_settings({})

    assert settings.provider == "akshare"
    assert settings.token is None
    assert settings.symbols == ("600519.SH",)
    assert settings.minute_symbols == ()
    assert settings.daily_lookback_days == 730
    assert settings.continuous is False
    assert settings.quality_public_root is None
    assert settings.status_public_root is None


def test_daily_mode_uses_an_explicit_shanghai_time_and_keeps_once_default() -> None:
    from datetime import time

    assert load_market_data_settings({}).daily_at is None
    daily = load_market_data_settings(
        {"MARKET_DATA_RUN_MODE": "daily", "MARKET_DATA_DAILY_AT": "10:15"}
    )
    assert daily.daily_at == time(10, 15)
    assert daily.continuous is False
    assert load_market_data_settings({"MARKET_DATA_RUN_MODE": "daily"}).daily_at == time(9)


@pytest.mark.parametrize("value", ["24:00", "9:00", "09:60", "09:00:00"])
def test_daily_mode_rejects_invalid_schedule_time(value: str) -> None:
    with pytest.raises((RuntimeError, ValueError), match="HH:MM"):
        load_market_data_settings({"MARKET_DATA_RUN_MODE": "daily", "MARKET_DATA_DAILY_AT": value})


def test_daily_mode_rejects_minute_collection_before_startup() -> None:
    with pytest.raises(ValueError, match="daily-only"):
        load_market_data_settings(
            {"MARKET_DATA_RUN_MODE": "daily", "MARKET_DATA_MINUTE_SYMBOLS": "600519.SH"}
        )


def test_daily_mode_rejects_managed_settings_before_any_remote_request() -> None:
    calls: list[Request] = []

    def transport(request: Request, _timeout: float) -> Never:
        calls.append(request)
        raise AssertionError("daily mode must not fetch managed settings")

    with pytest.raises(ValueError, match="daily-only local settings"):
        load_market_data_settings(
            {
                "MARKET_DATA_RUN_MODE": "daily",
                "MARKET_DATA_SETTINGS_URL": "https://control.example.test/api/v1/internal/market-data/settings",
                "MARKET_DATA_SETTINGS_WORKER_TOKEN": "worker-token-" + "x" * 32,
            },
            remote_transport=transport,
        )
    assert calls == []


def test_daily_entrypoint_restarts_without_repeating_the_confirmed_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_worker.jobs.market_data import runtime

    now = datetime(2026, 10, 16, 2, tzinfo=UTC)
    settings = load_market_data_settings(
        {
            "MARKET_DATA_RUN_MODE": "daily",
            "MARKET_DATA_RAW_ROOT": str(tmp_path / "raw"),
            "MARKET_DATA_STATUS_PUBLIC_ROOT": str(tmp_path / "public"),
        }
    )
    collector = RecordingCollector()

    def build(selected: MarketDataSyncSettings, **_kwargs: object) -> MarketDataRunner:
        return MarketDataRunner(
            collector,
            symbols=selected.symbols,
            daily_lookback_days=selected.daily_lookback_days,
            clock=lambda: now,
            checkpoint_root=selected.raw_root,
            status_public_root=selected.status_public_root,
        )

    def stop_waiting(seconds: float) -> None:
        assert 0 < seconds <= 60
        raise InterruptedError("test stop after one scheduler step")

    monkeypatch.setattr(runtime, "build_market_data_runner", build)
    for _ in range(2):
        with pytest.raises(InterruptedError, match="test stop"):
            runtime.run_market_data_sync(settings, clock=lambda: now, sleeper=stop_waiting)
    assert len(collector.calls) == 1
    public = json.loads((tmp_path / "public" / "market-data-sync-status.json").read_text())
    assert public["status"] == "SUCCEEDED"
    assert public["lastSuccessResult"]["requests"] == 1


def test_settings_enable_public_sync_status_only_for_explicit_nonempty_root(
    tmp_path: Path,
) -> None:
    assert (
        load_market_data_settings({"MARKET_DATA_STATUS_PUBLIC_ROOT": " "}).status_public_root
        is None
    )
    settings = load_market_data_settings(
        {"MARKET_DATA_STATUS_PUBLIC_ROOT": str(tmp_path / "public-status")}
    )
    assert settings.status_public_root == tmp_path / "public-status"


def test_status_scope_limit_is_opt_in_and_accepts_one_hundred_symbols(
    tmp_path: Path,
) -> None:
    symbols_100 = tuple(f"{index:06d}.SH" for index in range(1, 101))
    enabled = MarketDataRunner(
        RecordingCollector(),
        symbols=symbols_100,
        daily_lookback_days=2,
        status_public_root=tmp_path / "status-100",
    )

    enabled.run_cycle()

    status = json.loads((tmp_path / "status-100" / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert len(status["symbols"]) == 100
    symbols_101 = tuple(f"{index:06d}.SH" for index in range(1, 102))
    disabled = MarketDataRunner(
        RecordingCollector(),
        symbols=symbols_101,
        daily_lookback_days=2,
    )
    assert disabled.run_cycle().requests == 101

    with pytest.raises(MarketDataSyncStatusError, match="between 1 and 100 unique symbols"):
        MarketDataRunner(
            RecordingCollector(),
            symbols=symbols_101,
            daily_lookback_days=2,
            status_public_root=tmp_path / "status-101",
        )


@pytest.mark.parametrize(
    ("error", "error_code"),
    (
        (ProviderAuthError("provider secret-marker"), "SOURCE_ERROR"),
        (ProviderDataError("malformed secret-marker"), "VALIDATION_ERROR"),
        (ValueError("invalid secret-marker"), "VALIDATION_ERROR"),
        (RuntimeError("internal secret-marker"), "SYNC_ERROR"),
    ),
    ids=("provider", "provider-data", "validation", "sync"),
)
def test_status_failure_publishes_only_fixed_error_categories(
    tmp_path: Path,
    error: Exception,
    error_code: str,
) -> None:
    class FailingCollector:
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
        ) -> MarketDataCollectionResult:
            _ = (unified_code, interval, start_date, end_date, run_id, capture_ordinal)
            _ = processing_time
            raise error

    runner = MarketDataRunner(
        FailingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        clock=lambda: datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        status_public_root=tmp_path,
    )

    with pytest.raises(type(error)):
        runner.run_cycle()

    status_text = (tmp_path / STATUS_FILENAME).read_text(encoding="utf-8")
    status = json.loads(status_text)
    assert status["status"] == "FAILED"
    assert status["errorCode"] == error_code
    assert "secret-marker" not in status_text


def test_settings_enable_public_quality_only_for_explicit_nonempty_root() -> None:
    assert (
        load_market_data_settings({"MARKET_DATA_QUALITY_PUBLIC_ROOT": "  "}).quality_public_root
        is None
    )
    settings = load_market_data_settings(
        {"MARKET_DATA_QUALITY_PUBLIC_ROOT": "/var/lib/kunlun/public-quality"}
    )
    assert settings.quality_public_root == Path("/var/lib/kunlun/public-quality")


def test_tushare_defaults_use_the_conservative_daily_symbol() -> None:
    settings = load_market_data_settings(
        {"MARKET_DATA_PROVIDER": "tushare", "TUSHARE_TOKEN": "runtime-secret"}
    )

    assert settings.symbols == ("600519.SH",)
    assert settings.minute_symbols == ()


def test_tushare_requires_token_and_keeps_it_out_of_repr() -> None:
    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN is required"):
        load_market_data_settings({"MARKET_DATA_PROVIDER": "tushare"})

    environment = _environment()
    environment["MARKET_DATA_PROVIDER"] = "tushare"
    settings = load_market_data_settings(environment)

    assert settings.symbols == ("000001.SH", "399001.SZ")
    assert settings.minute_symbols == ()
    assert settings.poll_seconds == 30
    assert "runtime-secret" not in repr(settings)


def test_continuous_mode_requires_a_safe_poll_interval() -> None:
    environment = _environment()
    environment.update({"MARKET_DATA_RUN_MODE": "continuous", "MARKET_DATA_POLL_SECONDS": "59"})

    with pytest.raises(RuntimeError, match="at least 60"):
        load_market_data_settings(environment)


def test_invalid_provider_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="MARKET_DATA_PROVIDER"):
        load_market_data_settings({"MARKET_DATA_PROVIDER": "vendor"})


def test_builder_selects_provider_without_network() -> None:
    akshare_settings = load_market_data_settings({})
    akshare_provider = build_market_data_provider(akshare_settings)
    assert isinstance(akshare_provider, AKShareMarketDataProvider)

    tushare_environment = _environment()
    tushare_environment["MARKET_DATA_PROVIDER"] = "tushare"
    tushare_settings = load_market_data_settings(tushare_environment)
    tushare_provider = build_market_data_provider(tushare_settings)
    assert isinstance(tushare_provider, TushareMarketDataProvider)


def test_builder_accepts_injected_provider_factory() -> None:
    settings = load_market_data_settings({})
    seen: list[str] = []

    def provider_factory(
        settings_arg: MarketDataSyncSettings, _clock: Callable[[], datetime]
    ) -> RawBarProvider:
        seen.append(settings_arg.provider)
        return AKShareMarketDataProvider(client=object())

    build_market_data_runner(settings, provider_factory=provider_factory)

    assert seen == ["akshare"]


def test_builder_wires_durable_quality_sink_under_raw_root() -> None:
    settings = load_market_data_settings({"MARKET_DATA_RAW_ROOT": "/tmp/market-data-quality-test"})

    runner = build_market_data_runner(settings)

    collector = cast(MarketDataCollector, runner._collector)  # pyright: ignore[reportPrivateUsage]
    quality_sink = cast(MarketDataQualitySink, collector._quality_sink)  # pyright: ignore[reportPrivateUsage]
    assert isinstance(quality_sink, MarketDataQualitySink)
    assert quality_sink.root == settings.raw_root / "market-quality"


def test_builder_wires_public_quality_publisher_only_when_configured(tmp_path: Path) -> None:
    settings = load_market_data_settings(
        {
            "MARKET_DATA_RAW_ROOT": str(tmp_path / "raw"),
            "MARKET_DATA_QUALITY_PUBLIC_ROOT": str(tmp_path / "public"),
        }
    )

    runner = build_market_data_runner(settings)

    collector = cast(MarketDataCollector, runner._collector)  # pyright: ignore[reportPrivateUsage]
    quality_sink = cast(MarketDataQualitySink, collector._quality_sink)  # pyright: ignore[reportPrivateUsage]
    assert quality_sink._publisher is not None  # pyright: ignore[reportPrivateUsage]
    assert runner._quality_publisher is not None  # pyright: ignore[reportPrivateUsage]


def test_runner_publishes_at_cycle_end_when_public_hook_is_enabled() -> None:
    class Publisher:
        def __init__(self) -> None:
            self.calls = 0

        def publish_cycle(self) -> object:
            self.calls += 1
            return None

    publisher = Publisher()
    runner = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        run_id="market-quality-cycle",
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        quality_publisher=publisher,
    )

    runner.run_cycle()

    assert publisher.calls == 1


def test_checkpoint_replay_cycle_keeps_public_hook_at_cycle_boundary(tmp_path: Path) -> None:
    class Publisher:
        def __init__(self) -> None:
            self.calls = 0

        def publish_cycle(self) -> object:
            self.calls += 1
            return None

    publisher = Publisher()
    runner = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        quality_publisher=publisher,
    )

    runner.run_cycle()
    runner.run_cycle()

    assert publisher.calls == 2


def test_first_cycle_backfills_daily_then_collects_current_minutes() -> None:
    collector = RecordingCollector()
    runner = MarketDataRunner(
        collector,
        symbols=("000001.SH", "399001.SZ"),
        minute_symbols=("000001.SH", "399001.SZ"),
        daily_lookback_days=10,
        run_id="market-run-1",
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    summary = runner.run_cycle()

    assert [(call[0], call[1], call[2], call[3]) for call in collector.calls] == [
        ("000001.SH", "DAILY", "2026-08-17", "2026-08-26"),
        ("399001.SZ", "DAILY", "2026-08-17", "2026-08-26"),
        ("000001.SH", "MINUTE_1", "2026-08-27", "2026-08-27"),
        ("399001.SZ", "MINUTE_1", "2026-08-27", "2026-08-27"),
    ]
    assert [call[5] for call in collector.calls] == [1, 2, 3, 4]
    assert summary.requests == 4
    assert summary.received_bars == 8
    assert summary.written_bars == 8


def test_same_day_cycle_only_refreshes_minutes() -> None:
    collector = RecordingCollector()
    runner = MarketDataRunner(
        collector,
        symbols=("000001.SH",),
        minute_symbols=("000001.SH",),
        daily_lookback_days=10,
        run_id="market-run-2",
        clock=lambda: datetime(2026, 8, 27, 5, 0, tzinfo=UTC),
    )

    runner.run_cycle()
    collector.calls.clear()
    summary = runner.run_cycle()

    assert [(call[0], call[1]) for call in collector.calls] == [("000001.SH", "MINUTE_1")]
    assert summary.requests == 1
    assert collector.calls[0][5] == 3


def test_index_symbol_runs_daily_and_minute_requests() -> None:
    collector = RecordingCollector()
    runner = MarketDataRunner(
        collector,
        symbols=("000001.SH",),
        minute_symbols=("000001.SH",),
        daily_lookback_days=10,
        run_id="market-run-index",
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    summary = runner.run_cycle()

    assert [(call[0], call[1]) for call in collector.calls] == [
        ("000001.SH", "DAILY"),
        ("000001.SH", "MINUTE_1"),
    ]
    assert summary.requests == 2


def test_checkpoint_restarts_with_the_same_run_and_ordinal(tmp_path: Path) -> None:
    first_collector = RecordingCollector()
    first = MarketDataRunner(
        first_collector,
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )
    first.run_cycle()

    second_collector = RecordingCollector()
    second = MarketDataRunner(
        second_collector,
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 28, 4, 0, tzinfo=UTC),
    )
    second.run_cycle()

    assert second_collector.calls[0][4] == first_collector.calls[0][4]
    assert first_collector.calls[0][5] == 1
    assert second_collector.calls[0][5] == 2


def test_checkpoint_recovers_an_in_flight_request_without_a_new_identity(tmp_path: Path) -> None:
    class FailOnceCollector(RecordingCollector):
        def collect(self, *args: object, **kwargs: object) -> MarketDataCollectionResult:
            result = super().collect(
                cast(str, args[0]),
                cast(str, args[1]),
                cast(str, args[2]),
                cast(str, args[3]),
                run_id=cast(str, kwargs["run_id"]),
                capture_ordinal=cast(int, kwargs["capture_ordinal"]),
                processing_time=cast(datetime | None, kwargs.get("processing_time")),
            )
            if len(self.calls) == 1:
                raise RuntimeError("simulated interruption")
            return result

    interrupted_collector = FailOnceCollector()
    interrupted = MarketDataRunner(
        interrupted_collector,
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="simulated interruption"):
        interrupted.run_cycle()

    resumed_collector = RecordingCollector()
    resumed = MarketDataRunner(
        resumed_collector,
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )
    resumed.run_cycle()

    assert resumed_collector.calls[0][4] == interrupted_collector.calls[0][4]
    assert resumed_collector.calls[0][5] == interrupted_collector.calls[0][5] == 1
    assert resumed_collector.calls[0][:4] == interrupted_collector.calls[0][:4]


def test_corrupt_checkpoint_fails_closed(tmp_path: Path) -> None:
    checkpoint = tmp_path / "market-data-checkpoint-v1.json"
    checkpoint.write_text("{not-json", encoding="utf-8")

    runner = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="checkpoint"):
        runner.run_cycle()


def test_checkpoint_lock_rejects_a_concurrent_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MarketDataCheckpointStore(tmp_path)
    monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0.01)

    with (
        store.locked(),
        pytest.raises(MarketDataCheckpointBusyError, match="locked"),
        store.locked(),
    ):
        pass


def test_checkpoint_empty_lock_does_not_require_an_unlocked_byte_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_fdopen = checkpoint_module.os.fdopen

    def deny_marker_write(descriptor: int, mode: str, *, closefd: bool) -> BinaryIO:
        handle = original_fdopen(descriptor, mode, closefd=closefd)
        guarded = Mock(wraps=handle)
        guarded.write.side_effect = PermissionError("byte is owned by another handle")
        return cast(BinaryIO, guarded)

    monkeypatch.setattr(checkpoint_module.os, "fdopen", deny_marker_write)
    store = MarketDataCheckpointStore(tmp_path)
    with store.locked():
        checkpoint = store.load_or_create("empty-marker-run")
    with store.locked():
        assert store.load_or_create("empty-marker-run") == checkpoint


def test_checkpoint_lock_io_failure_is_not_classified_as_competition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_handle: BinaryIO) -> None:
        raise OSError(errno.EIO, "fixture filesystem failure")

    monkeypatch.setattr(checkpoint_module, "_acquire_os_lock", fail)
    monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0.01)
    with (
        pytest.raises(MarketDataCheckpointError) as error,
        MarketDataCheckpointStore(tmp_path).locked(),
    ):
        pytest.fail("lock I/O error must stop before work")
    assert not isinstance(error.value, MarketDataCheckpointBusyError)


def test_checkpoint_status_records_zero_request_success(tmp_path: Path) -> None:
    status_root = tmp_path / "public-status"
    checkpoint_root = tmp_path / "checkpoint"

    def clock() -> datetime:
        return datetime(2026, 10, 16, 1, 0, tzinfo=UTC)

    runner = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=checkpoint_root,
        clock=clock,
        status_public_root=status_root,
    )

    first = runner.run_cycle()
    assert first.requests == 1
    second = runner.run_cycle()
    assert second.requests == 0

    payload = json.loads((status_root / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert payload["status"] == "SUCCEEDED"
    assert payload["lastSuccessResult"] == {
        "requests": 0,
        "receivedBars": 0,
        "writtenBars": 0,
        "dailyRefreshed": False,
    }


def test_status_is_not_written_when_not_configured(tmp_path: Path) -> None:
    runner = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        checkpoint_root=tmp_path / "checkpoint",
        clock=lambda: datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
    )

    runner.run_cycle()

    assert list(tmp_path.rglob(STATUS_FILENAME)) == []


def test_checkpoint_status_failure_keeps_last_success_without_error_text(
    tmp_path: Path,
) -> None:
    status_root = tmp_path / "public-status"
    checkpoint_root = tmp_path / "checkpoint"
    first = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=checkpoint_root,
        clock=lambda: datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        status_public_root=status_root,
    )
    first.run_cycle()
    successful = json.loads((status_root / STATUS_FILENAME).read_text(encoding="utf-8"))

    class FailingCollector(RecordingCollector):
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
        ) -> MarketDataCollectionResult:
            raise RuntimeError("provider token secret-marker")

    failed = MarketDataRunner(
        FailingCollector(),
        symbols=("600519.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=checkpoint_root,
        clock=lambda: datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
        status_public_root=status_root,
    )
    with pytest.raises(RuntimeError, match="provider token secret-marker"):
        failed.run_cycle()

    status_text = (status_root / STATUS_FILENAME).read_text(encoding="utf-8")
    status = json.loads(status_text)
    assert status["status"] == "FAILED"
    assert status["errorCode"] == "SYNC_ERROR"
    assert status["lastSuccessAt"] == successful["lastSuccessAt"]
    assert status["lastSuccessResult"] == successful["lastSuccessResult"]
    assert "secret-marker" not in status_text


def test_status_write_rollback_does_not_swallow_sync_failure(
    tmp_path: Path,
) -> None:
    status_root = tmp_path / "public-status"
    first = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        clock=lambda: datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        status_public_root=status_root,
    )
    first.run_cycle()
    prior_status = json.loads((status_root / STATUS_FILENAME).read_text(encoding="utf-8"))
    times = iter(
        (
            datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        )
    )

    class FailingCollector(RecordingCollector):
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
        ) -> MarketDataCollectionResult:
            raise RuntimeError("worker-secret-marker")

    runner = MarketDataRunner(
        FailingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        clock=lambda: next(times),
        status_public_root=status_root,
    )

    with pytest.raises(RuntimeError, match="worker-secret-marker"):
        runner.run_cycle()

    status_text = (status_root / STATUS_FILENAME).read_text(encoding="utf-8")
    status = json.loads(status_text)
    assert status["status"] == "RUNNING"
    assert status["lastSuccessAt"] == prior_status["lastSuccessAt"]
    assert status["lastSuccessResult"] == prior_status["lastSuccessResult"]
    assert "worker-secret-marker" not in status_text


def test_lock_contention_does_not_publish_or_replace_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_root = tmp_path / "checkpoint"
    status_root = tmp_path / "public-status"
    store = MarketDataCheckpointStore(checkpoint_root)
    first = MarketDataRunner(
        RecordingCollector(),
        symbols=("600519.SH",),
        daily_lookback_days=2,
        checkpoint_root=checkpoint_root,
        clock=lambda: datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        status_public_root=status_root,
    )
    first.run_cycle()
    status_path = status_root / STATUS_FILENAME
    before = status_path.read_bytes()

    competitor = MarketDataRunner(
        RecordingCollector(),
        symbols=("000001.SZ",),
        daily_lookback_days=2,
        checkpoint_root=checkpoint_root,
        clock=lambda: datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
        provider="tushare",
        status_public_root=status_root,
    )
    monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0.01)
    with store.locked(), pytest.raises(MarketDataCheckpointError, match="locked"):
        competitor.run_cycle()

    assert status_path.read_bytes() == before


def test_checkpoint_recovery_replays_raw_before_provider_fetch(tmp_path: Path) -> None:
    class FailOnceWriter:
        def __init__(self) -> None:
            self.calls = 0

        def write_bars(self, bars: Iterable[StoredBar]) -> int:
            del bars
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated ClickHouse failure")
            return 1

    first_provider = _ReplayableProvider()
    first_writer = FailOnceWriter()
    first_collector = MarketDataCollector(
        first_provider,
        LocalFileStorage(tmp_path),
        first_writer,
        quality_sink=MarketDataQualitySink(tmp_path / "market-quality"),
    )
    first = MarketDataRunner(
        first_collector,
        symbols=("600000.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )
    with pytest.raises(RuntimeError, match="ClickHouse"):
        first.run_cycle()

    second_provider = _ReplayableProvider()
    second_writer = first_writer
    second_collector = MarketDataCollector(
        second_provider,
        LocalFileStorage(tmp_path),
        second_writer,
        quality_sink=MarketDataQualitySink(tmp_path / "market-quality"),
    )
    second = MarketDataRunner(
        second_collector,
        symbols=("600000.SH",),
        minute_symbols=(),
        daily_lookback_days=2,
        checkpoint_root=tmp_path,
        clock=lambda: datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    )
    summary = second.run_cycle()

    assert summary.requests == 1
    assert first_provider.fetch_calls == 1
    assert second_provider.fetch_calls == 0


class _ReplayableProvider:
    fetch_calls = 0

    def fetch_raw_bars(
        self,
        unified_code: str,
        interval: str,
        start_date: str,
        end_date: str,
        cursor: str | None = None,
    ) -> RawBarCapture:
        del cursor
        self.fetch_calls += 1
        from market_core.providers.tushare import TushareBarCapture

        api_name = "daily" if interval == "DAILY" else "rt_min_daily"
        return TushareBarCapture(
            body=b'{"rows":[]}',
            api_name=api_name,
            request="POST /?code=600000.SH&date=2026-08-27",
            unified_code=unified_code,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            received_at=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        )

    def parse_bars(self, capture: RawBarCapture) -> list[Bar]:
        del capture
        from ashare_contracts.market_data_bar import Bar

        return [
            Bar.model_validate(
                {
                    "unifiedCode": "600000.SH",
                    "exchange": "SH",
                    "date": "2026-08-26",
                    "interval": "DAILY",
                    "session": "CONTINUOUS",
                    "timestamp": "2026-08-26T07:00:00.000Z",
                    "open": "10.01",
                    "high": "10.08",
                    "low": "9.99",
                    "close": "10.06",
                    "volume": 1200,
                    "amount": "12072.5",
                    "priceType": "RAW",
                }
            )
        ]
