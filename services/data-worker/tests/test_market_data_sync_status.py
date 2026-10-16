"""Durable, secret-free status publication tests for market-data sync."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts.data_quality_market_data_sync_status import MarketDataSyncStatus
from data_worker.jobs.market_data.status import (
    MarketDataSyncStatusError,
    MarketDataSyncStatusPublisher,
)

STATUS_FILENAME = "market-data-sync-status.json"


def _load_status(root: Path) -> dict[str, object]:
    raw = json.loads((root / STATUS_FILENAME).read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def _publisher(
    root: Path,
    *,
    provider: str = "akshare",
    symbols: tuple[str, ...] = ("600519.SH",),
    at: datetime = datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
) -> MarketDataSyncStatusPublisher:
    return MarketDataSyncStatusPublisher(
        root,
        provider=provider,
        symbols=symbols,
        clock=lambda: at,
    )


def test_success_survives_restart_and_a_later_failure(tmp_path: Path) -> None:
    first = _publisher(tmp_path)
    first.publish_running()
    first.publish_succeeded(
        requests=2,
        received_bars=12,
        written_bars=12,
        daily_refreshed=True,
    )
    successful = _load_status(tmp_path)
    success_at = successful["lastSuccessAt"]
    success_result = successful["lastSuccessResult"]

    restarted = _publisher(
        tmp_path,
        at=datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
    )
    restarted.publish_running()
    restarted.publish_failed("SOURCE_ERROR")

    failed = _load_status(tmp_path)
    assert failed["schemaVersion"] == "market-data-sync-status-v1"
    assert failed["status"] == "FAILED"
    assert failed["errorCode"] == "SOURCE_ERROR"
    assert failed["lastSuccessAt"] == success_at
    assert failed["lastSuccessResult"] == success_result
    assert failed["lastAttemptAt"] == "2026-10-17T01:00:00Z"
    assert failed["lastFinishedAt"] == "2026-10-17T01:00:00Z"
    assert set(failed) == {
        "schemaVersion",
        "status",
        "provider",
        "symbols",
        "lastAttemptAt",
        "lastFinishedAt",
        "lastSuccessAt",
        "lastSuccessResult",
        "errorCode",
    }
    if os.name != "nt":
        assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755
        assert stat.S_IMODE((tmp_path / STATUS_FILENAME).stat().st_mode) == 0o644
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("prior_terminal_status", ("SUCCEEDED", "FAILED"))
def test_second_running_attempt_clears_finished_at_and_keeps_last_success(
    tmp_path: Path,
    prior_terminal_status: str,
) -> None:
    first = _publisher(tmp_path, at=datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    first.publish_running()
    first.publish_succeeded(
        requests=2,
        received_bars=8,
        written_bars=8,
        daily_refreshed=True,
    )
    if prior_terminal_status == "FAILED":
        failed = _publisher(tmp_path, at=datetime(2026, 10, 17, 1, 0, tzinfo=UTC))
        failed.publish_running()
        failed.publish_failed("SYNC_ERROR")

    prior = _load_status(tmp_path)
    current = _publisher(tmp_path, at=datetime(2026, 10, 18, 1, 0, tzinfo=UTC))
    current.publish_running()

    running = _load_status(tmp_path)
    assert running["status"] == "RUNNING"
    assert running["lastAttemptAt"] == "2026-10-18T01:00:00Z"
    assert running["lastFinishedAt"] is None
    assert running["lastSuccessAt"] == prior["lastSuccessAt"]
    assert running["lastSuccessResult"] == prior["lastSuccessResult"]


def test_successful_no_data_check_records_zero_counts(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    publisher.publish_running()
    publisher.publish_succeeded(
        requests=0,
        received_bars=0,
        written_bars=0,
        daily_refreshed=False,
    )

    status = _load_status(tmp_path)
    assert status["status"] == "SUCCEEDED"
    assert status["errorCode"] is None
    assert status["lastSuccessAt"] == "2026-10-16T01:00:00Z"
    assert status["lastSuccessResult"] == {
        "requests": 0,
        "receivedBars": 0,
        "writtenBars": 0,
        "dailyRefreshed": False,
    }


def test_clock_rollback_preserves_last_valid_status_snapshot(tmp_path: Path) -> None:
    previous = _publisher(tmp_path, at=datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    previous.publish_running()
    previous.publish_succeeded(
        requests=1,
        received_bars=4,
        written_bars=4,
        daily_refreshed=True,
    )
    previous_status = _load_status(tmp_path)

    times = iter(
        (
            datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
            datetime(2026, 10, 16, 1, 0, tzinfo=UTC),
        )
    )
    current = MarketDataSyncStatusPublisher(
        tmp_path,
        provider="akshare",
        symbols=("600519.SH",),
        clock=lambda: next(times),
    )
    current.publish_running()
    running_snapshot = (tmp_path / STATUS_FILENAME).read_bytes()

    with pytest.raises(MarketDataSyncStatusError, match="clock moved backwards"):
        current.publish_succeeded(
            requests=0,
            received_bars=0,
            written_bars=0,
            daily_refreshed=False,
        )

    assert (tmp_path / STATUS_FILENAME).read_bytes() == running_snapshot
    running = _load_status(tmp_path)
    assert running["status"] == "RUNNING"
    assert running["lastAttemptAt"] == "2026-10-17T01:00:00Z"
    assert running["lastSuccessAt"] == previous_status["lastSuccessAt"]
    assert running["lastSuccessResult"] == previous_status["lastSuccessResult"]


def test_shared_contract_allows_empty_symbols_for_unknown_status() -> None:
    model = MarketDataSyncStatus.model_validate(
        {
            "schemaVersion": "market-data-sync-status-v1",
            "status": "UNKNOWN",
            "provider": "akshare",
            "symbols": [],
            "lastAttemptAt": None,
            "lastFinishedAt": None,
            "lastSuccessAt": None,
            "lastSuccessResult": None,
            "errorCode": "NO_RUN",
        }
    )

    assert model.symbols == []


@pytest.mark.parametrize(
    "symbols",
    ((), tuple(f"{index:06d}.SH" for index in range(1, 102))),
    ids=("empty-worker-scope", "over-contract-limit"),
)
def test_worker_publisher_requires_one_to_one_hundred_symbols(
    tmp_path: Path,
    symbols: tuple[str, ...],
) -> None:
    with pytest.raises(MarketDataSyncStatusError, match="between 1 and 100"):
        MarketDataSyncStatusPublisher(
            tmp_path,
            provider="akshare",
            symbols=symbols,
        )


def test_scope_change_clears_prior_scope_success(tmp_path: Path) -> None:
    previous = _publisher(tmp_path)
    previous.publish_running()
    previous.publish_succeeded(
        requests=1,
        received_bars=3,
        written_bars=3,
        daily_refreshed=True,
    )

    changed = _publisher(
        tmp_path,
        provider="tushare",
        symbols=("600519.SH", "000001.SZ"),
        at=datetime(2026, 10, 17, 1, 0, tzinfo=UTC),
    )
    changed.publish_running()
    changed.publish_failed("SYNC_ERROR")

    status = _load_status(tmp_path)
    assert status["provider"] == "tushare"
    assert status["symbols"] == ["600519.SH", "000001.SZ"]
    assert status["lastSuccessAt"] is None
    assert status["lastSuccessResult"] is None


def test_corrupt_status_is_rejected_without_echoing_file_contents(tmp_path: Path) -> None:
    secret_marker = "do-not-echo-this-token"
    status_path = tmp_path / STATUS_FILENAME
    status_path.write_text(f"{{broken {secret_marker}", encoding="utf-8")

    with pytest.raises(MarketDataSyncStatusError) as error:
        _publisher(tmp_path).publish_running()

    assert secret_marker not in str(error.value)
    assert secret_marker in status_path.read_text(encoding="utf-8")


def test_duplicate_symbols_are_rejected_in_existing_status(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path)
    publisher.publish_running()
    status_path = tmp_path / STATUS_FILENAME
    status = _load_status(tmp_path)
    status["symbols"] = ["600519.SH", "600519.SH"]
    status_path.write_text(json.dumps(status), encoding="utf-8")

    with pytest.raises(MarketDataSyncStatusError, match="invalid"):
        publisher.publish_failed("SYNC_ERROR")


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires platform privileges")
def test_status_file_and_public_root_symlinks_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked-root"
    linked_root.symlink_to(target, target_is_directory=True)
    with pytest.raises(MarketDataSyncStatusError, match="unsafe"):
        _publisher(linked_root).publish_running()

    (target / STATUS_FILENAME).symlink_to(target / "other.json")
    with pytest.raises(MarketDataSyncStatusError, match="unsafe"):
        _publisher(target).publish_running()
