"""Durable single-instance tests for the opt-in daily market-data schedule."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import cast

import pytest
from data_worker.jobs.market_data import checkpoint as checkpoint_module
from data_worker.jobs.market_data.checkpoint import (
    MarketDataCheckpointBusyError,
    MarketDataCheckpointError,
)
from data_worker.jobs.market_data.daily_schedule import (
    DailyMarketDataScheduleError,
    DailyMarketDataScheduler,
    parse_daily_schedule_time,
)
from market_core.providers import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

_SCOPE = "a" * 64
_STATE_NAME = "market-data-daily-schedule-v1.json"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _scheduler(
    raw_root: Path,
    clock: MutableClock,
    *,
    at: time = time(9),
    scope: str = _SCOPE,
) -> DailyMarketDataScheduler:
    return DailyMarketDataScheduler(raw_root / "daily-schedule-v1", at=at, scope=scope, clock=clock)


def _state_path(raw_root: Path) -> Path:
    return raw_root / "daily-schedule-v1" / _STATE_NAME


def _read_state(raw_root: Path) -> dict[str, object]:
    value = json.loads(_state_path(raw_root).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.parametrize(
    ("value", "expected"),
    (("00:00", time(0)), ("09:05", time(9, 5)), ("23:59", time(23, 59))),
)
def test_parse_daily_schedule_time_accepts_only_zero_padded_hh_mm(
    value: str, expected: time
) -> None:
    assert parse_daily_schedule_time(value) == expected


@pytest.mark.parametrize("value", ["9:00", "09:0", "24:00", "09:60", "09:00:00", " 09:00"])
def test_parse_daily_schedule_time_rejects_non_hh_mm_values(value: str) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        parse_daily_schedule_time(value)


def test_waits_until_schedule_then_runs_once_and_persists_private_success(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 0, 59, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)
    calls: list[None] = []

    delay = scheduler.step(lambda: calls.append(None))

    assert calls == []
    assert delay == pytest.approx(60)
    assert not _state_path(tmp_path).exists()

    clock.value = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    scheduler.step(lambda: calls.append(None))
    scheduler_restarted = _scheduler(tmp_path, clock)
    scheduler_restarted.step(lambda: calls.append(None))

    assert calls == [None]
    state = _read_state(tmp_path)
    assert state == {
        "schemaVersion": "market-data-daily-schedule-v1",
        "scope": _SCOPE,
        "scheduleDate": "2026-10-16",
        "status": "SUCCEEDED",
        "attempts": 1,
        "lastAttemptAt": "2026-10-16T01:00:00Z",
        "nextAttemptAt": None,
    }
    if os.name != "nt":
        assert (_state_path(tmp_path).parent.stat().st_mode & 0o777) == 0o700
        assert (_state_path(tmp_path).stat().st_mode & 0o777) == 0o600


def test_late_start_runs_for_today_but_changed_scope_does_not_reuse_success(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 8, 30, tzinfo=UTC))
    calls: list[str] = []
    _scheduler(tmp_path, clock).step(lambda: calls.append("first"))
    _scheduler(tmp_path, clock, at=time(10)).step(lambda: calls.append("changed-time"))
    _scheduler(tmp_path, clock, scope="b" * 64).step(lambda: calls.append("new-scope"))

    assert calls == ["first", "new-scope"]
    assert _read_state(tmp_path)["scope"] == "b" * 64


def test_scope_and_timestamp_use_the_actual_aware_attempt_time(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, 0, 123456, tzinfo=UTC))

    _scheduler(tmp_path, clock).step(lambda: None)

    assert _read_state(tmp_path)["lastAttemptAt"] == "2026-10-16T01:00:00.123456Z"


def test_naive_clock_is_rejected_before_creating_schedule_state(tmp_path: Path) -> None:
    scheduler = _scheduler(tmp_path, MutableClock(datetime(2026, 10, 16, 1, 0)))

    with pytest.raises(DailyMarketDataScheduleError, match="timezone-aware"):
        scheduler.step(lambda: pytest.fail("must reject naive clock"))
    assert not _state_path(tmp_path).exists()


def test_shanghai_midnight_starts_new_day_without_catching_up_old_dates(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 15, 59, tzinfo=UTC))
    calls: list[str] = []
    scheduler = _scheduler(tmp_path, clock, at=time(0, 2))
    scheduler.step(lambda: calls.append("day-one"))

    clock.value = datetime(2026, 10, 16, 16, 1, tzinfo=UTC)
    restarted = _scheduler(tmp_path, clock, at=time(0, 2))
    assert restarted.step(lambda: calls.append("day-two")) == pytest.approx(60)
    assert calls == ["day-one"]

    clock.value = datetime(2026, 10, 16, 16, 2, tzinfo=UTC)
    restarted.step(lambda: calls.append("day-two"))
    assert calls == ["day-one", "day-two"]
    assert _read_state(tmp_path)["scheduleDate"] == "2026-10-17"


def test_transient_errors_use_bounded_60_and_120_second_backoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ProviderTimeoutError("secret-provider-detail")

    assert scheduler.step(operation) == pytest.approx(60)
    assert _read_state(tmp_path)["status"] == "RETRY_WAIT"
    clock.value += timedelta(seconds=59)
    assert scheduler.step(operation) == pytest.approx(1)
    clock.value += timedelta(seconds=1)
    assert scheduler.step(operation) == pytest.approx(120)
    assert _read_state(tmp_path)["attempts"] == 2
    clock.value += timedelta(seconds=120)
    scheduler.step(operation)

    assert attempts == 3
    state = _read_state(tmp_path)
    assert state["status"] == "DEAD"
    assert state["attempts"] == 3
    assert state["nextAttemptAt"] is None
    assert "secret-provider-detail" not in _state_path(tmp_path).read_text(encoding="utf-8")
    assert "secret-provider-detail" not in capsys.readouterr().out


@pytest.mark.parametrize("error_type", [ProviderRateLimitError, ProviderUnavailableError])
def test_all_transient_provider_codes_retry(tmp_path: Path, error_type: type[Exception]) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error_type("private provider detail")

    assert scheduler.step(operation) == pytest.approx(60)
    clock.value += timedelta(seconds=60)
    scheduler.step(operation)

    assert calls == 2
    assert _read_state(tmp_path)["status"] == "SUCCEEDED"
    assert _read_state(tmp_path)["attempts"] == 2


def test_checkpoint_lock_busy_retries_but_other_checkpoint_errors_are_permanent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MarketDataCheckpointBusyError("private lock detail")

    assert scheduler.step(operation) == pytest.approx(60)
    assert _read_state(tmp_path)["status"] == "RETRY_WAIT"
    clock.value += timedelta(seconds=60)
    scheduler.step(operation)
    assert calls == 2
    assert _read_state(tmp_path)["status"] == "SUCCEEDED"
    assert "private lock detail" not in capsys.readouterr().out

    next_root = tmp_path / "other-checkpoint"
    permanent = _scheduler(next_root, MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC)))
    permanent.step(lambda: (_ for _ in ()).throw(MarketDataCheckpointError("corrupt")))
    assert _read_state(next_root)["status"] == "DEAD"


@pytest.mark.parametrize(
    "error",
    [ProviderAuthError("auth-secret"), ValueError("validation-secret"), RuntimeError("secret")],
)
def test_permanent_and_unknown_errors_are_dead_without_retry(
    tmp_path: Path, error: Exception, capsys: pytest.CaptureFixture[str]
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)
    calls: list[None] = []

    def fail() -> None:
        raise error

    scheduler.step(fail)
    scheduler.step(lambda: calls.append(None))

    assert calls == []
    assert _read_state(tmp_path)["status"] == "DEAD"
    assert _read_state(tmp_path)["attempts"] == 1
    assert all(
        secret not in _state_path(tmp_path).read_text(encoding="utf-8")
        for secret in ("auth-secret", "validation-secret", "secret")
    )
    output = capsys.readouterr().out
    assert all(secret not in output for secret in ("auth-secret", "validation-secret"))


def test_interrupted_running_attempt_consumes_budget_across_restarts(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    scheduler = _scheduler(tmp_path, clock)

    for expected_attempts in (1, 2):
        with pytest.raises(KeyboardInterrupt):
            scheduler.step(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        assert _read_state(tmp_path)["attempts"] == expected_attempts
        scheduler = _scheduler(tmp_path, clock)

    with pytest.raises(KeyboardInterrupt):
        scheduler.step(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert _read_state(tmp_path)["attempts"] == 3

    calls: list[None] = []
    scheduler = _scheduler(tmp_path, clock)
    scheduler.step(lambda: calls.append(None))
    assert calls == []
    assert _read_state(tmp_path)["status"] == "DEAD"
    assert _read_state(tmp_path)["attempts"] == 3


def test_clock_rollback_preserves_existing_ledger(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    with pytest.raises(KeyboardInterrupt):
        _scheduler(tmp_path, clock).step(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    ledger = _state_path(tmp_path)
    before = ledger.read_bytes()

    clock.value -= timedelta(seconds=1)
    with pytest.raises(DailyMarketDataScheduleError, match="clock"):
        _scheduler(tmp_path, clock).step(lambda: pytest.fail("must fail closed"))
    assert ledger.read_bytes() == before


def test_future_ledger_date_fails_closed_without_replacement(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 10, 17, 1, 0, tzinfo=UTC))
    with pytest.raises(KeyboardInterrupt):
        _scheduler(tmp_path, clock).step(lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
    ledger = _state_path(tmp_path)
    before = ledger.read_bytes()

    clock.value = datetime(2026, 10, 16, 1, 0, tzinfo=UTC)
    with pytest.raises(DailyMarketDataScheduleError, match="clock"):
        _scheduler(tmp_path, clock).step(lambda: pytest.fail("must fail closed"))
    assert ledger.read_bytes() == before


def test_failed_terminal_write_leaves_durable_running_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduler = _scheduler(tmp_path, MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC)))
    real_replace = os.replace
    state_replacements = 0

    def fail_terminal_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        nonlocal state_replacements
        if Path(destination) == _state_path(tmp_path):
            state_replacements += 1
            if state_replacements == 2:
                raise OSError("simulated terminal replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_terminal_replace)
    with pytest.raises(DailyMarketDataScheduleError, match="publish daily schedule"):
        scheduler.step(lambda: None)

    state = _read_state(tmp_path)
    assert state["status"] == "RUNNING"
    assert state["attempts"] == 1


def test_corrupt_oversized_and_symlink_state_are_rejected_without_replacement(
    tmp_path: Path,
) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    ledger = _state_path(tmp_path)
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{broken", encoding="utf-8")
    before = ledger.read_bytes()
    with pytest.raises(DailyMarketDataScheduleError, match="corrupt"):
        _scheduler(tmp_path, clock).step(lambda: pytest.fail("must reject corrupt state"))
    assert ledger.read_bytes() == before

    ledger.write_bytes(b" " * (64 * 1024 + 1))
    before = ledger.read_bytes()
    with pytest.raises(DailyMarketDataScheduleError, match="size"):
        _scheduler(tmp_path, clock).step(lambda: pytest.fail("must reject oversized state"))
    assert ledger.read_bytes() == before

    ledger.unlink()
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    try:
        ledger.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    before = target.read_bytes()
    with pytest.raises(DailyMarketDataScheduleError, match="symlink"):
        _scheduler(tmp_path, clock).step(lambda: pytest.fail("must reject symlink state"))
    assert target.read_bytes() == before


def test_symlink_schedule_directory_is_rejected_without_touching_target(tmp_path: Path) -> None:
    target = tmp_path / "private-target"
    target.mkdir()
    (target / "keep.txt").write_text("unchanged", encoding="utf-8")
    schedule_dir = tmp_path / "daily-schedule-v1"
    try:
        schedule_dir.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(DailyMarketDataScheduleError, match="symlink"):
        _scheduler(tmp_path, MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))).step(
            lambda: pytest.fail("must reject symlink directory")
        )
    assert sorted(path.name for path in target.iterdir()) == ["keep.txt"]


def test_lock_contention_does_not_run_operation_or_write_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("the test holds a POSIX flock directly")
    import fcntl

    state_dir = tmp_path / "daily-schedule-v1"
    state_dir.mkdir()
    lock_path = state_dir / ".market-data-checkpoint.lock"
    with lock_path.open("w+b") as lock_handle:
        lock_handle.write(b"\0")
        lock_handle.flush()
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0)
        calls: list[None] = []
        with pytest.raises(MarketDataCheckpointError, match="locked"):
            _scheduler(
                tmp_path,
                MutableClock(datetime(2026, 10, 16, 1, 0, tzinfo=UTC)),
            ).step(lambda: calls.append(None))
        assert calls == []
        assert not _state_path(tmp_path).exists()


def test_run_limits_each_sleep_to_sixty_seconds(tmp_path: Path) -> None:
    clock = MutableClock(datetime(2026, 10, 16, 0, 0, tzinfo=UTC))
    waits: list[float] = []

    class StopRunError(Exception):
        pass

    def stop_after_one_wait(seconds: float) -> None:
        waits.append(seconds)
        raise StopRunError

    with pytest.raises(StopRunError):
        _scheduler(tmp_path, clock).run(lambda: None, sleeper=stop_after_one_wait)

    assert waits == [60]
