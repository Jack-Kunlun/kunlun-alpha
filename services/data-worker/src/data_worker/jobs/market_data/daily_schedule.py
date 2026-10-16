"""Durable, single-instance scheduling for one daily market-data operation."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time as time_module
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from ashare_contracts.providers import ProviderErrorCode
from data_worker.jobs.market_data.checkpoint import (
    MarketDataCheckpointBusyError,
    MarketDataCheckpointStore,
)
from market_core.providers import ProviderError

SCHEDULE_VERSION = "market-data-daily-schedule-v1"
SCHEDULE_FILENAME = f"{SCHEDULE_VERSION}.json"
_MAX_SCHEDULE_BYTES = 16 * 1024
_MAX_ATTEMPTS = 3
_TRANSIENT_BACKOFF_SECONDS = {1: 60, 2: 120}
_SCOPE_RE = re.compile(r"^[0-9a-f]{64}$")
_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_EXPECTED_FIELDS = {
    "schemaVersion",
    "scope",
    "scheduleDate",
    "status",
    "attempts",
    "lastAttemptAt",
    "nextAttemptAt",
}
_TRANSIENT_ERRORS = {
    ProviderErrorCode.TIMEOUT,
    ProviderErrorCode.RATE_LIMIT,
    ProviderErrorCode.UNAVAILABLE,
}


_SHANGHAI = ZoneInfo("Asia/Shanghai")


class DailyMarketDataScheduleError(RuntimeError):
    """The persisted schedule is unsafe, corrupt, or inconsistent with the clock."""


@dataclass(frozen=True, slots=True)
class _ScheduleState:
    scope: str
    schedule_date: date
    status: str
    attempts: int
    last_attempt_at: datetime
    next_attempt_at: datetime | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": SCHEDULE_VERSION,
            "scope": self.scope,
            "scheduleDate": self.schedule_date.isoformat(),
            "status": self.status,
            "attempts": self.attempts,
            "lastAttemptAt": _format_utc(self.last_attempt_at),
            "nextAttemptAt": (
                None if self.next_attempt_at is None else _format_utc(self.next_attempt_at)
            ),
        }


def parse_daily_schedule_time(value: str) -> time:
    """Parse a zero-padded 24-hour ``HH:MM`` schedule time."""
    if _TIME_RE.fullmatch(value) is None:
        raise ValueError("daily schedule time must use HH:MM")
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    if parsed.utcoffset() != timedelta(0):
        raise DailyMarketDataScheduleError("daily schedule timestamps must be UTC")
    return parsed.astimezone(UTC)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DailyMarketDataScheduleError("daily schedule state is corrupt")
        result[key] = value
    return result


def _validated_state(raw: object) -> _ScheduleState:
    if not isinstance(raw, dict):
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    payload = cast(dict[str, object], raw)
    if set(payload) != _EXPECTED_FIELDS or payload.get("schemaVersion") != SCHEDULE_VERSION:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")

    scope = payload["scope"]
    status = payload["status"]
    attempts = payload["attempts"]
    raw_date = payload["scheduleDate"]
    if not isinstance(scope, str) or _SCOPE_RE.fullmatch(scope) is None:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    if not isinstance(status, str) or status not in {
        "RUNNING",
        "RETRY_WAIT",
        "SUCCEEDED",
        "DEAD",
    }:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    if type(attempts) is not int or not 1 <= attempts <= _MAX_ATTEMPTS:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    if not isinstance(raw_date, str):
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    try:
        schedule_date = date.fromisoformat(raw_date)
    except ValueError:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt") from None
    if schedule_date.isoformat() != raw_date:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")

    last_attempt_at = _parse_timestamp(payload["lastAttemptAt"])
    next_raw = payload["nextAttemptAt"]
    next_attempt_at = None if next_raw is None else _parse_timestamp(next_raw)
    if last_attempt_at.astimezone(_SHANGHAI).date() != schedule_date:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    if status == "RETRY_WAIT":
        if attempts >= _MAX_ATTEMPTS or next_attempt_at is None:
            raise DailyMarketDataScheduleError("daily schedule state is corrupt")
        minimum_retry_at = last_attempt_at + timedelta(seconds=_TRANSIENT_BACKOFF_SECONDS[attempts])
        if next_attempt_at < minimum_retry_at:
            raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    elif next_attempt_at is not None:
        raise DailyMarketDataScheduleError("daily schedule state is corrupt")
    return _ScheduleState(
        scope=scope,
        schedule_date=schedule_date,
        status=status,
        attempts=attempts,
        last_attempt_at=last_attempt_at,
        next_attempt_at=next_attempt_at,
    )


class DailyMarketDataScheduler:
    """Run one callback per Shanghai calendar day, retaining retry state on disk.

    ``root`` is the private ``daily-schedule-v1`` directory under the raw-data
    root; the ledger and its process lock live directly in this directory.
    """

    def __init__(
        self,
        root: Path,
        *,
        at: time,
        scope: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if at.tzinfo is not None:
            raise ValueError("daily schedule time must not include a timezone")
        if _SCOPE_RE.fullmatch(scope) is None:
            raise ValueError("daily schedule scope must be a lowercase SHA-256 hex digest")
        self._directory = Path(root)
        self._state_path = self._directory / SCHEDULE_FILENAME
        self._lock_path = self._directory / ".market-data-checkpoint.lock"
        self._store = MarketDataCheckpointStore(self._directory)
        self._at = at
        self._scope = scope
        self._clock = clock

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise DailyMarketDataScheduleError("daily schedule clock must be timezone-aware")
        return now.astimezone(UTC)

    def _prepare_directory(self) -> None:
        if self._directory.is_symlink() or self._lock_path.is_symlink():
            raise DailyMarketDataScheduleError("daily schedule path must not be a symlink")
        try:
            directory_info = self._directory.lstat()
        except OSError:
            raise DailyMarketDataScheduleError("daily schedule directory is unavailable") from None
        if not stat.S_ISDIR(directory_info.st_mode):
            raise DailyMarketDataScheduleError("daily schedule path must be a directory")
        if os.name != "nt":
            try:
                os.chmod(self._directory, 0o700)
                lock_info = self._lock_path.lstat()
                if not stat.S_ISREG(lock_info.st_mode):
                    raise DailyMarketDataScheduleError("daily schedule lock must be a regular file")
                os.chmod(self._lock_path, 0o600, follow_symlinks=False)
            except DailyMarketDataScheduleError:
                raise
            except OSError:
                raise DailyMarketDataScheduleError(
                    "daily schedule directory permissions are unavailable"
                ) from None

    def _read_state(self) -> _ScheduleState | None:
        try:
            path_info = self._state_path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise DailyMarketDataScheduleError("daily schedule state is unavailable") from None
        if stat.S_ISLNK(path_info.st_mode):
            raise DailyMarketDataScheduleError("daily schedule state must not be a symlink")
        if not stat.S_ISREG(path_info.st_mode):
            raise DailyMarketDataScheduleError("daily schedule state must be a regular file")
        if path_info.st_size > _MAX_SCHEDULE_BYTES:
            raise DailyMarketDataScheduleError("daily schedule state exceeds size limit")
        if os.name != "nt":
            try:
                os.chmod(self._state_path, 0o600, follow_symlinks=False)
            except OSError:
                raise DailyMarketDataScheduleError(
                    "daily schedule state permissions are unavailable"
                ) from None

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(self._state_path, flags)
        except OSError:
            raise DailyMarketDataScheduleError("daily schedule state is unavailable") from None
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                descriptor = -1
                opened_info = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened_info.st_mode):
                    raise DailyMarketDataScheduleError(
                        "daily schedule state must be a regular file"
                    )
                if opened_info.st_size > _MAX_SCHEDULE_BYTES:
                    raise DailyMarketDataScheduleError("daily schedule state exceeds size limit")
                encoded = handle.read(_MAX_SCHEDULE_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(encoded) > _MAX_SCHEDULE_BYTES:
            raise DailyMarketDataScheduleError("daily schedule state exceeds size limit")
        try:
            raw = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except DailyMarketDataScheduleError:
            raise
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise DailyMarketDataScheduleError("daily schedule state is corrupt") from None
        return _validated_state(raw)

    def _write_state(self, state: _ScheduleState) -> None:
        try:
            path_info = self._state_path.lstat()
        except FileNotFoundError:
            path_info = None
        except OSError:
            raise DailyMarketDataScheduleError("daily schedule state is unavailable") from None
        if path_info is not None:
            if stat.S_ISLNK(path_info.st_mode):
                raise DailyMarketDataScheduleError("daily schedule state must not be a symlink")
            if not stat.S_ISREG(path_info.st_mode):
                raise DailyMarketDataScheduleError("daily schedule state must be a regular file")

        payload = json.dumps(
            state.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        temporary_path: Path | None = None
        try:
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=self._directory,
                prefix=".market-data-daily-schedule-",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
                else:
                    os.chmod(temporary_path, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._state_path)
            if os.name != "nt":
                try:
                    directory_descriptor = os.open(self._directory, os.O_RDONLY)
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
                except OSError:
                    # Match checkpoint durability behavior: the file itself was fsynced
                    # before replacement; directory fsync is best effort on some filesystems.
                    pass
        except OSError:
            raise DailyMarketDataScheduleError("unable to publish daily schedule state") from None
        finally:
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()

    def _validate_clock(self, state: _ScheduleState | None, now: datetime) -> None:
        if state is None:
            return
        today = now.astimezone(_SHANGHAI).date()
        if state.schedule_date > today:
            raise DailyMarketDataScheduleError("daily schedule clock is behind persisted date")
        if now < state.last_attempt_at:
            raise DailyMarketDataScheduleError("daily schedule clock moved backwards")

    def _scheduled_time(self, day: date) -> datetime:
        return datetime.combine(day, self._at, tzinfo=_SHANGHAI).astimezone(UTC)

    def _seconds_until_next_day(self, now: datetime) -> float:
        next_day = now.astimezone(_SHANGHAI).date() + timedelta(days=1)
        return (self._scheduled_time(next_day) - now).total_seconds()

    @staticmethod
    def _seconds_until(target: datetime, now: datetime) -> float:
        return max(0.0, (target - now).total_seconds())

    def _finish_attempt(
        self,
        *,
        operation: Callable[[], None],
        schedule_date: date,
        attempts: int,
        started_at: datetime,
    ) -> float:
        try:
            operation()
        except Exception as error:
            finished_at = self._now()
            if finished_at < started_at:
                raise DailyMarketDataScheduleError(
                    "daily schedule clock moved backwards during attempt"
                ) from None
            retryable = (
                isinstance(error, ProviderError) and error.code in _TRANSIENT_ERRORS
            ) or isinstance(error, MarketDataCheckpointBusyError)
            if retryable and attempts < _MAX_ATTEMPTS:
                delay = _TRANSIENT_BACKOFF_SECONDS[attempts]
                self._write_state(
                    _ScheduleState(
                        scope=self._scope,
                        schedule_date=schedule_date,
                        status="RETRY_WAIT",
                        attempts=attempts,
                        last_attempt_at=started_at,
                        next_attempt_at=finished_at + timedelta(seconds=delay),
                    )
                )
                print("market-data daily schedule retry scheduled", flush=True)
                return float(delay)
            self._write_state(
                _ScheduleState(
                    scope=self._scope,
                    schedule_date=schedule_date,
                    status="DEAD",
                    attempts=attempts,
                    last_attempt_at=started_at,
                    next_attempt_at=None,
                )
            )
            print("market-data daily schedule marked dead", flush=True)
            return self._seconds_until_next_day(finished_at)

        finished_at = self._now()
        if finished_at < started_at:
            raise DailyMarketDataScheduleError(
                "daily schedule clock moved backwards during attempt"
            )
        self._write_state(
            _ScheduleState(
                scope=self._scope,
                schedule_date=schedule_date,
                status="SUCCEEDED",
                attempts=attempts,
                last_attempt_at=started_at,
                next_attempt_at=None,
            )
        )
        return self._seconds_until_next_day(finished_at)

    def step(self, operation: Callable[[], None]) -> float:
        """Run when due, or return seconds until the next due check."""
        if self._directory.is_symlink() or self._lock_path.is_symlink():
            raise DailyMarketDataScheduleError("daily schedule path must not be a symlink")
        with self._store.locked():
            self._prepare_directory()
            now = self._now()
            state = self._read_state()
            self._validate_clock(state, now)
            today = now.astimezone(_SHANGHAI).date()
            active = (
                state is not None and state.scope == self._scope and state.schedule_date == today
            )
            if active and state is not None:
                if state.status in {"SUCCEEDED", "DEAD"}:
                    return self._seconds_until_next_day(now)
                if state.status == "RETRY_WAIT":
                    assert state.next_attempt_at is not None
                    if now < state.next_attempt_at:
                        return self._seconds_until(state.next_attempt_at, now)
                if state.status == "RUNNING" and state.attempts >= _MAX_ATTEMPTS:
                    self._write_state(
                        _ScheduleState(
                            scope=self._scope,
                            schedule_date=today,
                            status="DEAD",
                            attempts=state.attempts,
                            last_attempt_at=state.last_attempt_at,
                            next_attempt_at=None,
                        )
                    )
                    print("market-data daily schedule marked dead", flush=True)
                    return self._seconds_until_next_day(now)
                attempts = state.attempts + 1
            else:
                scheduled = self._scheduled_time(today)
                if now < scheduled:
                    return self._seconds_until(scheduled, now)
                attempts = 1

            started_at = now
            self._write_state(
                _ScheduleState(
                    scope=self._scope,
                    schedule_date=today,
                    status="RUNNING",
                    attempts=attempts,
                    last_attempt_at=started_at,
                    next_attempt_at=None,
                )
            )
            return self._finish_attempt(
                operation=operation,
                schedule_date=today,
                attempts=attempts,
                started_at=started_at,
            )

    def run(
        self,
        operation: Callable[[], None],
        *,
        sleeper: Callable[[float], None] = time_module.sleep,
    ) -> None:
        """Continuously step, splitting all idle waits into at most 60 seconds."""
        while True:
            delay = self.step(operation)
            sleeper(min(60.0, max(0.001, delay)))


__all__ = [
    "DailyMarketDataScheduleError",
    "DailyMarketDataScheduler",
    "SCHEDULE_FILENAME",
    "SCHEDULE_VERSION",
    "parse_daily_schedule_time",
]
