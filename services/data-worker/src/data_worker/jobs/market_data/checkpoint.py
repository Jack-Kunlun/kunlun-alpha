"""Crash-safe, process-exclusive checkpoint state for market-data runs."""

from __future__ import annotations

import errno
import json
import os
import re
import tempfile
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import BinaryIO, cast
from uuid import uuid4

CHECKPOINT_VERSION = "market-data-checkpoint-v1"
CHECKPOINT_FILENAME = f"{CHECKPOINT_VERSION}.json"
_LOCK_FILENAME = ".market-data-checkpoint.lock"
_LOCK_WAIT_SECONDS = 2.0
_LOCK_POLL_SECONDS = 0.01
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class MarketDataCheckpointError(RuntimeError):
    """Checkpoint state is corrupt, inconsistent, or currently unavailable."""


class MarketDataCheckpointBusyError(MarketDataCheckpointError):
    """Another process temporarily owns the unchanged checkpoint lock."""


@dataclass(frozen=True, slots=True)
class InFlightRequest:
    """The exact request identity that may be retried after a process crash."""

    kind: str
    trading_date: str
    unified_code: str
    interval: str
    start_date: str
    end_date: str
    capture_ordinal: int
    processing_time: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "trading_date": self.trading_date,
            "unified_code": self.unified_code,
            "interval": self.interval,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "capture_ordinal": self.capture_ordinal,
            "processing_time": self.processing_time.astimezone(UTC).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class MarketDataCheckpoint:
    """Versioned runner state published only after a request is durable."""

    run_id: str
    next_capture_ordinal: int
    daily_trading_date: str | None = None
    daily_completed_symbols: tuple[str, ...] = ()
    in_flight: InFlightRequest | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "version": CHECKPOINT_VERSION,
            "run_id": self.run_id,
            "next_capture_ordinal": self.next_capture_ordinal,
            "daily_trading_date": self.daily_trading_date,
            "daily_completed_symbols": list(self.daily_completed_symbols),
            "in_flight": None if self.in_flight is None else self.in_flight.to_dict(),
        }


def _validate_run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise MarketDataCheckpointError("checkpoint run_id is invalid")
    return value


def _validate_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise MarketDataCheckpointError(f"checkpoint {field} is invalid")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise MarketDataCheckpointError(f"checkpoint {field} is invalid") from error
    return value


def _validate_symbol(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 32:
        raise MarketDataCheckpointError("checkpoint symbol is invalid")
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise MarketDataCheckpointError("checkpoint symbol is invalid")
    return value


def _validate_request(raw: object) -> InFlightRequest:
    if not isinstance(raw, dict):
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    payload = cast(dict[str, object], raw)
    expected = {
        "kind",
        "trading_date",
        "unified_code",
        "interval",
        "start_date",
        "end_date",
        "capture_ordinal",
        "processing_time",
    }
    if set(payload) != expected:
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    kind = payload["kind"]
    interval = payload["interval"]
    if not isinstance(kind, str) or kind not in {"DAILY", "MINUTE"}:
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    if not isinstance(interval, str):
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    if kind == "DAILY" and interval != "DAILY":
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    if kind == "MINUTE" and interval not in {"MINUTE_1", "MINUTE_5"}:
        raise MarketDataCheckpointError("checkpoint in-flight request is invalid")
    ordinal = payload["capture_ordinal"]
    if type(ordinal) is not int or ordinal < 1:
        raise MarketDataCheckpointError("checkpoint capture ordinal is invalid")
    processing_time = payload["processing_time"]
    if not isinstance(processing_time, str):
        raise MarketDataCheckpointError("checkpoint processing time is invalid")
    try:
        parsed_processing_time = datetime.fromisoformat(processing_time)
    except ValueError as error:
        raise MarketDataCheckpointError("checkpoint processing time is invalid") from error
    if parsed_processing_time.tzinfo is None or parsed_processing_time.utcoffset() is None:
        raise MarketDataCheckpointError("checkpoint processing time is invalid")
    start_date = _validate_date(payload["start_date"], "start_date")
    end_date = _validate_date(payload["end_date"], "end_date")
    if end_date < start_date:
        raise MarketDataCheckpointError("checkpoint request date range is invalid")
    return InFlightRequest(
        kind=kind,
        trading_date=_validate_date(payload["trading_date"], "trading_date"),
        unified_code=_validate_symbol(payload["unified_code"]),
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        capture_ordinal=ordinal,
        processing_time=parsed_processing_time.astimezone(UTC),
    )


def _validated_checkpoint(raw: Mapping[str, object]) -> MarketDataCheckpoint:
    expected = {
        "version",
        "run_id",
        "next_capture_ordinal",
        "daily_trading_date",
        "daily_completed_symbols",
        "in_flight",
    }
    if set(raw) != expected or raw.get("version") != CHECKPOINT_VERSION:
        raise MarketDataCheckpointError("checkpoint is corrupt or unsupported")
    ordinal = raw.get("next_capture_ordinal")
    if type(ordinal) is not int or ordinal < 1:
        raise MarketDataCheckpointError("checkpoint next capture ordinal is invalid")
    daily_date = raw.get("daily_trading_date")
    if daily_date is not None:
        daily_date = _validate_date(daily_date, "daily_trading_date")
    completed = raw.get("daily_completed_symbols")
    if not isinstance(completed, list):
        raise MarketDataCheckpointError("checkpoint daily symbols are invalid")
    completed_values = cast(list[object], completed)
    if any(not isinstance(item, str) for item in completed_values):
        raise MarketDataCheckpointError("checkpoint daily symbols are invalid")
    completed_symbols = tuple(_validate_symbol(item) for item in completed_values)
    if len(set(completed_symbols)) != len(completed_symbols):
        raise MarketDataCheckpointError("checkpoint daily symbols are invalid")
    in_flight_raw = raw.get("in_flight")
    in_flight = None if in_flight_raw is None else _validate_request(in_flight_raw)
    if in_flight is not None and in_flight.capture_ordinal != ordinal:
        raise MarketDataCheckpointError("checkpoint in-flight ordinal is inconsistent")
    if daily_date is None and completed_symbols:
        raise MarketDataCheckpointError("checkpoint daily symbols lack a date")
    return MarketDataCheckpoint(
        run_id=_validate_run_id(raw.get("run_id")),
        next_capture_ordinal=ordinal,
        daily_trading_date=daily_date,
        daily_completed_symbols=completed_symbols,
        in_flight=in_flight,
    )


def _acquire_os_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_os_lock(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class MarketDataCheckpointStore:
    """Persist checkpoint JSON using an OS lock and atomic replacement."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / CHECKPOINT_FILENAME
        self._lock_path = self.root / _LOCK_FILENAME

    @contextmanager
    def locked(self) -> Generator[None, None, None]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as error:
            raise MarketDataCheckpointError("unable to open market-data checkpoint lock") from error
        handle: BinaryIO = os.fdopen(descriptor, "r+b", closefd=True)
        acquired = False
        try:
            # Windows supports locking beyond EOF; writing an empty marker
            # before ownership can race with another handle's byte lock.
            handle.seek(0)
            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while not acquired:
                try:
                    _acquire_os_lock(handle)
                    acquired = True
                except OSError as error:
                    if error.errno not in {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES}:
                        raise MarketDataCheckpointError(
                            "market-data checkpoint lock failed"
                        ) from error
                    if time.monotonic() >= deadline:
                        raise MarketDataCheckpointBusyError(
                            "market-data checkpoint is locked by another process"
                        ) from error
                    time.sleep(_LOCK_POLL_SECONDS)
            yield
        finally:
            if acquired:
                with suppress(OSError):
                    _release_os_lock(handle)
            handle.close()

    def load_or_create(self, requested_run_id: str | None = None) -> MarketDataCheckpoint:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise MarketDataCheckpointError("market-data checkpoint is corrupt") from error
            if not isinstance(raw, dict):
                raise MarketDataCheckpointError("market-data checkpoint is corrupt")
            checkpoint = _validated_checkpoint(cast(Mapping[str, object], raw))
            if requested_run_id is not None and requested_run_id != checkpoint.run_id:
                raise MarketDataCheckpointError("requested run does not own checkpoint")
            return checkpoint

        run_id = _validate_run_id(requested_run_id or f"market-{uuid4().hex}")
        checkpoint = MarketDataCheckpoint(run_id=run_id, next_capture_ordinal=1)
        self.save(checkpoint)
        return checkpoint

    def save(self, checkpoint: MarketDataCheckpoint) -> None:
        validated = _validated_checkpoint(checkpoint.to_dict())
        payload = json.dumps(
            validated.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        temporary_path: Path | None = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.root,
                prefix=".market-data-checkpoint-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            assert temporary_path is not None
            os.replace(temporary_path, self.path)
            if os.name != "nt":
                try:
                    directory = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                except OSError:
                    pass
        except OSError as error:
            raise MarketDataCheckpointError("unable to publish market-data checkpoint") from error
        finally:
            if temporary_path is not None:
                with suppress(FileNotFoundError):
                    temporary_path.unlink()


__all__ = [
    "CHECKPOINT_FILENAME",
    "CHECKPOINT_VERSION",
    "InFlightRequest",
    "MarketDataCheckpoint",
    "MarketDataCheckpointError",
    "MarketDataCheckpointStore",
]
