"""Contract tests for the one-shot SZSE V4 runtime."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import json
import os
import runpy
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, cast
from uuid import UUID

import data_worker.jobs.calendars.official_szse_runtime as runtime
import pytest
from data_worker.jobs.calendars.official_calendar_repository import (
    OfficialCalendarPersistResult,
)
from data_worker.jobs.calendars.official_szse_daily import (
    OfficialSzseCalendarError,
    OfficialSzseTransport,
    SzseOfficialDailyResult,
)
from data_worker.raw import LocalFileStorage, RawStorage

_RUN_ID = UUID(int=42)
_MANIFEST_DATE = "2026-09-06"
_MANIFEST_CAPTURE_ID = "capture-manifest"
_OUTCOME = OfficialCalendarPersistResult(
    run_id=_RUN_ID,
    snapshot_id=UUID(int=43),
    disposition="SNAPSHOT_CREATED",
    terminal="COMPLETE",
    coverage_level="FINAL_YEAR",
)
_RAW_STORAGE = cast(RawStorage, object())
_TRANSPORT = cast(OfficialSzseTransport, object())


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FailingCloseConnection(_FakeConnection):
    def close(self) -> None:
        self.closed = True
        raise RuntimeError("close-secret")


class _BaseExceptionCloseConnection(_FakeConnection):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def close(self) -> None:
        self.closed = True
        raise self.error


class _FakeGuard:
    def __init__(self) -> None:
        self.closed = False

    def assert_stable(self) -> None:
        if self.closed:
            raise AssertionError("closed guard was used")

    def close(self) -> None:
        self.closed = True


class _FailingGuard(_FakeGuard):
    def close(self) -> None:
        self.closed = True
        raise RuntimeError("guard-close-secret")


class _BaseExceptionCloseGuard(_FakeGuard):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def close(self) -> None:
        self.closed = True
        raise self.error


class _CustomCleanupBaseException(BaseException):
    pass


class _RecordingRepository:
    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events

    def persist_authoritative_szse_run(
        self,
        raw_storage: RawStorage,
        run_id: UUID,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> OfficialCalendarPersistResult:
        self.events.append(("persist", (raw_storage, run_id, manifest_date, manifest_capture_id)))
        return _OUTCOME


class _RecordingCollector:
    def __init__(self, events: list[tuple[str, object]], result: object) -> None:
        self.events = events
        self.result = result

    def __call__(self, raw_storage: RawStorage, **kwargs: object) -> _RecordingCollector:
        self.events.append(("collector", (raw_storage, kwargs)))
        return self

    def collect(self, *, exchange: str, year: int) -> object:
        self.events.append(("collect", (exchange, year)))
        return self.result


def _forbidden_open_repository(*unused: object, **also_unused: object) -> NoReturn:
    del unused, also_unused
    pytest.fail("invalid inputs must fail before DB open")


def _forbidden_capture_collection(**unused: object) -> NoReturn:
    del unused
    pytest.fail("invalid capture-only arguments must not collect")


def _raise_provider_error(**unused: object) -> NoReturn:
    del unused
    raise OfficialSzseCalendarError("provider-secret")


def _collected_result() -> object:
    return SimpleNamespace(
        run_id=_RUN_ID,
        raw_manifest_ref=SimpleNamespace(
            raw_date=_MANIFEST_DATE,
            capture_id=_MANIFEST_CAPTURE_ID,
        ),
    )


def _fixture_daily_result(tmp_path: Path) -> SzseOfficialDailyResult:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_official_szse_daily.py")))
    import data_worker.jobs.calendars.official_szse_daily as daily

    original_pins = daily._IDENTITY_SOURCE_SHA256
    body_factories = {
        "root": helpers["_official_root_body"],
        "path": helpers["_official_path_body"],
        "concat": helpers["_official_concatversion_body"],
        "js": helpers["_official_js_body"],
    }
    daily._IDENTITY_SOURCE_SHA256 = {
        kind: hashlib.sha256(factory()).hexdigest() for kind, factory in body_factories.items()
    }
    try:
        collector = runtime.SzseOfficialCalendarCollector(
            LocalFileStorage(tmp_path / "raw"),
            transport=helpers["_transport"](),
            clock=helpers["_Clock"](),
            run_id=_RUN_ID,
        )
        return collector.collect(exchange="SZ", year=2026)
    finally:
        daily._IDENTITY_SOURCE_SHA256 = original_pins


def test_collect_replays_coordinates_after_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, object]] = []
    collector = _RecordingCollector(events, _collected_result())
    monkeypatch.setattr(runtime, "SzseOfficialCalendarCollector", collector)
    repository = _RecordingRepository(events)
    raw_storage = object()
    transport = _TRANSPORT

    def clock() -> datetime:
        return datetime(2026, 9, 6, tzinfo=UTC)

    outcome = runtime.run_official_szse_once(
        raw_storage=cast(RawStorage, raw_storage),
        repository=repository,
        transport=transport,
        clock=clock,
    )

    assert outcome == _OUTCOME
    assert events == [
        ("collector", (raw_storage, {"transport": transport, "clock": clock})),
        ("collect", ("SZ", 2026)),
        ("persist", (raw_storage, _RUN_ID, _MANIFEST_DATE, _MANIFEST_CAPTURE_ID)),
    ]


def test_replay_does_not_construct_or_call_a_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, object]] = []

    def forbidden_collector(*args: object, **kwargs: object) -> object:
        raise AssertionError("replay must not construct a collector")

    monkeypatch.setattr(runtime, "SzseOfficialCalendarCollector", forbidden_collector)
    repository = _RecordingRepository(events)

    outcome = runtime.run_official_szse_once(
        raw_storage=_RAW_STORAGE,
        repository=repository,
        replay=True,
        run_id=_RUN_ID,
        manifest_date=_MANIFEST_DATE,
        manifest_capture_id=_MANIFEST_CAPTURE_ID,
        transport=_TRANSPORT,
    )

    assert outcome == _OUTCOME
    assert events[0][0] == "persist"


@pytest.mark.parametrize(
    ("replay", "run_id", "manifest_date", "manifest_capture_id"),
    [
        (True, None, None, None),
        (True, _RUN_ID, _MANIFEST_DATE, None),
        (False, _RUN_ID, None, None),
        (False, None, _MANIFEST_DATE, None),
        (False, None, None, _MANIFEST_CAPTURE_ID),
    ],
)
def test_replay_coordinates_must_be_explicit_and_complete(
    replay: bool,
    run_id: UUID | None,
    manifest_date: str | None,
    manifest_capture_id: str | None,
) -> None:
    with pytest.raises(OfficialSzseCalendarError):
        runtime.run_official_szse_once(
            raw_storage=_RAW_STORAGE,
            repository=_RecordingRepository([]),
            replay=replay,
            run_id=run_id,
            manifest_date=manifest_date,
            manifest_capture_id=manifest_capture_id,
        )


def test_safe_payload_preserves_duplicate_out_of_order_and_conflict_results() -> None:
    outcomes = (
        replace(_OUTCOME, disposition="DUPLICATE", run_disposition="DUPLICATE"),
        replace(
            _OUTCOME,
            snapshot_id=None,
            disposition="DUPLICATE",
            terminal="INDETERMINATE",
            coverage_level="FINAL_YEAR",
            run_disposition="DUPLICATE",
        ),
        replace(
            _OUTCOME,
            snapshot_id=None,
            disposition="DUPLICATE",
            terminal="INDETERMINATE",
            coverage_level="CONFIRMED_HORIZON",
            run_disposition="OUT_OF_ORDER",
        ),
        replace(
            _OUTCOME,
            snapshot_id=None,
            disposition="DUPLICATE",
            terminal="INDETERMINATE",
            coverage_level="INDETERMINATE",
            run_disposition="CONFLICT",
        ),
        replace(
            _OUTCOME,
            snapshot_id=None,
            disposition="OUT_OF_ORDER_BLOCKED",
            terminal="INDETERMINATE",
            coverage_level="FINAL_YEAR",
            run_disposition="OUT_OF_ORDER",
        ),
        replace(
            _OUTCOME,
            snapshot_id=None,
            disposition="CONFLICT_HEAD",
            terminal="INDETERMINATE",
            coverage_level="FINAL_YEAR",
            run_disposition="CONFLICT",
        ),
    )
    for outcome in outcomes:
        payload = json.loads(runtime._safe_payload(outcome))
        assert set(payload) == {
            "run_id",
            "snapshot_id",
            "disposition",
            "terminal",
            "coverage_level",
            "run_disposition",
        }
        assert payload["disposition"] == outcome.disposition
        assert payload["run_disposition"] == outcome.run_disposition
        assert payload["terminal"] == outcome.terminal


def test_safe_payload_never_wraps_indeterminate_as_complete() -> None:
    outcome = replace(
        _OUTCOME,
        snapshot_id=None,
        terminal="INDETERMINATE",
        coverage_level="CONFIRMED_HORIZON",
        disposition="OUT_OF_ORDER_BLOCKED",
        run_disposition="OUT_OF_ORDER",
    )
    payload = json.loads(runtime._safe_payload(outcome))
    assert payload["terminal"] == "INDETERMINATE"
    assert payload["snapshot_id"] is None


def test_safe_payload_rejects_inconsistent_result() -> None:
    with pytest.raises(OfficialSzseCalendarError):
        runtime._safe_payload(replace(_OUTCOME, snapshot_id=None))


def _patch_cli(
    monkeypatch: pytest.MonkeyPatch,
    outcome: OfficialCalendarPersistResult | None = _OUTCOME,
    failure: Exception | None = None,
) -> tuple[_FakeConnection, list[tuple[str, object]]]:
    connection = _FakeConnection()
    events: list[tuple[str, object]] = []
    repository = _RecordingRepository(events)

    def open_repository(
        dsn: object, schema: object
    ) -> tuple[_FakeConnection, _RecordingRepository]:
        events.append(("open", (dsn, schema)))
        return connection, repository

    def run_once(**kwargs: object) -> OfficialCalendarPersistResult:
        events.append(("run", kwargs))
        if failure is not None:
            raise failure
        assert outcome is not None
        return outcome

    monkeypatch.setattr(runtime, "_open_repository", open_repository)
    monkeypatch.setattr(runtime, "run_official_szse_once", run_once)
    return connection, events


def test_cli_success_has_safe_sorted_output_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection, events = _patch_cli(monkeypatch)
    secret_dsn = "postgresql://user:secret-token@example.invalid/db"
    monkeypatch.setenv("KUNLUN_POSTGRES_DSN", secret_dsn)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root)]) == 0

    captured = capsys.readouterr()
    assert captured.out == runtime._safe_payload(_OUTCOME) + "\n"
    assert captured.err == ""
    assert secret_dsn not in captured.out + captured.err
    assert str(raw_root) not in captured.out + captured.err
    assert connection.closed
    assert events[0] == ("open", (secret_dsn, "kunlun"))
    assert events[1][0] == "run"


def test_cli_capture_only_collects_raw_without_opening_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("KUNLUN_POSTGRES_DSN", "dsn-secret")
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    result = _fixture_daily_result(tmp_path)

    def collect(**unused: object) -> SzseOfficialDailyResult:
        del unused
        return result

    monkeypatch.setattr(runtime, "_collect_official_szse_once", collect)

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "RAW_CAPTURED_UNPERSISTED"
    assert payload["run_id"] == str(_RUN_ID)
    assert payload["manifest_capture_id"] == result.raw_manifest_ref.capture_id
    assert payload["proof_digest"] == result.proof.proof_digest
    confirmed_through = result.proof.coverage.confirmed_through
    assert confirmed_through is not None
    assert payload["confirmed_through"] == confirmed_through.isoformat()
    assert payload["source_nowdate"] == result.proof.coverage.source_nowdate.isoformat()
    assert captured.err == ""
    assert "dsn-secret" not in captured.out + captured.err
    assert str(raw_root) not in captured.out + captured.err
    assert set(payload) == {
        "status",
        "exchange",
        "year",
        "run_id",
        "manifest_date",
        "manifest_capture_id",
        "manifest_sha256",
        "proof_digest",
        "parser_version",
        "contract_version",
        "manifest_version",
        "capture_state_version",
        "catalog_version",
        "identity_policy_version",
        "coverage_level",
        "confirmed_through",
        "source_nowdate",
        "available_at",
        "identity_count",
        "catalog_count",
        "attempt_count",
        "page_count",
        "daily_day_count",
    }
    assert not {
        "snapshot_id",
        "terminal",
        "disposition",
        "run_disposition",
        "accepted",
        "complete",
        "final_year",
    }.intersection(payload)


def test_cli_capture_only_does_not_read_postgres_dsn_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _fixture_daily_result(tmp_path)

    def collect(**unused: object) -> SzseOfficialDailyResult:
        del unused
        return result

    monkeypatch.setattr(runtime, "_collect_official_szse_once", collect)
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)
    original_get = runtime.os.environ.get
    environment_keys: list[str] = []

    def recording_get(key: str, default: str | None = None) -> str | None:
        environment_keys.append(key)
        if key == runtime._DSN_ENV:
            raise AssertionError("capture-only must not read the PostgreSQL DSN")
        return original_get(key, default)

    monkeypatch.setattr(runtime.os.environ, "get", recording_get)
    raw_root = tmp_path / "capture-root"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert runtime._RAW_ROOT_ENV in environment_keys
    assert runtime._DSN_ENV not in environment_keys


def test_cli_capture_only_serialization_failure_has_no_success_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _fixture_daily_result(tmp_path)

    def collect(**unused: object) -> SzseOfficialDailyResult:
        del unused
        return result

    def failing_dumps(*unused: object, **also_unused: object) -> NoReturn:
        del unused, also_unused
        raise RuntimeError("serialization-secret")

    monkeypatch.setattr(runtime, "_collect_official_szse_once", collect)
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)

    def validated_capture(_value: object) -> SzseOfficialDailyResult:
        return result

    monkeypatch.setattr(runtime, "_validated_capture_result", validated_capture)
    monkeypatch.setattr(runtime.json, "dumps", failing_dumps)
    raw_root = tmp_path / "capture-root"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._CLI_ERROR + "\n"
    assert "serialization-secret" not in captured.err


def test_cli_capture_only_raw_root_replacement_fails_closed_before_database_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    old_root = tmp_path / "old-root"

    class _ReplacingCollector:
        def __init__(self, unused_storage: RawStorage, **unused_kwargs: object) -> None:
            del unused_storage, unused_kwargs

        def collect(self, *, exchange: str, year: int) -> object:
            del exchange, year
            raw_root.rename(old_root)
            replacement.rename(raw_root)
            return _collected_result()

    monkeypatch.setattr(runtime, "SzseOfficialCalendarCollector", _ReplacingCollector)
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._RAW_ROOT_ERROR + "\n"


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--replay"],
        ["--run-id", str(_RUN_ID)],
        ["--manifest-date", _MANIFEST_DATE],
        ["--manifest-capture-id", _MANIFEST_CAPTURE_ID],
    ],
)
def test_cli_capture_only_rejects_replay_coordinates_before_database_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
) -> None:
    monkeypatch.setenv("KUNLUN_POSTGRES_DSN", "dsn-secret")
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)
    monkeypatch.setattr(
        runtime,
        "_collect_official_szse_once",
        _forbidden_capture_collection,
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only", *extra_args]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._REPLAY_ARGUMENT_ERROR + "\n"
    assert "dsn-secret" not in captured.err


def test_cli_capture_only_maps_collection_failure_without_success_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)
    monkeypatch.setattr(
        runtime,
        "_collect_official_szse_once",
        _raise_provider_error,
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._CLI_ERROR + "\n"
    assert "provider-secret" not in captured.err


def test_cli_capture_only_guard_cleanup_failure_does_not_print_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    guard = _FailingGuard()
    result = _fixture_daily_result(tmp_path)

    def open_failing_guard(_root: Path) -> _FailingGuard:
        return guard

    monkeypatch.setattr(runtime._RawRootGuard, "open", open_failing_guard)

    def collect(**unused: object) -> SzseOfficialDailyResult:
        del unused
        return result

    monkeypatch.setattr(runtime, "_collect_official_szse_once", collect)
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)
    raw_root = tmp_path / "capture-root"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root), "--capture-only"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._RAW_ROOT_ERROR + "\n"
    assert guard.closed


def test_safe_capture_payload_rejects_tampered_or_malformed_results(
    tmp_path: Path,
) -> None:
    result = _fixture_daily_result(tmp_path)
    payload = json.loads(runtime._safe_capture_payload(result))
    assert payload["status"] == "RAW_CAPTURED_UNPERSISTED"
    assert payload["coverage_level"] == result.proof.coverage.level.value
    assert payload["available_at"] == result.proof.cutoff_at.isoformat()
    assert "final_year" not in payload

    tampered_manifest = replace(result.raw_manifest_ref, raw_date="2026-09-05")
    tampered_result = object.__new__(type(result))
    for field_name in (
        "exchange",
        "year",
        "run_id",
        "proof",
        "identity_assets",
        "catalog_refs",
        "attempts",
    ):
        object.__setattr__(tampered_result, field_name, getattr(result, field_name))
    object.__setattr__(tampered_result, "raw_manifest_ref", tampered_manifest)
    with pytest.raises(OfficialSzseCalendarError) as tampered_error:
        runtime._safe_capture_payload(tampered_result)
    assert str(tampered_error.value) == runtime._RESULT_ERROR

    with pytest.raises(OfficialSzseCalendarError) as malformed_error:
        runtime._safe_capture_payload(SimpleNamespace())
    assert str(malformed_error.value) == runtime._RESULT_ERROR


def test_cli_replay_passes_only_explicit_coordinates_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection, events = _patch_cli(monkeypatch)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    args = [
        "--raw-root",
        str(raw_root),
        "--replay",
        "--run-id",
        str(_RUN_ID),
        "--manifest-date",
        _MANIFEST_DATE,
        "--manifest-capture-id",
        _MANIFEST_CAPTURE_ID,
    ]

    assert runtime.main(args) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert connection.closed
    run_kwargs = cast(dict[str, object], events[1][1])
    assert run_kwargs["replay"] is True
    assert run_kwargs["run_id"] == _RUN_ID
    assert run_kwargs["manifest_date"] == _MANIFEST_DATE
    assert run_kwargs["manifest_capture_id"] == _MANIFEST_CAPTURE_ID


@pytest.mark.parametrize(
    "args",
    [
        ["--replay"],
        ["--replay", "--run-id", str(_RUN_ID), "--manifest-date", _MANIFEST_DATE],
        ["--run-id", str(_RUN_ID)],
        ["--manifest-date", _MANIFEST_DATE],
        ["--manifest-capture-id", _MANIFEST_CAPTURE_ID],
    ],
)
def test_cli_replay_arguments_must_be_complete_and_not_extra(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    monkeypatch.setenv("KUNLUN_POSTGRES_DSN", "dsn-secret")
    monkeypatch.setattr(
        runtime,
        "_open_repository",
        _forbidden_open_repository,
    )

    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    result = runtime.main(["--raw-root", str(raw_root), *args])

    assert result == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._REPLAY_ARGUMENT_ERROR + "\n"
    assert "dsn-secret" not in captured.err


@pytest.mark.parametrize(
    "args",
    [
        [
            "--replay",
            "--run-id",
            "not-a-uuid",
            "--manifest-date",
            _MANIFEST_DATE,
            "--manifest-capture-id",
            _MANIFEST_CAPTURE_ID,
        ],
        [
            "--replay",
            "--run-id",
            str(_RUN_ID),
            "--manifest-date",
            "2026-02-30",
            "--manifest-capture-id",
            _MANIFEST_CAPTURE_ID,
        ],
        [
            "--replay",
            "--run-id",
            str(_RUN_ID),
            "--manifest-date",
            _MANIFEST_DATE,
            "--manifest-capture-id",
            "../escape",
        ],
    ],
)
def test_cli_replay_coordinates_are_validated_before_db_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
) -> None:
    monkeypatch.setattr(
        runtime,
        "_open_repository",
        _forbidden_open_repository,
    )

    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    result = runtime.main(["--raw-root", str(raw_root), *args])

    assert result == 1
    assert capsys.readouterr().err == runtime._REPLAY_ARGUMENT_ERROR + "\n"


def test_cli_rejects_relative_or_file_raw_root_before_db_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_file = tmp_path / "raw-file"
    raw_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        runtime,
        "_open_repository",
        _forbidden_open_repository,
    )

    for raw_root in ("relative/raw", str(raw_file)):
        assert runtime.main(["--raw-root", raw_root]) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == runtime._RAW_ROOT_ERROR + "\n"


def test_cli_uses_absolute_raw_root_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection, events = _patch_cli(monkeypatch)
    raw_root = tmp_path / "from-env"
    raw_root.mkdir()
    monkeypatch.setenv("KUNLUN_RAW_ROOT", str(raw_root))

    assert runtime.main([]) == 0

    capsys.readouterr()
    assert connection.closed
    assert events[1][0] == "run"


@pytest.mark.parametrize(
    ("dsn", "schema"),
    [
        ("", "kunlun"),
        ("postgresql://safe", ""),
        ("postgresql://safe", "not-portable"),
        ("postgresql://safe", "1bad"),
    ],
)
def test_open_repository_rejects_invalid_dsn_or_schema_without_connect(
    monkeypatch: pytest.MonkeyPatch,
    dsn: str,
    schema: str,
) -> None:
    monkeypatch.setattr(
        runtime.psycopg,
        "connect",
        _forbidden_open_repository,
    )

    with pytest.raises(OfficialSzseCalendarError) as error:
        runtime._open_repository(dsn, schema)
    assert str(error.value) == runtime._DB_ERROR


def test_open_repository_bounds_connect_and_closes_on_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection()
    calls: list[tuple[object, dict[str, object]]] = []

    def connect(dsn: object, **kwargs: object) -> _FakeConnection:
        calls.append((dsn, kwargs))
        return connection

    def broken_repository(unused_connection: object) -> object:
        raise RuntimeError("repository secret")

    monkeypatch.setattr(runtime.psycopg, "connect", connect)
    monkeypatch.setattr(runtime, "PostgresOfficialCalendarRepository", broken_repository)

    with pytest.raises(OfficialSzseCalendarError) as error:
        runtime._open_repository("postgresql://safe", "kunlun")

    assert str(error.value) == runtime._DB_ERROR
    assert connection.closed
    assert calls == [
        (
            "postgresql://safe",
            {"options": '-c search_path="kunlun"', "connect_timeout": 10},
        )
    ]


def test_cli_closes_connection_when_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection, _events = _patch_cli(monkeypatch, failure=RuntimeError("db-secret"))
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._CLI_ERROR + "\n"
    assert "db-secret" not in captured.err
    assert connection.closed


def test_cli_maps_unknown_domain_error_to_fixed_cli_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_cli(monkeypatch, failure=OfficialSzseCalendarError("provider-secret"))
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._CLI_ERROR + "\n"
    assert "provider-secret" not in captured.err


def test_cli_close_failure_is_fixed_error_and_does_not_print_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FailingCloseConnection()
    events: list[tuple[str, object]] = []
    repository = _RecordingRepository(events)

    def open_repository(
        dsn: object, schema: object
    ) -> tuple[_FailingCloseConnection, _RecordingRepository]:
        events.append(("open", (dsn, schema)))
        return connection, repository

    monkeypatch.setattr(runtime, "_open_repository", open_repository)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    assert runtime.main(["--raw-root", str(raw_root)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == runtime._DB_ERROR + "\n"
    assert connection.closed


def _patch_cli_base_exception(
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
) -> tuple[_FakeConnection, _FakeGuard]:
    connection = _FakeConnection()
    guard = _FakeGuard()
    repository = _RecordingRepository([])

    def open_guard(unused_root: Path) -> _FakeGuard:
        del unused_root
        return guard

    def open_repository(
        dsn: object, schema: object
    ) -> tuple[_FakeConnection, _RecordingRepository]:
        del dsn, schema
        return connection, repository

    def run_once(**kwargs: object) -> OfficialCalendarPersistResult:
        del kwargs
        raise raised

    monkeypatch.setattr(runtime._RawRootGuard, "open", open_guard)
    monkeypatch.setattr(runtime, "_open_repository", open_repository)
    monkeypatch.setattr(runtime, "run_official_szse_once", run_once)
    return connection, guard


def _patch_cli_cleanup_base_exception(
    monkeypatch: pytest.MonkeyPatch,
    connection: _FakeConnection,
    guard: _FakeGuard,
) -> None:
    repository = _RecordingRepository([])

    def open_guard(unused_root: Path) -> _FakeGuard:
        del unused_root
        return guard

    def open_repository(
        dsn: object, schema: object
    ) -> tuple[_FakeConnection, _RecordingRepository]:
        del dsn, schema
        return connection, repository

    def run_once(**kwargs: object) -> OfficialCalendarPersistResult:
        del kwargs
        return _OUTCOME

    monkeypatch.setattr(runtime._RawRootGuard, "open", open_guard)
    monkeypatch.setattr(runtime, "_open_repository", open_repository)
    monkeypatch.setattr(runtime, "run_official_szse_once", run_once)


def test_cli_keyboard_interrupt_closes_resources_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    work_error = KeyboardInterrupt()
    connection, guard = _patch_cli_base_exception(monkeypatch, work_error)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(KeyboardInterrupt) as error:
        runtime.main(["--raw-root", str(raw_root)])

    assert error.value is work_error
    assert connection.closed
    assert guard.closed


def test_cli_system_exit_closes_resources_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    work_error = SystemExit(23)
    connection, guard = _patch_cli_base_exception(monkeypatch, work_error)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(SystemExit) as error:
        runtime.main(["--raw-root", str(raw_root)])

    assert error.value is work_error
    assert error.value.code == 23
    assert connection.closed
    assert guard.closed


def test_cli_preserves_base_exception_when_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connection = _FailingCloseConnection()
    guard = _FailingGuard()
    repository = _RecordingRepository([])

    def open_guard(unused_root: Path) -> _FailingGuard:
        del unused_root
        return guard

    def open_repository(
        dsn: object, schema: object
    ) -> tuple[_FailingCloseConnection, _RecordingRepository]:
        del dsn, schema
        return connection, repository

    work_error = KeyboardInterrupt()

    def run_once(**kwargs: object) -> OfficialCalendarPersistResult:
        del kwargs
        raise work_error

    monkeypatch.setattr(runtime._RawRootGuard, "open", open_guard)
    monkeypatch.setattr(runtime, "_open_repository", open_repository)
    monkeypatch.setattr(runtime, "run_official_szse_once", run_once)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(KeyboardInterrupt) as error:
        runtime.main(["--raw-root", str(raw_root)])

    assert error.value is work_error
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert connection.closed
    assert guard.closed


@pytest.mark.parametrize(
    "exception_factory",
    [KeyboardInterrupt, lambda: SystemExit(41), _CustomCleanupBaseException],
)
def test_cli_reraises_connection_cleanup_base_exception_exactly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exception_factory: Callable[[], BaseException],
) -> None:
    cleanup_error = exception_factory()
    connection = _BaseExceptionCloseConnection(cleanup_error)
    guard = _FakeGuard()
    _patch_cli_cleanup_base_exception(monkeypatch, connection, guard)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(BaseException) as error:
        runtime.main(["--raw-root", str(raw_root)])

    assert error.value is cleanup_error
    assert connection.closed
    assert guard.closed


@pytest.mark.parametrize(
    "exception_factory",
    [KeyboardInterrupt, lambda: SystemExit(43), _CustomCleanupBaseException],
)
def test_cli_reraises_guard_cleanup_base_exception_exactly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exception_factory: Callable[[], BaseException],
) -> None:
    cleanup_error = exception_factory()
    connection = _FakeConnection()
    guard = _BaseExceptionCloseGuard(cleanup_error)
    _patch_cli_cleanup_base_exception(monkeypatch, connection, guard)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(BaseException) as error:
        runtime.main(["--raw-root", str(raw_root)])

    assert error.value is cleanup_error
    assert connection.closed
    assert guard.closed


def test_cli_argparse_system_exit_does_not_open_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = False

    def forbidden_open(unused_root: Path) -> NoReturn:
        nonlocal opened
        del unused_root
        opened = True
        pytest.fail("argparse exits must happen before resource opening")

    monkeypatch.setattr(runtime._RawRootGuard, "open", forbidden_open)
    monkeypatch.setattr(runtime, "_open_repository", _forbidden_open_repository)

    with pytest.raises(SystemExit) as help_exit:
        runtime.main(["--help"])
    assert help_exit.value.code == 0

    with pytest.raises(SystemExit) as argument_exit:
        runtime.main(["--unknown-secret-flag", "secret-token"])
    assert argument_exit.value.code == 2
    assert not opened


def test_cli_never_calls_migration_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from data_worker.storage import migrations

    called = False

    def forbidden_migration(*unused: object, **also_unused: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("runtime must not migrate")

    connection = _FakeConnection()
    events: list[tuple[str, object]] = []
    repository = _RecordingRepository(events)

    def connect(dsn: object, **kwargs: object) -> _FakeConnection:
        events.append(("connect", (dsn, kwargs)))
        return connection

    def build_repository(unused_connection: object) -> _RecordingRepository:
        del unused_connection
        return repository

    def run_once(**kwargs: object) -> OfficialCalendarPersistResult:
        events.append(("run", kwargs))
        return _OUTCOME

    monkeypatch.setattr(migrations, "apply_data_worker_migrations", forbidden_migration)
    monkeypatch.setattr(runtime.psycopg, "connect", connect)
    monkeypatch.setattr(runtime, "PostgresOfficialCalendarRepository", build_repository)
    monkeypatch.setattr(runtime, "run_official_szse_once", run_once)
    assert "apply_data_worker_migrations" not in runtime.__dict__
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    monkeypatch.setenv("KUNLUN_POSTGRES_DSN", "dsn-secret")

    assert runtime.main(["--raw-root", str(raw_root)]) == 0

    capsys.readouterr()
    assert not called
    assert connection.closed
    assert events[0] == (
        "connect",
        (
            "dsn-secret",
            {"options": '-c search_path="kunlun"', "connect_timeout": 10},
        ),
    )


def test_cli_help_is_available_and_unknown_arguments_do_not_echo_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        runtime.main(["--help"])
    assert help_exit.value.code == 0
    help_output = capsys.readouterr()
    assert "--replay" in help_output.out
    assert "--capture-only" in help_output.out
    assert "SZSE" in help_output.out
    assert "usage: official-szse-daily-sync" in help_output.out

    with pytest.raises(SystemExit) as error_exit:
        runtime.main(["--unknown-secret-flag", "secret-token"])
    assert error_exit.value.code == 2
    error_output = capsys.readouterr()
    assert "secret-token" not in error_output.err


def test_pyproject_registers_szse_entrypoint() -> None:
    service_pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    contents = service_pyproject.read_text(encoding="utf-8")
    assert (
        'official-szse-daily-sync = "data_worker.jobs.calendars.official_szse_runtime:main"'
        in contents
    )


def test_validated_raw_root_requires_existing_secure_non_symlink_directory(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    assert runtime._validated_raw_root(str(raw_root)) == raw_root

    invalid_paths = (tmp_path / "missing", Path(os.path.abspath(os.sep)))
    for invalid_path in invalid_paths:
        with pytest.raises(OfficialSzseCalendarError):
            runtime._validated_raw_root(str(invalid_path))


@pytest.mark.skipif(os.name == "nt", reason="symlink and POSIX ownership checks differ")
def test_validated_raw_root_rejects_root_and_parent_symlinks_and_writable_dirs(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    raw_root = real_parent / "raw"
    raw_root.mkdir()

    root_link = tmp_path / "root-link"
    root_link.symlink_to(raw_root, target_is_directory=True)
    dangling_link = tmp_path / "dangling-link"
    dangling_link.symlink_to(tmp_path / "does-not-exist", target_is_directory=True)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)

    for invalid_path in (
        root_link,
        dangling_link,
        parent_link / "raw",
    ):
        with pytest.raises(OfficialSzseCalendarError):
            runtime._validated_raw_root(str(invalid_path))

    writable_parent = tmp_path / "writable-parent"
    writable_parent.mkdir()
    writable_root = writable_parent / "raw"
    writable_root.mkdir()
    original_parent_mode = writable_parent.stat().st_mode & 0o777
    original_root_mode = writable_root.stat().st_mode & 0o777
    try:
        writable_parent.chmod(0o777)
        with pytest.raises(OfficialSzseCalendarError):
            runtime._validated_raw_root(str(writable_root))
        writable_parent.chmod(original_parent_mode)
        writable_root.chmod(0o777)
        with pytest.raises(OfficialSzseCalendarError):
            runtime._validated_raw_root(str(writable_root))
    finally:
        writable_parent.chmod(original_parent_mode)
        writable_root.chmod(original_root_mode)


def test_raw_root_guard_rejects_replacement_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    guard = runtime._RawRootGuard.open(raw_root)
    events: list[tuple[str, object]] = []
    repository = _RecordingRepository(events)

    class _ReplacingCollector:
        def __init__(self, unused_storage: RawStorage, **unused_kwargs: object) -> None:
            del unused_storage, unused_kwargs

        def collect(self, *, exchange: str, year: int) -> object:
            del exchange, year
            raw_root.rename(tmp_path / "old-root")
            replacement.rename(raw_root)
            return _collected_result()

    monkeypatch.setattr(runtime, "SzseOfficialCalendarCollector", _ReplacingCollector)
    try:
        with pytest.raises(OfficialSzseCalendarError) as error:
            runtime.run_official_szse_once(
                raw_storage=runtime._GuardedRawStorage(cast(RawStorage, object()), guard),
                repository=repository,
                raw_guard=guard,
            )
        assert str(error.value) == runtime._RAW_ROOT_ERROR
        assert events == []
    finally:
        guard.close()


def test_guarded_storage_rechecks_root_after_each_operation(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    guard = runtime._RawRootGuard.open(raw_root)

    class _ReplacingStorage:
        def list(self, source: str, date: str) -> list[object]:
            del source, date
            raw_root.rename(tmp_path / "old-root")
            replacement.rename(raw_root)
            return []

    storage = runtime._GuardedRawStorage(cast(RawStorage, _ReplacingStorage()), guard)
    try:
        with pytest.raises(OfficialSzseCalendarError) as error:
            storage.list("source", "2026-09-06")
        assert str(error.value) == runtime._RAW_ROOT_ERROR
    finally:
        guard.close()


def test_safe_payload_rejects_invalid_disposition_combinations() -> None:
    invalid_outcomes = (
        replace(_OUTCOME, snapshot_id=None),
        replace(_OUTCOME, run_disposition="DUPLICATE"),
        replace(
            _OUTCOME,
            disposition="OUT_OF_ORDER_BLOCKED",
            terminal="INDETERMINATE",
            coverage_level="CONFIRMED_HORIZON",
            run_disposition="CONFIRMED",
            snapshot_id=None,
        ),
        replace(
            _OUTCOME,
            disposition="CONFLICT_HEAD",
            terminal="INDETERMINATE",
            coverage_level="INDETERMINATE",
            run_disposition="CONFLICT",
            snapshot_id=UUID(int=43),
        ),
        replace(_OUTCOME, terminal="COMPLETE", coverage_level="CONFIRMED_HORIZON"),
        replace(_OUTCOME, terminal="INDETERMINATE", coverage_level="FINAL_YEAR"),
        replace(
            _OUTCOME,
            disposition="OUT_OF_ORDER_BLOCKED",
            terminal="INDETERMINATE",
            coverage_level="FINAL_YEAR",
            run_disposition="OUT_OF_ORDER",
            snapshot_id=UUID(int=43),
        ),
    )
    for outcome in invalid_outcomes:
        with pytest.raises(OfficialSzseCalendarError):
            runtime._safe_payload(outcome)
