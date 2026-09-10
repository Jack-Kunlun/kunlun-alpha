"""One-shot Tushare instrument-master collect/replay runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeVar
from uuid import UUID

from data_worker.jobs.instruments.postgres_repository import (
    InstrumentMasterPersistResult,
    PostgresInstrumentMasterRepository,
)
from data_worker.jobs.instruments.tushare_master import (
    TushareInstrumentCollector,
    TushareInstrumentConfig,
)
from data_worker.raw import LocalFileStorage, RawObjectManifest, RawStorage
from data_worker.storage.migrations import (
    INSTRUMENT_MASTER_PROVIDER_SCHEMA,
    apply_instrument_master_provider_migration,
)

_RAW_ROOT_ENV = "KUNLUN_RAW_ROOT"
_DSN_ENV = "INSTRUMENT_MASTER_RUNTIME_DSN"
_DSN_FILE_ENV = "INSTRUMENT_MASTER_RUNTIME_DSN_FILE"
_MIGRATOR_DSN_ENV = "INSTRUMENT_MASTER_MIGRATOR_DSN"
_MIGRATOR_DSN_FILE_ENV = "INSTRUMENT_MASTER_MIGRATOR_DSN_FILE"
_TOKEN_ENV = "TUSHARE_TOKEN"
_DEFAULT_SCHEMA = INSTRUMENT_MASTER_PROVIDER_SCHEMA
_MAX_DSN_FILE_BYTES = 4096
_SAFE_ERROR = "instrument master sync failed"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.exit(2, "argument error\n")


class _InstrumentMasterRepository(Protocol):
    def persist_authoritative_instrument_master_run(
        self,
        raw_storage: RawStorage,
        run_id: str,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> InstrumentMasterPersistResult: ...


def _trusted_directory(path: Path) -> os.stat_result:
    try:
        info = os.lstat(path)
    except (OSError, ValueError):
        raise ValueError("raw root is not a trusted directory") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("raw root is not a trusted directory")
    if os.name != "nt":
        current_uid = os.getuid() if hasattr(os, "getuid") else info.st_uid
        if info.st_uid not in {0, current_uid}:
            raise ValueError("raw root owner is invalid")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("raw root permissions are unsafe")
    return info


def _directory_identity(path: Path) -> tuple[int, int]:
    info = _trusted_directory(path)
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
        raise ValueError("raw root is not a trusted directory") from None


@dataclass(slots=True)
class _RawRootGuard:
    root: Path
    root_identity: tuple[int, int]
    parent_identity: tuple[int, int]
    root_fd: int | None
    parent_fd: int | None
    _closed: bool = False

    @classmethod
    def open(cls, root: Path) -> _RawRootGuard:
        _trusted_directory(root)
        _trusted_directory(root.parent)
        root_identity = _directory_identity(root)
        parent_identity = _directory_identity(root.parent)
        root_fd: int | None = None
        parent_fd: int | None = None
        try:
            parent_fd = _open_directory_capability(root.parent)
            root_fd = _open_directory_capability(root)
            guard = cls(
                root,
                root_identity,
                parent_identity,
                root_fd,
                parent_fd,
            )
            guard.assert_stable()
            return guard
        except BaseException:
            if root_fd is not None:
                with suppress(BaseException):
                    os.close(root_fd)
            if parent_fd is not None:
                with suppress(BaseException):
                    os.close(parent_fd)
            raise

    def assert_stable(self) -> None:
        if self._closed:
            raise ValueError("raw root is not a trusted directory")
        _trusted_directory(self.root)
        _trusted_directory(self.root.parent)
        if (
            _directory_identity(self.root) != self.root_identity
            or _directory_identity(self.root.parent) != self.parent_identity
        ):
            raise ValueError("raw root was replaced")
        if self.root_fd is not None:
            root_info = os.fstat(self.root_fd)
            if (
                not stat.S_ISDIR(root_info.st_mode)
                or (root_info.st_dev, root_info.st_ino) != self.root_identity
            ):
                raise ValueError("raw root was replaced")
        if self.parent_fd is not None:
            parent_info = os.fstat(self.parent_fd)
            if (
                not stat.S_ISDIR(parent_info.st_mode)
                or (parent_info.st_dev, parent_info.st_ino) != self.parent_identity
            ):
                raise ValueError("raw root was replaced")

    def close(self) -> None:
        if self._closed:
            return
        ordinary_failure = False
        base_exception: BaseException | None = None
        for descriptor in (self.root_fd, self.parent_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException as error:
                if isinstance(error, Exception):
                    ordinary_failure = True
                elif base_exception is None:
                    base_exception = error
        self._closed = True
        if base_exception is not None:
            raise base_exception
        if ordinary_failure:
            raise ValueError("raw root is not a trusted directory")


_GuardedResult = TypeVar("_GuardedResult")


class _GuardedRawStorage(RawStorage):
    """Check raw-root identity around every raw storage operation."""

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
            result = operation(*args, **kwargs)
        except BaseException:
            # The operation's exception is the authoritative work-phase
            # outcome.  A second capability check is still attempted, but it
            # must never mask KeyboardInterrupt/SystemExit/custom signals (or
            # the original ordinary operation error).
            with suppress(BaseException):
                self._guard.assert_stable()
            raise
        self._guard.assert_stable()
        return result

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


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="instrument-master-sync")
    parser.add_argument("--raw-root", dest="raw_root")
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--manifest-date")
    parser.add_argument("--manifest-capture-id")
    return parser


def _raw_root(value: str | None, environ: Mapping[str, str]) -> Path:
    candidate = (value if value is not None else environ.get(_RAW_ROOT_ENV, "")).strip()
    if not candidate:
        raise ValueError("raw root is required")
    path = Path(candidate)
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError("raw root must be an absolute directory")
    _trusted_directory(path)
    _trusted_directory(path.parent)
    return path


def _schema(environ: Mapping[str, str]) -> str:
    del environ
    return _DEFAULT_SCHEMA


def _required(value: str | None, field_name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _dedicated_dsn(environ: Mapping[str, str], direct_name: str, file_name_key: str) -> str:
    direct = environ.get(direct_name)
    file_name = environ.get(file_name_key)
    if direct is not None and direct.strip() and file_name is not None and file_name.strip():
        raise ValueError("database DSN configuration is ambiguous")
    if direct is not None and direct.strip():
        return direct.strip()
    if file_name is None or not file_name.strip():
        raise ValueError("database DSN is required")

    path = Path(file_name.strip())
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError("database DSN file is invalid")
    try:
        info = os.lstat(path)
        parent_info = os.lstat(path.parent)
    except (OSError, ValueError):
        raise ValueError("database DSN file is invalid") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("database DSN file is invalid")
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise ValueError("database DSN file is invalid")
    if os.name != "nt":
        current_uid = os.getuid() if hasattr(os, "getuid") else info.st_uid
        if info.st_uid not in {0, current_uid} or parent_info.st_uid not in {0, current_uid}:
            raise ValueError("database DSN file ownership is invalid")
        unsafe_mode = stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH
        if info.st_mode & unsafe_mode or parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("database DSN file permissions are unsafe")

    flags = os.O_RDONLY
    if os.name != "nt":
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise ValueError("database DSN file was replaced")
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as stream:
            descriptor = None
            content = stream.read(_MAX_DSN_FILE_BYTES + 1)
    except (OSError, UnicodeError, ValueError):
        raise ValueError("database DSN file is invalid") from None
    finally:
        if descriptor is not None:
            with suppress(BaseException):
                os.close(descriptor)
    if len(content) > _MAX_DSN_FILE_BYTES:
        raise ValueError("database DSN file is invalid")
    return _required(content, "database DSN")


def _runtime_dsn(environ: Mapping[str, str]) -> str:
    return _dedicated_dsn(environ, _DSN_ENV, _DSN_FILE_ENV)


def _migrator_dsn(environ: Mapping[str, str]) -> str:
    return _dedicated_dsn(environ, _MIGRATOR_DSN_ENV, _MIGRATOR_DSN_FILE_ENV)


def _replay_coordinates(
    run_id: str | None,
    manifest_date: str | None,
    manifest_capture_id: str | None,
) -> tuple[str, str, str]:
    checked_run_id = _required(run_id, "run_id")
    checked_date = _required(manifest_date, "manifest_date")
    checked_capture_id = _required(manifest_capture_id, "manifest_capture_id")
    try:
        parsed_run_id = UUID(checked_run_id)
        parsed_date = date.fromisoformat(checked_date)
    except ValueError:
        raise ValueError("replay coordinates are invalid") from None
    if parsed_date.isoformat() != checked_date:
        raise ValueError("replay coordinates are invalid")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", checked_capture_id) is None:
        raise ValueError("replay coordinates are invalid")
    return str(parsed_run_id), parsed_date.isoformat(), checked_capture_id


def run_instrument_master_once(
    *,
    raw_storage: RawStorage,
    repository: _InstrumentMasterRepository,
    collector: TushareInstrumentCollector | None = None,
    replay: bool = False,
    run_id: str | None = None,
    manifest_date: str | None = None,
    manifest_capture_id: str | None = None,
    raw_guard: _RawRootGuard | None = None,
) -> InstrumentMasterPersistResult:
    """Compose collect or offline replay with raw coordinates only.

    In collect mode, the collector writes raw evidence first and the
    repository receives only the returned coordinates.  Replay mode does not
    construct a collector or a provider transport.
    """

    if raw_guard is not None:
        raw_guard.assert_stable()
    try:
        if replay:
            replay_run_id, replay_date, replay_capture = _replay_coordinates(
                run_id, manifest_date, manifest_capture_id
            )
            result = repository.persist_authoritative_instrument_master_run(
                raw_storage,
                run_id=replay_run_id,
                manifest_date=replay_date,
                manifest_capture_id=replay_capture,
            )
        else:
            if any(value is not None for value in (run_id, manifest_date, manifest_capture_id)):
                raise ValueError("replay coordinates are only valid with --replay")
            if collector is None:
                raise ValueError("collector is required for collect")
            collected = collector.collect()
            result = repository.persist_authoritative_instrument_master_run(
                raw_storage,
                run_id=collected.run_id,
                manifest_date=collected.manifest_date,
                manifest_capture_id=collected.manifest_capture_id,
            )
    except BaseException:
        if raw_guard is not None:
            with suppress(BaseException):
                raw_guard.assert_stable()
        raise
    if raw_guard is not None:
        raw_guard.assert_stable()
    return result


def _safe_output(result: InstrumentMasterPersistResult) -> str:
    payload = {
        "run_id": str(result.run_id),
        "snapshot_id": None if result.snapshot_id is None else str(result.snapshot_id),
        "disposition": result.disposition,
        "terminal": result.terminal,
        "coverage_level": result.completeness,
        "run_disposition": result.run_disposition,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _connection(dsn: str, schema: str) -> Any:
    if not dsn.strip():
        raise ValueError("database DSN is required")
    if schema != _DEFAULT_SCHEMA:
        raise ValueError("database schema is invalid")
    import psycopg

    return psycopg.connect(
        dsn,
        connect_timeout=8,
        options=f'-c search_path="{schema}"',
    )


def _close_resources(
    connection: Any | None,
    guard: _RawRootGuard | None,
) -> tuple[str | None, BaseException | None]:
    """Close all capabilities before emitting success output."""

    failure: str | None = None
    base_exception: BaseException | None = None
    if connection is not None:
        try:
            close = getattr(connection, "close", None)
            if not callable(close):
                failure = _SAFE_ERROR
            else:
                close()
        except BaseException as error:
            if isinstance(error, Exception):
                failure = _SAFE_ERROR
            else:
                base_exception = error
    if guard is not None:
        try:
            guard.close()
        except BaseException as error:
            if isinstance(error, Exception):
                if failure is None:
                    failure = _SAFE_ERROR
            elif base_exception is None:
                base_exception = error
    return failure, base_exception


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    connection_factory: Callable[[str, str], Any] = _connection,
) -> int:
    """Run one bounded sync and return a process exit code."""

    env = os.environ if environ is None else environ
    parser = _parser()
    connection: Any | None = None
    guard: _RawRootGuard | None = None
    result: InstrumentMasterPersistResult | None = None
    failure: str | None = None
    cleanup_failure: str | None = None
    cleanup_base_exception: BaseException | None = None
    try:
        args = parser.parse_args(argv)
        raw_root = _raw_root(args.raw_root, env)
        guard = _RawRootGuard.open(raw_root)
        schema = _schema(env)
        if args.replay:
            if (
                args.run_id is None
                or args.manifest_date is None
                or args.manifest_capture_id is None
            ):
                raise ValueError("replay requires run_id, manifest_date and manifest_capture_id")
        elif any(
            value is not None
            for value in (args.run_id, args.manifest_date, args.manifest_capture_id)
        ):
            raise ValueError("replay coordinates require --replay")
        raw_storage = _GuardedRawStorage(LocalFileStorage(raw_root), guard)
        connection = connection_factory(_runtime_dsn(env), schema)
        if connection is None:
            raise RuntimeError("database connection cannot be opened")
        repository = PostgresInstrumentMasterRepository(connection, schema=schema)
        if args.replay:
            result = run_instrument_master_once(
                raw_storage=raw_storage,
                repository=repository,
                replay=True,
                run_id=args.run_id,
                manifest_date=args.manifest_date,
                manifest_capture_id=args.manifest_capture_id,
                raw_guard=guard,
            )
        else:
            token = _required(env.get(_TOKEN_ENV), _TOKEN_ENV)
            collector = TushareInstrumentCollector(
                TushareInstrumentConfig(
                    token=token,
                ),
                raw_storage,
            )
            result = run_instrument_master_once(
                raw_storage=raw_storage,
                repository=repository,
                collector=collector,
                raw_guard=guard,
            )
    except SystemExit:
        raise
    except Exception:
        failure = _SAFE_ERROR

    finally:
        cleanup_failure, cleanup_base_exception = _close_resources(connection, guard)

    if cleanup_base_exception is not None and failure is None:
        raise cleanup_base_exception
    if cleanup_failure is not None:
        failure = cleanup_failure
    if failure is not None or result is None:
        print(failure or _SAFE_ERROR, file=sys.stderr, flush=True)
        return 1
    try:
        print(_safe_output(result), flush=True)
    except Exception:
        print(_SAFE_ERROR, file=sys.stderr, flush=True)
        return 1
    return 0


def migrate_main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    connection_factory: Callable[[str, str], Any] = _connection,
) -> int:
    """Run only the explicit private-provider migration entrypoint."""

    env = os.environ if environ is None else environ
    parser = _SafeArgumentParser(prog="instrument-master-provider-migrate")
    connection: Any | None = None
    failure: str | None = None
    cleanup_failure: str | None = None
    cleanup_base_exception: BaseException | None = None
    try:
        parser.parse_args(argv)
        connection = connection_factory(_migrator_dsn(env), _DEFAULT_SCHEMA)
        if connection is None:
            raise RuntimeError("database connection cannot be opened")
        apply_instrument_master_provider_migration(connection)
    except SystemExit:
        raise
    except Exception:
        failure = _SAFE_ERROR
    finally:
        cleanup_failure, cleanup_base_exception = _close_resources(connection, None)

    if cleanup_base_exception is not None and failure is None:
        raise cleanup_base_exception
    if cleanup_failure is not None:
        failure = cleanup_failure
    if failure is not None:
        print(failure, file=sys.stderr, flush=True)
        return 1
    return 0


__all__ = ["main", "migrate_main", "run_instrument_master_once"]
