"""One-shot composition root for the fixed SZSE 2026 calendar run.

The collector is the only component allowed to capture official responses.  A
successful collection returns raw coordinates, and the V4 repository replays
those coordinates before opening its transaction.  The CLI deliberately does
not expose provider URLs, years, exchanges, migrations, or a scheduler.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn, Protocol, TypeVar
from uuid import UUID

import psycopg
from data_worker.jobs.calendars.official_calendar_repository import (
    OfficialCalendarPersistenceError,
    OfficialCalendarPersistResult,
    PostgresOfficialCalendarRepository,
)
from data_worker.jobs.calendars.official_szse_daily import (
    OfficialSzseCalendarError,
    OfficialSzseTransport,
    SzseOfficialCalendarCollector,
)
from data_worker.raw import LocalFileStorage, RawObjectManifest, RawStorage
from data_worker.raw.manifest import validate_date_identifier, validate_identifier

_RAW_ROOT_ENV = "KUNLUN_RAW_ROOT"
_DSN_ENV = "KUNLUN_POSTGRES_DSN"
_SCHEMA_ENV = "KUNLUN_POSTGRES_SCHEMA"
_DEFAULT_SCHEMA = "kunlun"
_DB_CONNECT_TIMEOUT_SECONDS = 10

_CLI_ERROR = "official SZSE calendar CLI failed"
_DB_ERROR = "official SZSE calendar database is unavailable"
_RAW_ROOT_ERROR = "official SZSE calendar raw root is invalid"
_REPLAY_ARGUMENT_ERROR = "official SZSE calendar replay arguments are invalid"
_RESULT_ERROR = "official SZSE calendar result is invalid"
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$", re.ASCII)

_DISPOSITIONS = frozenset(
    {"SNAPSHOT_CREATED", "DUPLICATE", "OUT_OF_ORDER_BLOCKED", "CONFLICT_HEAD"}
)
_TERMINALS = frozenset({"COMPLETE", "INDETERMINATE"})
_COVERAGE_LEVELS = frozenset({"FINAL_YEAR", "CONFIRMED_HORIZON", "INDETERMINATE"})
_RUN_DISPOSITIONS = frozenset({"CONFIRMED", "DUPLICATE", "OUT_OF_ORDER", "CONFLICT"})
_CLI_ERROR_MESSAGES = frozenset(
    {
        _CLI_ERROR,
        _DB_ERROR,
        _RAW_ROOT_ERROR,
        _REPLAY_ARGUMENT_ERROR,
        _RESULT_ERROR,
    }
)


def _raise_raw_root_error() -> NoReturn:
    raise OfficialSzseCalendarError(_RAW_ROOT_ERROR)


def _directory_stat(path: Path) -> os.stat_result:
    """Return a trusted, non-symlink directory stat for one path component."""

    try:
        info = os.lstat(path)
    except (OSError, ValueError):
        _raise_raw_root_error()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _raise_raw_root_error()
    if os.name != "nt":
        current_uid = os.getuid() if hasattr(os, "getuid") else info.st_uid
        if info.st_uid not in {0, current_uid}:
            _raise_raw_root_error()
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            _raise_raw_root_error()
    return info


def _directory_identity(path: Path) -> tuple[int, int]:
    info = _directory_stat(path)
    return info.st_dev, info.st_ino


def _open_directory_capability(path: Path) -> int | None:
    """Keep an open directory capability where the platform exposes one."""

    if os.name == "nt":
        return None
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError:
        _raise_raw_root_error()


@dataclass(slots=True)
class _RawRootGuard:
    """Track raw-root and immediate-parent identity for one CLI lifetime."""

    root: Path
    root_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    root_fd: int | None
    parent_fd: int | None
    _closed: bool = False

    @classmethod
    def open(cls, root: Path) -> _RawRootGuard:
        """Open directory capabilities after validating both path components."""

        checked_root = _validated_raw_root(os.fspath(root))
        parent = checked_root.parent
        root_identity = _directory_identity(checked_root)
        parent_identity = _directory_identity(parent)
        root_fd: int | None = None
        parent_fd: int | None = None
        try:
            parent_fd = _open_directory_capability(parent)
            root_fd = _open_directory_capability(checked_root)
            guard = cls(
                root=checked_root,
                root_identity=root_identity,
                parent_identity=parent_identity,
                root_fd=root_fd,
                parent_fd=parent_fd,
            )
            guard.assert_stable()
            return guard
        except OfficialSzseCalendarError:
            if root_fd is not None:
                with suppress(BaseException):
                    os.close(root_fd)
            if parent_fd is not None:
                with suppress(BaseException):
                    os.close(parent_fd)
            raise
        except Exception:
            if root_fd is not None:
                with suppress(BaseException):
                    os.close(root_fd)
            if parent_fd is not None:
                with suppress(BaseException):
                    os.close(parent_fd)
            raise OfficialSzseCalendarError(_RAW_ROOT_ERROR) from None
        except BaseException:
            if root_fd is not None:
                with suppress(BaseException):
                    os.close(root_fd)
            if parent_fd is not None:
                with suppress(BaseException):
                    os.close(parent_fd)
            raise

    def assert_stable(self) -> None:
        """Fail closed if either path component changed or lost its capability."""

        if self._closed:
            _raise_raw_root_error()
        try:
            if _directory_identity(self.root) != self.root_identity:
                _raise_raw_root_error()
            if _directory_identity(self.root.parent) != self.parent_identity:
                _raise_raw_root_error()
            if self.root_fd is not None:
                root_info = os.fstat(self.root_fd)
                if (
                    not stat.S_ISDIR(root_info.st_mode)
                    or (root_info.st_dev, root_info.st_ino) != self.root_identity
                ):
                    _raise_raw_root_error()
            if self.parent_fd is not None:
                parent_info = os.fstat(self.parent_fd)
                if (
                    not stat.S_ISDIR(parent_info.st_mode)
                    or (parent_info.st_dev, parent_info.st_ino) != self.parent_identity
                ):
                    _raise_raw_root_error()
        except OfficialSzseCalendarError:
            raise
        except (OSError, ValueError):
            _raise_raw_root_error()

    def close(self) -> None:
        """Close capabilities and surface cleanup failures as fixed errors."""

        if self._closed:
            return
        close_failed = False
        for descriptor in (self.root_fd, self.parent_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException:
                close_failed = True
        self._closed = True
        if close_failed:
            _raise_raw_root_error()


_GuardedResult = TypeVar("_GuardedResult")


class _GuardedRawStorage(RawStorage):
    """Check the raw-root capability around every raw storage operation."""

    def __init__(self, storage: RawStorage, guard: _RawRootGuard) -> None:
        self._storage = storage
        self._guard = guard

    def _call(
        self,
        operation: Callable[..., _GuardedResult],
        *args: object,
        **kwargs: object,
    ) -> _GuardedResult:
        self._guard.assert_stable()
        try:
            return operation(*args, **kwargs)
        finally:
            self._guard.assert_stable()

    def put(
        self,
        source: str,
        date: str,
        request: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        *,
        capture_id: str | None = None,
        idempotency_key: str | None = None,
        ingest_time: datetime | None = None,
        available_time: datetime | None = None,
        endpoint_kind: str | None = None,
        run_id: str | None = None,
        source_revision: str | None = None,
        source_revision_absent: bool = False,
        attempt_id: str | None = None,
        page_ordinal: int | None = None,
        schema_version: str | None = None,
        capture_version: str | None = None,
        api_name: str | None = None,
        unified_code: str | None = None,
        interval: str | None = None,
        requested_start: str | None = None,
        requested_end: str | None = None,
        source_version: str | None = None,
        market_run_id: str | None = None,
        capture_ordinal: int | None = None,
    ) -> RawObjectManifest:
        return self._call(
            self._storage.put,
            source,
            date,
            request,
            content,
            content_type,
            capture_id=capture_id,
            idempotency_key=idempotency_key,
            ingest_time=ingest_time,
            available_time=available_time,
            endpoint_kind=endpoint_kind,
            run_id=run_id,
            source_revision=source_revision,
            source_revision_absent=source_revision_absent,
            attempt_id=attempt_id,
            page_ordinal=page_ordinal,
            schema_version=schema_version,
            capture_version=capture_version,
            api_name=api_name,
            unified_code=unified_code,
            interval=interval,
            requested_start=requested_start,
            requested_end=requested_end,
            source_version=source_version,
            market_run_id=market_run_id,
            capture_ordinal=capture_ordinal,
        )

    def get(
        self,
        object_id: str,
        *,
        checksum: str | None = None,
        size: int | None = None,
    ) -> bytes:
        return self._call(self._storage.get, object_id, checksum=checksum, size=size)

    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        return self._call(self._storage.list, source, date)

    def find_capture(
        self,
        *,
        market_run_id: str,
        capture_ordinal: int,
    ) -> RawObjectManifest | None:
        return self._call(
            self._storage.find_capture,
            market_run_id=market_run_id,
            capture_ordinal=capture_ordinal,
        )


class _SzsePersistenceRepository(Protocol):
    """The narrow V4 write boundary used by the composition root."""

    def persist_authoritative_szse_run(
        self,
        raw_storage: RawStorage,
        run_id: UUID,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> OfficialCalendarPersistResult: ...


class _Closeable(Protocol):
    """Connection surface needed by the runtime for deterministic cleanup."""

    def close(self) -> None: ...


def _persist_with_guard(
    *,
    raw_storage: RawStorage,
    repository: _SzsePersistenceRepository,
    run_id: UUID,
    manifest_date: str,
    manifest_capture_id: str,
    raw_guard: _RawRootGuard | None,
) -> OfficialCalendarPersistResult:
    """Persist one run while checking the raw-root guard on both boundaries."""

    if raw_guard is not None:
        raw_guard.assert_stable()
    try:
        return repository.persist_authoritative_szse_run(
            raw_storage,
            run_id,
            manifest_date,
            manifest_capture_id,
        )
    finally:
        if raw_guard is not None:
            raw_guard.assert_stable()


def _validate_replay_coordinates(
    run_id: object,
    manifest_date: object,
    manifest_capture_id: object,
) -> tuple[UUID, str, str]:
    """Validate the only coordinates accepted by offline replay."""

    if type(run_id) is not UUID:
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
    if type(manifest_date) is not str or type(manifest_capture_id) is not str:
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
    try:
        normalized_date = validate_date_identifier(manifest_date)
        if date.fromisoformat(normalized_date).isoformat() != normalized_date:
            raise ValueError
        normalized_capture_id = validate_identifier(
            manifest_capture_id, "manifest_capture_id", max_length=48
        )
    except (TypeError, ValueError):
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR) from None
    return run_id, normalized_date, normalized_capture_id


def run_official_szse_once(
    *,
    raw_storage: RawStorage,
    repository: _SzsePersistenceRepository,
    replay: bool = False,
    run_id: UUID | None = None,
    manifest_date: str | None = None,
    manifest_capture_id: str | None = None,
    transport: OfficialSzseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
    raw_guard: _RawRootGuard | None = None,
) -> OfficialCalendarPersistResult:
    """Collect or replay exactly one fixed SZSE 2026 run.

    Collection and persistence are intentionally two separate boundaries: the
    collector writes raw evidence first, while the repository accepts only the
    returned coordinates and performs its own raw replay.  In replay mode no
    collector is constructed, so the injected transport cannot be used.
    """

    if type(replay) is not bool:
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
    if raw_guard is not None:
        raw_guard.assert_stable()
    coordinates = (run_id, manifest_date, manifest_capture_id)
    has_coordinates = any(value is not None for value in coordinates)
    if replay:
        if not all(value is not None for value in coordinates):
            raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
        checked_run_id, checked_date, checked_capture_id = _validate_replay_coordinates(
            run_id, manifest_date, manifest_capture_id
        )
        return _persist_with_guard(
            raw_storage=raw_storage,
            repository=repository,
            run_id=checked_run_id,
            manifest_date=checked_date,
            manifest_capture_id=checked_capture_id,
            raw_guard=raw_guard,
        )
    if has_coordinates:
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)

    collector = SzseOfficialCalendarCollector(
        raw_storage,
        transport=transport,
        clock=clock,
    )
    try:
        collected = collector.collect(exchange="SZ", year=2026)
    finally:
        if raw_guard is not None:
            raw_guard.assert_stable()
    try:
        collected_run_id = collected.run_id
        manifest_reference = collected.raw_manifest_ref
        collected_manifest_date = manifest_reference.raw_date
        collected_capture_id = manifest_reference.capture_id
    except Exception:
        raise OfficialSzseCalendarError(_CLI_ERROR) from None
    return _persist_with_guard(
        raw_storage=raw_storage,
        repository=repository,
        run_id=collected_run_id,
        manifest_date=collected_manifest_date,
        manifest_capture_id=collected_capture_id,
        raw_guard=raw_guard,
    )


def _validated_raw_root(value: object) -> Path:
    """Return an absolute, existing raw-root path after security checks."""

    if type(value) is not str or not value or value != value.strip():
        raise OfficialSzseCalendarError(_RAW_ROOT_ERROR)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise OfficialSzseCalendarError(_RAW_ROOT_ERROR)
    try:
        path = Path(value)
        if not path.is_absolute() or path == Path(path.anchor):
            raise ValueError
        _directory_stat(path)
        _directory_stat(path.parent)
    except (OSError, RuntimeError, ValueError):
        raise OfficialSzseCalendarError(_RAW_ROOT_ERROR) from None
    return path


def _open_repository(dsn: object, schema: object) -> tuple[_Closeable, _SzsePersistenceRepository]:
    """Open the V4 repository with bounded connection setup and fixed errors."""

    if type(dsn) is not str or not dsn.strip():
        raise OfficialSzseCalendarError(_DB_ERROR)
    if type(schema) is not str or _SCHEMA_RE.fullmatch(schema) is None:
        raise OfficialSzseCalendarError(_DB_ERROR)

    connection: _Closeable | None = None
    try:
        connection = psycopg.connect(
            dsn,
            options=f'-c search_path="{schema}"',
            connect_timeout=_DB_CONNECT_TIMEOUT_SECONDS,
        )
        repository = PostgresOfficialCalendarRepository(connection)
    except Exception:
        if connection is not None:
            with suppress(BaseException):
                connection.close()
        raise OfficialSzseCalendarError(_DB_ERROR) from None
    except BaseException:
        if connection is not None:
            with suppress(BaseException):
                connection.close()
        raise
    return connection, repository


class _SafeArgumentParser(argparse.ArgumentParser):
    """Argparse parser that never reflects raw user input in diagnostics."""

    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {_REPLAY_ARGUMENT_ERROR}\n")


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = _SafeArgumentParser(
        prog="official-szse-daily-sync",
        description="Run the fixed SZSE SZ 2026 official calendar capture or replay",
    )
    parser.add_argument("--raw-root", default=os.environ.get(_RAW_ROOT_ENV))
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--manifest-date")
    parser.add_argument("--manifest-capture-id")
    return parser.parse_args(argv)


def _parse_run_id(value: object) -> UUID:
    if type(value) is not str or not value:
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
    try:
        return UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR) from None


def _safe_payload(result: OfficialCalendarPersistResult) -> str:
    """Serialize only the fixed, non-sensitive V4 outcome fields."""

    if type(result) is not OfficialCalendarPersistResult:
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if type(result.run_id) is not UUID:
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if result.snapshot_id is not None and type(result.snapshot_id) is not UUID:
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if (
        type(result.disposition) is not str
        or result.disposition not in _DISPOSITIONS
        or type(result.terminal) is not str
        or result.terminal not in _TERMINALS
        or type(result.coverage_level) is not str
        or result.coverage_level not in _COVERAGE_LEVELS
        or type(result.run_disposition) is not str
        or result.run_disposition not in _RUN_DISPOSITIONS
    ):
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if result.snapshot_id is None and result.terminal != "INDETERMINATE":
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if result.terminal == "COMPLETE" and (
        result.snapshot_id is None or result.coverage_level != "FINAL_YEAR"
    ):
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if (
        result.snapshot_id is not None
        and result.terminal == "INDETERMINATE"
        and result.coverage_level == "FINAL_YEAR"
    ):
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    if result.disposition == "SNAPSHOT_CREATED":
        if result.snapshot_id is None or result.run_disposition != "CONFIRMED":
            raise OfficialSzseCalendarError(_RESULT_ERROR)
    elif result.disposition == "OUT_OF_ORDER_BLOCKED":
        if (
            result.snapshot_id is not None
            or result.terminal != "INDETERMINATE"
            or result.run_disposition != "OUT_OF_ORDER"
        ):
            raise OfficialSzseCalendarError(_RESULT_ERROR)
    elif result.disposition == "CONFLICT_HEAD" and (
        result.snapshot_id is not None
        or result.terminal != "INDETERMINATE"
        or result.run_disposition != "CONFLICT"
    ):
        raise OfficialSzseCalendarError(_RESULT_ERROR)
    payload = {
        "run_id": str(result.run_id),
        "snapshot_id": None if result.snapshot_id is None else str(result.snapshot_id),
        "disposition": result.disposition,
        "terminal": result.terminal,
        "coverage_level": result.coverage_level,
        "run_disposition": result.run_disposition,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _map_cli_error(error: OfficialSzseCalendarError) -> str:
    message = str(error)
    return message if message in _CLI_ERROR_MESSAGES else _CLI_ERROR


def _close_resources(
    connection: _Closeable | None,
    guard: _RawRootGuard | None,
) -> tuple[str | None, BaseException | None]:
    """Close both resources while retaining fixed and origin error signals."""

    failure: str | None = None
    base_exception: BaseException | None = None
    if connection is not None:
        try:
            connection.close()
        except BaseException as error:
            if isinstance(error, Exception):
                failure = _DB_ERROR
            else:
                base_exception = error
    if guard is not None:
        try:
            guard.close()
        except BaseException as error:
            if isinstance(error, Exception):
                if failure is None:
                    failure = _RAW_ROOT_ERROR
            elif base_exception is None:
                base_exception = error
    return failure, base_exception


def main(argv: Sequence[str] | None = None) -> int:
    """Run one fixed SZSE collect/replay and close the DB connection."""

    connection: _Closeable | None = None
    guard: _RawRootGuard | None = None
    result: OfficialCalendarPersistResult | None = None
    failure: str | None = None
    cleanup_failure: str | None = None
    cleanup_base_exception: BaseException | None = None
    try:
        args = _arguments(argv)
        raw_root = _validated_raw_root(args.raw_root)
        guard = _RawRootGuard.open(raw_root)
        coordinates = (args.run_id, args.manifest_date, args.manifest_capture_id)
        if args.replay:
            if not all(value is not None for value in coordinates):
                raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
            parsed_run_id = _parse_run_id(args.run_id)
            parsed_run_id, parsed_date, parsed_capture_id = _validate_replay_coordinates(
                parsed_run_id, args.manifest_date, args.manifest_capture_id
            )
        elif any(value is not None for value in coordinates):
            raise OfficialSzseCalendarError(_REPLAY_ARGUMENT_ERROR)
        else:
            parsed_run_id = None
            parsed_date = None
            parsed_capture_id = None

        raw_storage = _GuardedRawStorage(LocalFileStorage(raw_root), guard)
        guard.assert_stable()
        connection, repository = _open_repository(
            os.environ.get(_DSN_ENV, ""),
            os.environ.get(_SCHEMA_ENV, _DEFAULT_SCHEMA),
        )
        result = run_official_szse_once(
            raw_storage=raw_storage,
            repository=repository,
            replay=args.replay,
            run_id=parsed_run_id,
            manifest_date=parsed_date,
            manifest_capture_id=parsed_capture_id,
            raw_guard=guard,
        )
    except OfficialSzseCalendarError as error:
        failure = _map_cli_error(error)
    except OfficialCalendarPersistenceError:
        failure = _DB_ERROR
    except Exception:
        failure = _CLI_ERROR
    finally:
        cleanup_failure, cleanup_base_exception = _close_resources(connection, guard)

    if cleanup_base_exception is not None and failure is None:
        raise cleanup_base_exception
    if cleanup_failure is not None:
        failure = cleanup_failure

    if failure is not None:
        print(failure, file=sys.stderr)
        return 1
    if result is None:
        print(_CLI_ERROR, file=sys.stderr)
        return 1
    try:
        payload = _safe_payload(result)
    except OfficialSzseCalendarError as error:
        print(_map_cli_error(error), file=sys.stderr)
        return 1
    except Exception:
        print(_CLI_ERROR, file=sys.stderr)
        return 1
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_official_szse_once"]
