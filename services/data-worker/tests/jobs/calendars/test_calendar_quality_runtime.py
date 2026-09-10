"""Operational contract tests for the calendar-quality V5 boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from data_worker.jobs.calendars import calendar_quality_repository
from data_worker.jobs.calendars.calendar_quality_repository import (
    CalendarQualityPersistenceError,
)
from data_worker.jobs.calendars.calendar_quality_runtime import main
from psycopg.pq import TransactionStatus


def test_storage_migrations_imports_in_a_fresh_process_without_calendar_cycle() -> None:
    source_root = Path(__file__).resolve().parents[3] / "src"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root)
        if not existing_pythonpath
        else os.pathsep.join((str(source_root), existing_pythonpath))
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from data_worker.storage import migrations; "
                "print(migrations.CALENDAR_QUALITY_MIGRATION_VERSION)"
            ),
        ],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "5"


class _IdleInfo:
    transaction_status = TransactionStatus.IDLE


class _IdleConnection:
    info = _IdleInfo()


class _RepoCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._identity_returned = False

    def __enter__(self) -> _RepoCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, _parameters: object = None) -> None:
        self.queries.append(query)

    def fetchone(self) -> tuple[str, str] | None:
        if not self._identity_returned:
            self._identity_returned = True
            return ("admin", "kunlun_cq_runtime")
        return None

    def fetchall(self) -> tuple[object, ...]:
        return ()


class _RepoTransaction:
    def __enter__(self) -> _RepoTransaction:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _RepoConnection:
    info = _IdleInfo()

    def __init__(self) -> None:
        self.cursor_instance = _RepoCursor()

    def transaction(self) -> _RepoTransaction:
        return _RepoTransaction()

    def cursor(self) -> _RepoCursor:
        return self.cursor_instance


class _RuntimeContextCursor:
    def __init__(self, identities: list[tuple[str, str]], context: tuple[str, str]) -> None:
        self.queries: list[str] = []
        self._identities = identities
        self._context = context
        self._identity_index = 0

    def __enter__(self) -> _RuntimeContextCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, _parameters: object = None) -> None:
        self.queries.append(query)

    def fetchone(self) -> tuple[str, str] | None:
        query = self.queries[-1]
        if "SESSION_USER" in query:
            if self._identity_index >= len(self._identities):
                return None
            identity = self._identities[self._identity_index]
            self._identity_index += 1
            return identity
        if "current_schema()" in query:
            return self._context
        return None

    def fetchall(self) -> tuple[object, ...]:
        return ()


class _RuntimeContextConnection:
    info = _IdleInfo()

    def __init__(self, cursor: _RuntimeContextCursor) -> None:
        self.cursor_instance = cursor

    def transaction(self) -> _RepoTransaction:
        return _RepoTransaction()

    def cursor(self) -> _RuntimeContextCursor:
        return self.cursor_instance


def test_repository_initialize_is_verify_only(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _IdleConnection()
    verified: list[object] = []

    def verify(supplied: object, **kwargs: object) -> None:
        verified.append(supplied)
        assert kwargs == {
            "schema": "kunlun",
            "roles": calendar_quality_repository.CalendarQualityRoles(),
        }

    monkeypatch.setattr(calendar_quality_repository, "verify_calendar_quality_runtime", verify)
    repository = calendar_quality_repository.PostgresCalendarQualityRepository(connection)  # type: ignore[arg-type]

    repository.initialize()

    assert verified == [connection]


def test_calendar_quality_runtime_rejects_shared_dsn_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [],
        environ={"KUNLUN_POSTGRES_DSN": "postgresql://shared-secret"},
        connection_factory=lambda _dsn, _schema: pytest.fail("unexpected connection"),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "calendar quality operation failed"
    assert "shared-secret" not in captured.out + captured.err


def test_calendar_quality_publish_requires_dedicated_admin_and_passwords_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from data_worker.jobs.calendars.calendar_quality_runtime import publish_main

    exit_code = publish_main(
        [],
        environ={
            "KUNLUN_POSTGRES_DSN": "postgresql://shared-secret",
            "CALENDAR_QUALITY_MIGRATOR_PASSWORD": "migrator-secret",
            "CALENDAR_QUALITY_RUNTIME_PASSWORD": "runtime-secret",
        },
        connection_factory=lambda _dsn, _schema: pytest.fail("unexpected connection"),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "calendar quality operation failed"
    assert "shared-secret" not in captured.out + captured.err
    assert "migrator-secret" not in captured.out + captured.err
    assert "runtime-secret" not in captured.out + captured.err


def test_calendar_quality_publish_requires_non_empty_passwords_without_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from data_worker.jobs.calendars.calendar_quality_runtime import publish_main

    exit_code = publish_main(
        [],
        environ={"CALENDAR_QUALITY_ADMIN_DSN": "postgresql://admin"},
        connection_factory=lambda _dsn, _schema: pytest.fail("unexpected connection"),
    )

    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "calendar quality operation failed"


def test_calendar_quality_publish_serializes_only_terminal_disposition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from data_worker.jobs.calendars import calendar_quality_runtime as runtime
    from data_worker.storage.migrations import (
        CalendarQualityPublishDisposition,
        CalendarQualityPublishResult,
    )

    class Connection:
        def close(self) -> None:
            return None

    def publish(_connection: object, **_kwargs: object) -> CalendarQualityPublishResult:
        return CalendarQualityPublishResult(CalendarQualityPublishDisposition.ALREADY_SEALED)

    monkeypatch.setattr(
        runtime,
        "publish_calendar_quality",
        publish,
    )

    exit_code = runtime.publish_main(
        [],
        environ={
            "CALENDAR_QUALITY_ADMIN_DSN": "postgresql://admin",
            "CALENDAR_QUALITY_MIGRATOR_PASSWORD": "migrator-secret",
            "CALENDAR_QUALITY_RUNTIME_PASSWORD": "runtime-secret",
        },
        connection_factory=lambda _dsn, _schema: Connection(),
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == '{"status":"ALREADY_SEALED"}'


def test_calendar_quality_compose_exposes_only_atomic_publish_entrypoint() -> None:
    compose_body = Path("infra/docker/docker-compose.apps.yml").read_text(encoding="utf-8")
    pyproject_body = Path("services/data-worker/pyproject.toml").read_text(encoding="utf-8")

    assert "  calendar-quality-publish:" in compose_body
    assert "calendar-quality-role-bootstrap" not in compose_body
    assert "  calendar-quality-migrate:" not in compose_body
    assert "  calendar-quality-seal:" not in compose_body
    assert 'command: ["calendar-quality-publish"]' in compose_body
    assert "calendar-quality-publish" in pyproject_body
    assert "calendar-quality-migrate" not in pyproject_body
    assert "calendar-quality-seal" not in pyproject_body


def test_repository_rejects_admin_set_role_before_business_sql() -> None:
    connection = _RepoConnection()
    repository = calendar_quality_repository.PostgresCalendarQualityRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(CalendarQualityPersistenceError):
        repository.list_manual_overlays(uuid4(), datetime(2026, 1, 1, tzinfo=UTC))

    assert not any(
        "calendar_quality_manual_overlays" in query for query in connection.cursor_instance.queries
    )


def test_repository_rechecks_session_identity_for_each_operation() -> None:
    cursor = _RuntimeContextCursor(
        [("kunlun_cq_runtime", "kunlun_cq_runtime"), ("kunlun_cq_runtime", "other")],
        ("kunlun", '"kunlun", pg_catalog, pg_temp'),
    )
    connection = _RuntimeContextConnection(cursor)
    repository = calendar_quality_repository.PostgresCalendarQualityRepository(connection)  # type: ignore[arg-type]
    as_of = datetime(2026, 1, 1, tzinfo=UTC)

    assert repository.list_manual_overlays(uuid4(), as_of) == ()
    with pytest.raises(CalendarQualityPersistenceError):
        repository.list_manual_overlays(uuid4(), as_of)

    assert sum("calendar_quality_manual_overlays" in query for query in cursor.queries) == 1


def test_repository_rejects_search_path_drift_before_business_sql() -> None:
    cursor = _RuntimeContextCursor(
        [("kunlun_cq_runtime", "kunlun_cq_runtime")],
        ("other", '"other"'),
    )
    connection = _RuntimeContextConnection(cursor)
    repository = calendar_quality_repository.PostgresCalendarQualityRepository(connection)  # type: ignore[arg-type]

    with pytest.raises(CalendarQualityPersistenceError):
        repository.list_manual_overlays(uuid4(), datetime(2026, 1, 1, tzinfo=UTC))

    assert not any("calendar_quality_manual_overlays" in query for query in cursor.queries)


def test_calendar_quality_has_no_raw_role_or_seal_bypass() -> None:
    compose_body = Path("infra/docker/docker-compose.apps.yml").read_text(encoding="utf-8")
    assert not Path("infra/docker/migrations/calendar-quality-roles.sql").exists()
    assert "calendar-quality-seal.sql" not in compose_body
