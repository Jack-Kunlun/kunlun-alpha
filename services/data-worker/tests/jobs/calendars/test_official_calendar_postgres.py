"""PostgreSQL acceptance tests for the official SSE raw-first calendar job."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from data_worker.jobs.calendars.official_sse import (
    SSE_2026_ANNOUNCEMENT_URL,
    SSE_CALENDAR_SOURCE,
    SSE_PARSER_VERSION,
    SSE_RECEIPT_SOURCE,
    OfficialSseCalendarError,
    OfficialSseResponse,
    SseOfficialCalendarCollector,
    parse_sse_2026_announcement,
    replay_sse_calendar,
)
from data_worker.jobs.calendars.postgres_repository import PostgresCalendarRepository
from data_worker.jobs.calendars.repository import (
    CalendarOperationConflictError,
    CalendarRepository,
    InMemoryCalendarRepository,
)
from data_worker.raw import LocalFileStorage, RawObjectManifest, RawStorageError
from data_worker.raw.storage import RawIntegrityError
from data_worker.storage import apply_data_worker_migrations

_OBSERVED_AT = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)
_RAW_DATE = _OBSERVED_AT.date().isoformat()

_OFFICIAL_HTML = """
<html>
  <head><title>关于上海证券交易所2026年部分节假日休市安排的通知</title></head>
  <body>
    <h1>关于上海证券交易所2026年部分节假日休市安排的通知</h1>
    <p>上证公告〔2025〕45号</p>
    <p>发布日期：2025-12-22</p>
    <p>上海证券交易所</p>
    <p>一、休市安排</p>
    <p>（一）元旦：1月1日（星期四）至1月3日（星期六）休市，1月5日（星期一）起照常开市。另外，1月4日（星期日）为周末休市。</p>
    <p>（二）春节：2月15日（星期日）至2月23日（星期一）休市，2月24日（星期二）起照常开市。另外，2月14日（星期六）、2月28日（星期六）为周末休市。</p>
    <p>（三）清明节：4月4日（星期六）至4月6日（星期一）休市，4月7日（星期二）起照常开市。</p>
    <p>（四）劳动节：5月1日（星期五）至5月5日（星期二）休市，5月6日（星期三）起照常开市。另外，5月9日（星期六）为周末休市。</p>
    <p>（五）端午节：6月19日（星期五）至6月21日（星期日）休市，6月22日（星期一）起照常开市。</p>
    <p>（六）中秋节：9月25日（星期五）至9月27日（星期日）休市，9月28日（星期一）起照常开市。</p>
    <p>（七）国庆节：10月1日（星期四）至10月7日（星期三）休市，10月8日（星期四）起照常开市。另外，9月20日（星期日）、10月10日（星期六）为周末休市。</p>
    <p>二、有关清算事宜，根据中国证券登记结算有限责任公司的安排进行。</p>
    <p>三、有关春节、国庆节测试事宜，本所将另行通知。</p>
  </body>
</html>
""".encode()


class _FakeTransport:
    def __init__(self, response: OfficialSseResponse | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, float, int]] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int) -> OfficialSseResponse:
        self.calls.append((url, timeout_seconds, max_bytes))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _create_worker_base_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          max_attempts INTEGER NOT NULL,
          lease_token TEXT,
          lease_expires_at TIMESTAMPTZ,
          next_run_at TIMESTAMPTZ,
          last_error_category TEXT,
          last_error_detail JSONB,
          dead_letter_detail JSONB,
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE checkpoints (
          task_id TEXT PRIMARY KEY,
          cursor TEXT,
          state JSONB,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE quality_events (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          unified_code TEXT,
          date DATE,
          detail TEXT
        );
        """
    )


@pytest.fixture()
def postgres_repositories() -> Generator[
    tuple[PostgresCalendarRepository, PostgresCalendarRepository, str], None, None
]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn)
    except Exception:
        pytest.skip("PostgreSQL unavailable")

    schema = f"calendar_official_sse_{uuid4().hex}"
    first: Any = None
    second: Any = None
    try:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
        first = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with first.transaction(), first.cursor() as cursor:
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(first)
        second = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        yield PostgresCalendarRepository(first), PostgresCalendarRepository(second), schema
    finally:
        if second is not None:
            second.close()
        if first is not None:
            first.close()
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def _collector(
    raw: LocalFileStorage,
    repository: CalendarRepository,
    body: bytes = _OFFICIAL_HTML,
) -> tuple[SseOfficialCalendarCollector, _FakeTransport]:
    transport = _FakeTransport(
        OfficialSseResponse(
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=body,
        )
    )
    return (
        SseOfficialCalendarCollector(
            raw,
            repository,
            transport=transport,
            clock=lambda: _OBSERVED_AT,
        ),
        transport,
    )


def _count(connection: Any, table: str) -> int:
    allowed = {
        "calendar_snapshot_versions",
        "calendar_snapshot_holidays",
        "calendar_snapshot_latest",
        "calendar_snapshot_corrections",
        "calendar_snapshot_audit",
    }
    if table not in allowed:
        raise AssertionError("test table is not allowlisted")
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM {table}")
        return int(cursor.fetchone()[0])


def _assert_no_calendar_rows(repository: PostgresCalendarRepository) -> None:
    for table in (
        "calendar_snapshot_versions",
        "calendar_snapshot_holidays",
        "calendar_snapshot_latest",
        "calendar_snapshot_corrections",
        "calendar_snapshot_audit",
    ):
        assert _count(repository._connection, table) == 0


def _calendar_counts(connection: Any) -> dict[str, int]:
    return {
        table: _count(connection, table)
        for table in (
            "calendar_snapshot_versions",
            "calendar_snapshot_holidays",
            "calendar_snapshot_latest",
            "calendar_snapshot_audit",
        )
    }


def _seed_raw_capture_and_receipt(
    raw: LocalFileStorage,
    *,
    capture_id: str,
) -> Any:
    seed_repository = InMemoryCalendarRepository()
    seed_collector, _transport = _collector(raw, seed_repository)
    return seed_collector.collect(capture_id=capture_id)


def test_collect_existing_receipt_with_different_repository_version_fails_without_new_rows(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    seeded = _seed_raw_capture_and_receipt(
        raw,
        capture_id="receipt-version-mismatch-collect",
    )
    holidays = parse_sse_2026_announcement(_OFFICIAL_HTML)
    existing_version = repository.save_version(
        SSE_CALENDAR_SOURCE,
        2026,
        holidays,
        exchange="SH",
        operation_id=seeded.operation_id,
    )
    before = _calendar_counts(repository._connection)

    collector, _transport = _collector(raw, repository)
    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id=seeded.capture_id)

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert existing_version != seeded.version_id
    assert _calendar_counts(repository._connection) == before
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) == existing_version
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 1


def test_collect_existing_receipt_without_repository_operation_fails_without_new_rows(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    seeded = _seed_raw_capture_and_receipt(
        raw,
        capture_id="receipt-operation-missing-collect",
    )
    before = _calendar_counts(repository._connection)

    collector, _transport = _collector(raw, repository)
    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id=seeded.capture_id)

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert _calendar_counts(repository._connection) == before
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) is None
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 1


def test_replay_existing_receipt_without_repository_operation_fails_without_new_rows(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    seeded = _seed_raw_capture_and_receipt(
        raw,
        capture_id="receipt-operation-missing-replay",
    )
    before = _calendar_counts(repository._connection)

    with pytest.raises(OfficialSseCalendarError) as error:
        replay_sse_calendar(
            raw,
            reopened,
            capture_id=seeded.capture_id,
            date=seeded.raw_date,
            exchange="SH",
            year=2026,
        )

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert _calendar_counts(repository._connection) == before
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) is None
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 1


def test_find_operation_version_is_read_only_and_fingerprint_bound(
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    holidays = parse_sse_2026_announcement(_OFFICIAL_HTML)
    operation_id = "calendar-operation-lookup"

    assert (
        repository.find_operation_version(
            SSE_CALENDAR_SOURCE,
            2026,
            holidays,
            exchange="SH",
            operation_id=operation_id,
        )
        is None
    )
    assert _calendar_counts(repository._connection) == {
        "calendar_snapshot_versions": 0,
        "calendar_snapshot_holidays": 0,
        "calendar_snapshot_latest": 0,
        "calendar_snapshot_audit": 0,
    }

    version_id = repository.save_version(
        SSE_CALENDAR_SOURCE,
        2026,
        holidays,
        exchange="SH",
        operation_id=operation_id,
    )
    before = _calendar_counts(repository._connection)
    assert (
        repository.find_operation_version(
            SSE_CALENDAR_SOURCE,
            2026,
            holidays,
            exchange="SH",
            operation_id=operation_id,
        )
        == version_id
    )
    assert (
        repository.find_operation_version(
            SSE_CALENDAR_SOURCE,
            2026,
            holidays,
            exchange="SH",
            operation_id="another-operation",
        )
        is None
    )
    with pytest.raises(CalendarOperationConflictError) as error:
        repository.find_operation_version(
            SSE_CALENDAR_SOURCE,
            2026,
            holidays[:-1],
            exchange="SH",
            operation_id=operation_id,
        )
    assert str(error.value) == "calendar operation conflicts with existing content"
    assert error.value.__context__ is None
    assert _calendar_counts(repository._connection) == before


def test_official_fixture_uses_public_worker_migrations_and_persists_19_holidays_and_receipt(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    collector, transport = _collector(raw, repository)

    with repository._connection.transaction(), repository._connection.cursor() as cursor:
        cursor.execute("SELECT version, name FROM data_worker_schema_migrations ORDER BY version")
        assert cursor.fetchall() == [
            (1, "precious_metals_migration"),
            (2, "seat_collection_migration"),
            (3, "calendar_snapshot_migration"),
            (4, "official_calendar_migration"),
        ]

    result = collector.collect(capture_id="official-pg-capture")

    assert transport.calls == [(SSE_2026_ANNOUNCEMENT_URL, 10.0, 512 * 1024)]
    assert result.exchange == "SH"
    assert result.year == 2026
    assert result.raw_date == _RAW_DATE
    assert result.parser_version == SSE_PARSER_VERSION
    assert result.holiday_count == 19
    assert result.coverage_status == "UNKNOWN"
    assert len(repository.get_version(result.version_id)) == 19
    assert reopened.get_version(result.version_id) == repository.get_version(result.version_id)
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_holidays") == 19
    assert _count(repository._connection, "calendar_snapshot_latest") == 1
    assert _count(repository._connection, "calendar_snapshot_audit") == 1

    captures = raw.list(SSE_CALENDAR_SOURCE, _RAW_DATE)
    receipts = raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)
    assert len(captures) == 1
    assert len(receipts) == 1
    receipt = json.loads(raw.get(receipts[0].object_id, checksum=receipts[0].checksum))
    assert receipt["capture_id"] == result.capture_id
    assert receipt["calendar_version_id"] == result.version_id
    assert receipt["raw_object_id"] == result.raw_object_id
    assert receipt["raw_checksum"] == result.raw_checksum


def test_replay_from_new_connection_reuses_same_capture_version_and_receipt(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    collector, _transport = _collector(raw, repository)
    first = collector.collect(capture_id="cross-connection-capture")

    replayed = replay_sse_calendar(
        raw,
        reopened,
        capture_id=first.capture_id,
        date=first.raw_date,
        exchange="SH",
        year=2026,
    )

    assert replayed.version_id == first.version_id
    assert replayed.receipt_id == first.receipt_id
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_audit") == 1
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 1


def test_receipt_failure_after_postgres_commit_replays_without_new_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    receipt_failure = True
    original_put = raw.put

    def put_with_receipt_failure(**kwargs: Any) -> RawObjectManifest:
        if receipt_failure and kwargs.get("source") == SSE_RECEIPT_SOURCE:
            raise RawStorageError("synthetic receipt failure")
        return original_put(**kwargs)

    monkeypatch.setattr(raw, "put", put_with_receipt_failure)
    collector, _transport = _collector(raw, repository)

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="receipt-recovery-capture")

    assert str(error.value) == "official SSE calendar receipt failed"
    assert error.value.__context__ is None
    version_id = repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026)
    assert version_id is not None
    assert len(repository.get_version(version_id)) == 19
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_holidays") == 19
    assert _count(repository._connection, "calendar_snapshot_audit") == 1
    assert len(raw.list(SSE_CALENDAR_SOURCE, _RAW_DATE)) == 1
    assert raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE) == []

    receipt_failure = False
    replayed = replay_sse_calendar(
        raw,
        reopened,
        capture_id="receipt-recovery-capture",
        date=_RAW_DATE,
        exchange="SH",
        year=2026,
    )

    assert replayed.version_id == version_id
    assert _count(repository._connection, "calendar_snapshot_versions") == 1
    assert _count(repository._connection, "calendar_snapshot_audit") == 1
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 1


def test_identical_capture_bytes_create_versions_and_old_replay_keeps_latest(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    collector, _transport = _collector(raw, repository)

    first = collector.collect(capture_id="same-bytes-capture-a")
    second = collector.collect(capture_id="same-bytes-capture-b")

    assert first.raw_object_id == second.raw_object_id
    assert first.raw_checksum == second.raw_checksum
    assert first.version_id != second.version_id
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) == second.version_id
    assert len(raw.list(SSE_CALENDAR_SOURCE, _RAW_DATE)) == 2
    assert len(raw.list(SSE_RECEIPT_SOURCE, _RAW_DATE)) == 2
    assert _count(repository._connection, "calendar_snapshot_versions") == 2
    assert _count(repository._connection, "calendar_snapshot_holidays") == 38
    assert _count(repository._connection, "calendar_snapshot_audit") == 2

    replayed = replay_sse_calendar(
        raw,
        reopened,
        capture_id=first.capture_id,
        date=_RAW_DATE,
        exchange="SH",
        year=2026,
    )

    assert replayed.version_id == first.version_id
    assert repository.latest_version_id(SSE_CALENDAR_SOURCE, "SH", 2026) == second.version_id
    assert _count(repository._connection, "calendar_snapshot_versions") == 2
    assert _count(repository._connection, "calendar_snapshot_audit") == 2


def test_parse_failure_keeps_raw_capture_but_does_not_write_postgres(
    tmp_path: Path,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")
    bad_body = (
        _OFFICIAL_HTML.decode("utf-8").replace("上海证券交易所", "未经核验的发布方").encode("utf-8")
    )
    collector, _transport = _collector(raw, repository, bad_body)

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="parse-failure-pg")

    assert str(error.value) == "official SSE calendar announcement is invalid"
    assert error.value.__context__ is None
    assert len(raw.list(SSE_CALENDAR_SOURCE, _RAW_DATE)) == 1
    _assert_no_calendar_rows(repository)


def test_raw_storage_failure_after_capture_does_not_write_postgres(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    postgres_repositories: tuple[PostgresCalendarRepository, PostgresCalendarRepository, str],
) -> None:
    repository, _reopened, _schema = postgres_repositories
    raw = LocalFileStorage(tmp_path / "raw")

    def broken_get(*_args: Any, **_kwargs: Any) -> bytes:
        raise RawIntegrityError("synthetic raw corruption")

    monkeypatch.setattr(raw, "get", broken_get)
    collector, _transport = _collector(raw, repository)

    with pytest.raises(OfficialSseCalendarError) as error:
        collector.collect(capture_id="storage-failure-pg")

    assert str(error.value) == "official SSE calendar capture integrity failed"
    assert error.value.__context__ is None
    assert len(raw.list(SSE_CALENDAR_SOURCE, _RAW_DATE)) == 1
    _assert_no_calendar_rows(repository)
