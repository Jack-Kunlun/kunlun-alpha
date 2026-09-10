"""One-shot CLI composition root for the fixed SSE holiday capture."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any

from data_worker.jobs.calendars.official_sse import (
    OfficialSseCalendarError,
    OfficialSseTransport,
    SseOfficialCalendarCollector,
    SseOfficialCalendarResult,
    replay_sse_calendar,
)
from data_worker.jobs.calendars.repository import CalendarRepository
from data_worker.raw import LocalFileStorage, RawStorage

_RAW_ROOT_ENV = "KUNLUN_RAW_ROOT"
_DSN_ENV = "KUNLUN_POSTGRES_DSN"
_DEFAULT_SCHEMA = "kunlun"
_CLI_ERROR = "official SSE calendar CLI failed"
_DB_ERROR = "official SSE calendar database is unavailable"
_RAW_ROOT_ERROR = "official SSE calendar raw root is required"
_REPLAY_ARGUMENT_ERROR = "official SSE calendar replay arguments are invalid"
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_DB_CONNECT_TIMEOUT_SECONDS = 10


def run_official_sse_once(
    *,
    raw_storage: RawStorage,
    repository: CalendarRepository,
    exchange: str = "SH",
    year: int = 2026,
    replay_capture_id: str | None = None,
    replay_date: str | None = None,
    transport: OfficialSseTransport | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SseOfficialCalendarResult:
    """Run one injected collection or one explicit offline replay."""

    if (replay_capture_id is None) != (replay_date is None):
        raise OfficialSseCalendarError(_REPLAY_ARGUMENT_ERROR)
    if replay_capture_id is not None and replay_date is not None:
        return replay_sse_calendar(
            raw_storage,
            repository,
            capture_id=replay_capture_id,
            date=replay_date,
            exchange=exchange,
            year=year,
        )
    collector = SseOfficialCalendarCollector(
        raw_storage,
        repository,
        transport=transport,
        clock=clock,
    )
    return collector.collect(exchange=exchange, year=year)


def _open_repository(dsn: str, schema: str) -> tuple[Any, CalendarRepository]:
    if type(dsn) is not str or not dsn.strip():
        raise OfficialSseCalendarError(_DB_ERROR)
    if type(schema) is not str or _SCHEMA_RE.fullmatch(schema) is None:
        raise OfficialSseCalendarError(_DB_ERROR)
    connection: Any = None
    failed = False
    try:
        import psycopg

        connection = psycopg.connect(
            dsn,
            options=f'-c search_path="{schema}"',
            connect_timeout=_DB_CONNECT_TIMEOUT_SECONDS,
        )
    except Exception:
        failed = True
    if failed or connection is None:
        raise OfficialSseCalendarError(_DB_ERROR)
    from data_worker.jobs.calendars.postgres_repository import PostgresCalendarRepository

    return connection, PostgresCalendarRepository(connection)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture the fixed SSE SH 2026 holiday page")
    parser.add_argument("--exchange", default="SH")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--raw-root", default=os.environ.get(_RAW_ROOT_ENV))
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--capture-id")
    parser.add_argument("--date")
    return parser.parse_args(argv)


def _safe_payload(result: SseOfficialCalendarResult) -> str:
    return json.dumps(
        {
            "capture_id": result.capture_id,
            "calendar_version_id": result.version_id,
            "coverage_status": result.coverage_status,
            "holiday_count": result.holiday_count,
            "raw_checksum": result.raw_checksum,
            "receipt_id": result.receipt_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run one collection/replay without migrations or continuous scheduling."""

    try:
        args = _arguments(argv)
        if not isinstance(args.raw_root, str) or not args.raw_root.strip():
            raise OfficialSseCalendarError(_RAW_ROOT_ERROR)
        if args.replay and (args.capture_id is None or args.date is None):
            raise OfficialSseCalendarError(_REPLAY_ARGUMENT_ERROR)
        if not args.replay and (args.capture_id is not None or args.date is not None):
            raise OfficialSseCalendarError(_REPLAY_ARGUMENT_ERROR)
        raw_storage = LocalFileStorage(Path(args.raw_root))
        connection, repository = _open_repository(
            os.environ.get(_DSN_ENV, ""),
            os.environ.get("KUNLUN_POSTGRES_SCHEMA", _DEFAULT_SCHEMA),
        )
        try:
            result = run_official_sse_once(
                raw_storage=raw_storage,
                repository=repository,
                exchange=args.exchange,
                year=args.year,
                replay_capture_id=args.capture_id if args.replay else None,
                replay_date=args.date if args.replay else None,
            )
        finally:
            with suppress(Exception):
                connection.close()
        print(_safe_payload(result))
        return 0
    except OfficialSseCalendarError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print(_CLI_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_official_sse_once"]
