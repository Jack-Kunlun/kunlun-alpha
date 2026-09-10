"""One-shot operational entry points for the sealed calendar-quality V5 ledger."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, NoReturn

from data_worker.storage.migrations import (
    CALENDAR_QUALITY_SCHEMA,
    CalendarQualityPublishResult,
    publish_calendar_quality,
    verify_calendar_quality_runtime,
)

_RUNTIME_DSN_ENV = "CALENDAR_QUALITY_RUNTIME_DSN"
_RUNTIME_DSN_FILE_ENV = "CALENDAR_QUALITY_RUNTIME_DSN_FILE"
_ADMIN_DSN_ENV = "CALENDAR_QUALITY_ADMIN_DSN"
_ADMIN_DSN_FILE_ENV = "CALENDAR_QUALITY_ADMIN_DSN_FILE"
_MAX_DSN_FILE_BYTES = 4096
_SAFE_ERROR = "calendar quality operation failed"


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        self.exit(2, "argument error\n")


def _dedicated_dsn(environ: Mapping[str, str], direct_name: str, file_name: str) -> str:
    direct = environ.get(direct_name)
    file_value = environ.get(file_name)
    if direct is not None and direct.strip() and file_value is not None and file_value.strip():
        raise ValueError("database DSN configuration is ambiguous")
    if direct is not None and direct.strip():
        return direct.strip()
    if file_value is None or not file_value.strip():
        raise ValueError("database DSN is required")

    path = Path(file_value.strip())
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
        unsafe_file = stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH
        unsafe_parent = stat.S_IWGRP | stat.S_IWOTH
        if (
            info.st_uid not in {0, current_uid}
            or parent_info.st_uid not in {0, current_uid}
            or info.st_mode & unsafe_file
            or parent_info.st_mode & unsafe_parent
        ):
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
    if len(content) > _MAX_DSN_FILE_BYTES or not content.strip():
        raise ValueError("database DSN is invalid")
    return content.strip()


def _runtime_dsn(environ: Mapping[str, str]) -> str:
    return _dedicated_dsn(environ, _RUNTIME_DSN_ENV, _RUNTIME_DSN_FILE_ENV)


def _admin_dsn(environ: Mapping[str, str]) -> str:
    return _dedicated_dsn(environ, _ADMIN_DSN_ENV, _ADMIN_DSN_FILE_ENV)


def _required_secret(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value:
        raise ValueError("calendar quality secret is required")
    if len(value) > 4096 or "\x00" in value:
        raise ValueError("calendar quality secret is invalid")
    return value


def _connection(dsn: str, schema: str) -> Any:
    if not dsn.strip() or schema != CALENDAR_QUALITY_SCHEMA:
        raise ValueError("database connection configuration is invalid")
    import psycopg

    return psycopg.connect(
        dsn,
        connect_timeout=8,
        options=f'-c search_path="{CALENDAR_QUALITY_SCHEMA}"',
    )


def _close_connection(connection: Any | None) -> tuple[str | None, BaseException | None]:
    if connection is None:
        return None, None
    try:
        close = getattr(connection, "close", None)
        if not callable(close):
            return _SAFE_ERROR, None
        close()
    except BaseException as error:
        if isinstance(error, Exception):
            return _SAFE_ERROR, None
        return None, error
    return None, None


def _parser(prog: str) -> argparse.ArgumentParser:
    return _SafeArgumentParser(
        prog=prog,
        description="Verify the sealed calendar-quality V5 ledger",
    )


def _run(
    *,
    dsn: str,
    action: Callable[[Any], Any],
    connection_factory: Callable[[str, str], Any],
) -> int:
    connection: Any | None = None
    failure: str | None = None
    result: Any = None
    try:
        connection = connection_factory(dsn, CALENDAR_QUALITY_SCHEMA)
        if connection is None:
            raise RuntimeError("database connection cannot be opened")
        result = action(connection)
    except SystemExit:
        raise
    except Exception:
        failure = _SAFE_ERROR
    cleanup_failure, cleanup_base_exception = _close_connection(connection)
    if cleanup_base_exception is not None and failure is None:
        raise cleanup_base_exception
    if cleanup_failure is not None:
        failure = cleanup_failure
    if failure is not None:
        print(failure, file=sys.stderr, flush=True)
        return 1
    if result is None:
        output: dict[str, str] = {"status": "VERIFIED"}
    elif isinstance(result, CalendarQualityPublishResult):
        output = {"status": result.disposition.value}
    else:
        print(_SAFE_ERROR, file=sys.stderr, flush=True)
        return 1
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    connection_factory: Callable[[str, str], Any] = _connection,
) -> int:
    """Verify V5 without DDL or ledger writes."""

    env = os.environ if environ is None else environ
    parser = _parser("calendar-quality-verify")
    try:
        parser.parse_args(argv)
        dsn = _runtime_dsn(env)
    except SystemExit:
        raise
    except Exception:
        print(_SAFE_ERROR, file=sys.stderr, flush=True)
        return 1
    return _run(
        dsn=dsn,
        action=verify_calendar_quality_runtime,
        connection_factory=connection_factory,
    )


def publish_main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    connection_factory: Callable[[str, str], Any] = _connection,
) -> int:
    """Install and seal V5 through one dedicated administrator transaction."""

    env = os.environ if environ is None else environ
    parser = _parser("calendar-quality-publish")
    try:
        parser.parse_args(argv)
        dsn = _admin_dsn(env)
        migrator_password = _required_secret(env, "CALENDAR_QUALITY_MIGRATOR_PASSWORD")
        runtime_password = _required_secret(env, "CALENDAR_QUALITY_RUNTIME_PASSWORD")
    except SystemExit:
        raise
    except Exception:
        print(_SAFE_ERROR, file=sys.stderr, flush=True)
        return 1

    return _run(
        dsn=dsn,
        action=lambda connection: publish_calendar_quality(
            connection,
            migrator_password=migrator_password,
            runtime_password=runtime_password,
        ),
        connection_factory=connection_factory,
    )


__all__ = ["main", "publish_main"]


if __name__ == "__main__":
    raise SystemExit(main())
