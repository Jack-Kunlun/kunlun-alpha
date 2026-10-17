"""Per-code watchlist sync remains isolated, restartable and bounded."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from data_worker.jobs.market_data.personal_watchlist import due_for_sync, supported_code

NOW = datetime(2026, 10, 17, 2, tzinfo=UTC)


def test_supported_market_boundary():
    assert supported_code("161226.SZ")
    assert supported_code("920885.BJ")
    assert supported_code("000001.SH")
    assert not supported_code("HK:09618")
    assert not supported_code("SGE:AU99.99")
    assert not supported_code("600000.SZ")


def test_daily_success_and_retry_budget():
    assert due_for_sync(None, None, None, 0, NOW)
    assert not due_for_sync("SUCCEEDED", NOW.date(), NOW, 1, NOW)
    assert due_for_sync(
        "SUCCEEDED", NOW.date() - timedelta(days=1), NOW - timedelta(days=1), 1, NOW
    )
    assert not due_for_sync("FAILED", NOW.date(), NOW, 1, NOW)
    assert due_for_sync("FAILED", NOW.date(), NOW - timedelta(hours=2), 1, NOW)
    assert not due_for_sync("FAILED", NOW.date(), NOW - timedelta(hours=2), 3, NOW)
    assert not due_for_sync("UNSUPPORTED", NOW.date() - timedelta(days=1), NOW, 1, NOW)


def test_batch_isolates_failure_preserves_success_and_skips_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from dataclasses import replace

    from data_worker.jobs.market_data import personal_watchlist as module
    from data_worker.jobs.market_data.runtime import (
        MarketDataSyncSettings,
        MarketDataSyncSummary,
        load_market_data_settings,
    )
    from market_core.providers import ProviderUnavailableError

    states: dict[str, list[object]] = {}
    locks: set[str] = set()

    class Cursor:
        def __init__(self, rows: list[tuple[object, ...]]) -> None:
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, sql: str, params: Sequence[object] = ()) -> Cursor:
            if "SELECT DISTINCT" in sql:
                return Cursor([(x,) for x in ["600000.SH", "600001.SH", "HK:09618"]])
            code = str(params[0]) if params else ""
            if "pg_try_advisory_lock" in sql:
                if code in locks:
                    return Cursor([(False,)])
                locks.add(code)
                return Cursor([(True,)])
            if "pg_advisory_unlock" in sql:
                locks.remove(code)
                return Cursor([])
            if "SELECT status" in sql:
                row = states.get(code)
                return Cursor([] if row is None else [(row[0], row[1], row[2], row[3])])
            if "INSERT INTO" in sql:
                states[code] = ["RUNNING", params[2], params[1], 1]
                return Cursor([])
            if "UPDATE personal" in sql:
                states[str(params[-1])][0] = params[0]
                return Cursor([])
            raise AssertionError(sql)

    def connect(*args: object, **kwargs: object) -> Connection:
        return Connection()

    monkeypatch.setattr(module.psycopg, "connect", connect)
    calls: list[str] = []

    def runner(settings: MarketDataSyncSettings) -> MarketDataSyncSummary:
        calls.append(settings.symbols[0])
        if settings.symbols[0] == "600000.SH":
            raise ProviderUnavailableError("sanitized")
        return MarketDataSyncSummary("2026-10-17", 1, 2, 2, True, ())

    settings = replace(load_market_data_settings({}), raw_root=tmp_path)
    result = module.sync_watchlist("unused", settings, runner=runner, clock=lambda: NOW)
    assert result == {
        "processed": 3,
        "succeeded": 1,
        "failed": 1,
        "empty": 0,
        "unsupported": 1,
        "writtenBars": 2,
    }
    assert states["600001.SH"][0] == "SUCCEEDED"
    assert not locks
    again = module.sync_watchlist("unused", settings, runner=runner, clock=lambda: NOW)
    assert again["processed"] == 0
    assert calls == ["600000.SH", "600001.SH"]


def test_hung_sdk_call_has_process_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess
    from dataclasses import replace

    from data_worker.jobs.market_data import personal_watchlist as module
    from data_worker.jobs.market_data.runtime import load_market_data_settings
    from market_core.providers import ProviderTimeoutError

    def hung(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 90
        raise subprocess.TimeoutExpired("sanitized-child", 90)

    monkeypatch.setattr(module.subprocess, "run", hung)
    with pytest.raises(ProviderTimeoutError, match="deadline exceeded"):
        module.collect_code(replace(load_market_data_settings({}), raw_root=tmp_path))


def test_private_child_never_inherits_public_publishers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json
    import subprocess
    from dataclasses import replace

    from data_worker.jobs.market_data import personal_watchlist as module
    from data_worker.jobs.market_data.runtime import load_market_data_settings

    monkeypatch.setenv("MARKET_DATA_STATUS_PUBLIC_ROOT", str(tmp_path / "public-status"))
    monkeypatch.setenv("MARKET_DATA_QUALITY_PUBLIC_ROOT", str(tmp_path / "public-quality"))

    def child(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        from typing import cast

        environment = cast(dict[str, str], kwargs["env"])
        assert environment["MARKET_DATA_STATUS_PUBLIC_ROOT"] == ""
        assert environment["MARKET_DATA_QUALITY_PUBLIC_ROOT"] == ""
        return subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "tradingDate": "2026-10-17",
                    "requests": 1,
                    "receivedBars": 1,
                    "writtenBars": 1,
                    "dailyRefreshed": True,
                    "rawCaptureIds": [],
                }
            ),
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", child)
    assert (
        module.collect_code(replace(load_market_data_settings({}), raw_root=tmp_path)).written_bars
        == 1
    )
