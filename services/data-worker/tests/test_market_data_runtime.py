"""Runtime composition tests for continuous real market-data sync."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts.market_data_bar import Bar
from data_worker.jobs.market_data import checkpoint as checkpoint_module
from data_worker.jobs.market_data.checkpoint import (
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
from data_worker.providers.akshare import AKShareMarketDataProvider
from data_worker.raw.storage import LocalFileStorage
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
        pytest.raises(MarketDataCheckpointError, match="locked"),
        store.locked(),
    ):
        pass


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
