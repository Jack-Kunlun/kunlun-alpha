"""One-shot runtime safety tests for the instrument-master job."""

# The runtime intentionally keeps the capability and output helpers private;
# these tests exercise those security boundaries directly.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import NoReturn, cast
from uuid import UUID

import pytest
from data_worker.jobs.instruments import runtime
from data_worker.jobs.instruments.postgres_repository import InstrumentMasterPersistResult
from data_worker.raw import RawStorage


class _StubRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, str, str]] = []

    def persist_authoritative_instrument_master_run(
        self,
        raw_storage: object,
        run_id: str,
        manifest_date: str,
        manifest_capture_id: str,
    ) -> InstrumentMasterPersistResult:
        self.calls.append((raw_storage, run_id, manifest_date, manifest_capture_id))
        return InstrumentMasterPersistResult(
            run_id=UUID("00000000-0000-4000-8000-000000000001"),
            snapshot_id=None,
            disposition="NO_HEAD_CHANGE",
            terminal="INDETERMINATE",
            completeness="INDETERMINATE",
            run_disposition="NO_HEAD_CHANGE",
        )


def test_replay_requires_exact_coordinate_set(tmp_path: Path) -> None:
    repository = _StubRepository()
    raw_storage = cast(RawStorage, object())

    with pytest.raises(ValueError, match="required"):
        runtime.run_instrument_master_once(
            raw_storage=raw_storage,
            repository=repository,  # type: ignore[arg-type]
            replay=True,
            run_id="run",
            manifest_date="2026-09-08",
        )


def test_replay_composition_passes_only_coordinates(tmp_path: Path) -> None:
    repository = _StubRepository()
    raw_storage = cast(RawStorage, object())
    result = runtime.run_instrument_master_once(
        raw_storage=raw_storage,
        repository=repository,  # type: ignore[arg-type]
        replay=True,
        run_id="00000000-0000-4000-8000-000000000001",
        manifest_date="2026-09-08",
        manifest_capture_id="manifest-1",
    )

    assert result.run_disposition == "NO_HEAD_CHANGE"
    assert len(repository.calls) == 1
    assert repository.calls[0] == (
        raw_storage,
        "00000000-0000-4000-8000-000000000001",
        "2026-09-08",
        "manifest-1",
    )


def test_safe_cli_rejects_missing_dsn_and_does_not_echo_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "dsn-password-and-token"
    exit_code = runtime.main(
        ["--raw-root", str(tmp_path)],
        environ={"KUNLUN_POSTGRES_DSN": secret, "TUSHARE_TOKEN": secret},
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "instrument master sync failed"
    assert secret not in captured.out + captured.err


def test_help_is_available_without_database_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as error:
        runtime.main(["--help"])

    assert error.value.code == 0
    assert "--replay" in capsys.readouterr().out


def test_safe_output_is_sorted_compact_json() -> None:
    result = InstrumentMasterPersistResult(
        run_id=UUID("00000000-0000-4000-8000-000000000001"),
        snapshot_id=None,
        disposition="NO_HEAD_CHANGE",
        terminal="INDETERMINATE",
        completeness="INDETERMINATE",
        run_disposition="NO_HEAD_CHANGE",
    )
    output = runtime._safe_output(result)
    assert output == json.dumps(
        {
            "run_id": "00000000-0000-4000-8000-000000000001",
            "snapshot_id": None,
            "disposition": "NO_HEAD_CHANGE",
            "terminal": "INDETERMINATE",
            "coverage_level": "INDETERMINATE",
            "run_disposition": "NO_HEAD_CHANGE",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.skipif(os.name == "nt", reason="directory capability checks are POSIX-specific")
def test_raw_root_guard_and_guarded_storage_reject_replacement(tmp_path: Path) -> None:
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
        with pytest.raises(ValueError, match="raw root"):
            storage.list("tushare-instrument-master", "2026-09-08")
    finally:
        guard.close()


@pytest.mark.skipif(os.name == "nt", reason="symlink and POSIX ownership checks differ")
def test_raw_root_rejects_symlink_components_and_writable_directories(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    raw_root = parent / "raw"
    raw_root.mkdir()
    root_link = tmp_path / "root-link"
    root_link.symlink_to(raw_root, target_is_directory=True)
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(parent, target_is_directory=True)

    with pytest.raises(ValueError, match="trusted directory"):
        runtime._raw_root(str(root_link), {})
    with pytest.raises(ValueError, match="trusted directory"):
        runtime._raw_root(str(parent_link / "raw"), {})

    original_mode = parent.stat().st_mode & 0o777
    try:
        parent.chmod(0o777)
        with pytest.raises(ValueError, match="raw root"):
            runtime._raw_root(str(raw_root), {})
    finally:
        parent.chmod(original_mode)


def test_main_does_not_emit_success_before_connection_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FailingConnection:
        def close(self) -> None:
            raise RuntimeError("close failed")

    result = InstrumentMasterPersistResult(
        run_id=UUID("00000000-0000-4000-8000-000000000001"),
        snapshot_id=None,
        disposition="NO_HEAD_CHANGE",
        terminal="INDETERMINATE",
        completeness="INDETERMINATE",
        run_disposition="NO_HEAD_CHANGE",
    )

    def fake_run(**_: object) -> InstrumentMasterPersistResult:
        return result

    monkeypatch.setattr(runtime, "run_instrument_master_once", fake_run)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    exit_code = runtime.main(
        [],
        environ={
            "KUNLUN_RAW_ROOT": str(raw_root),
            "INSTRUMENT_MASTER_RUNTIME_DSN": "postgresql://redacted",
            "TUSHARE_TOKEN": "secret-token",
        },
        connection_factory=lambda _dsn, _schema: _FailingConnection(),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert captured.err.strip() == "instrument master sync failed"
    assert "secret-token" not in captured.out + captured.err


def test_close_resources_preserves_close_getter_base_exception_and_closes_guard() -> None:
    class _ExplodingConnection:
        @property
        def close(self) -> NoReturn:
            raise KeyboardInterrupt("close getter")

    class _Guard:
        closed = False

        def close(self) -> None:
            self.closed = True

    guard = _Guard()
    failure, base_exception = runtime._close_resources(
        _ExplodingConnection(),
        cast(runtime._RawRootGuard, guard),
    )

    assert failure is None
    assert isinstance(base_exception, KeyboardInterrupt)
    assert guard.closed


def test_runtime_does_not_fallback_to_shared_worker_dsn(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    calls: list[tuple[str, str]] = []

    def connection_factory(dsn: str, schema: str) -> object:
        calls.append((dsn, schema))
        return object()

    exit_code = runtime.main(
        [
            "--replay",
            "--run-id",
            "00000000-0000-4000-8000-000000000001",
            "--manifest-date",
            "2026-09-08",
            "--manifest-capture-id",
            "manifest-1",
        ],
        environ={
            "KUNLUN_RAW_ROOT": str(raw_root),
            "KUNLUN_POSTGRES_DSN": "postgresql://shared-secret",
        },
        connection_factory=connection_factory,
    )

    assert exit_code == 1
    assert calls == []


def test_runtime_accepts_only_dedicated_dsn_and_fixed_provider_schema(tmp_path: Path) -> None:
    dsn = "postgresql://dedicated-runtime"
    assert runtime._runtime_dsn({"INSTRUMENT_MASTER_RUNTIME_DSN": dsn}) == dsn
    assert runtime._schema({"KUNLUN_POSTGRES_SCHEMA": "public"}) == ("kunlun_instrument_provider")

    dsn_file = tmp_path / "runtime.dsn"
    dsn_file.write_text(dsn, encoding="utf-8")
    dsn_file.chmod(0o600)
    assert runtime._runtime_dsn({"INSTRUMENT_MASTER_RUNTIME_DSN_FILE": str(dsn_file)}) == dsn

    with pytest.raises(ValueError, match="ambiguous"):
        runtime._runtime_dsn(
            {
                "INSTRUMENT_MASTER_RUNTIME_DSN": dsn,
                "INSTRUMENT_MASTER_RUNTIME_DSN_FILE": str(dsn_file),
            }
        )


def test_main_uses_dedicated_dsn_and_private_provider_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Connection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    connection = _Connection()
    seen: list[tuple[str, str]] = []
    expected = InstrumentMasterPersistResult(
        run_id=UUID("00000000-0000-4000-8000-000000000001"),
        snapshot_id=None,
        disposition="NO_HEAD_CHANGE",
        terminal="INDETERMINATE",
        completeness="INDETERMINATE",
        run_disposition="NO_HEAD_CHANGE",
    )

    class _Repository:
        def __init__(self, supplied_connection: object, *, schema: str) -> None:
            assert supplied_connection is connection
            assert schema == "kunlun_instrument_provider"

        def persist_authoritative_instrument_master_run(
            self,
            raw_storage: object,
            run_id: str,
            manifest_date: str,
            manifest_capture_id: str,
        ) -> InstrumentMasterPersistResult:
            del raw_storage
            assert run_id == "00000000-0000-4000-8000-000000000001"
            assert manifest_date == "2026-09-08"
            assert manifest_capture_id == "manifest-1"
            return expected

    monkeypatch.setattr(runtime, "PostgresInstrumentMasterRepository", _Repository)
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    exit_code = runtime.main(
        [
            "--replay",
            "--run-id",
            "00000000-0000-4000-8000-000000000001",
            "--manifest-date",
            "2026-09-08",
            "--manifest-capture-id",
            "manifest-1",
        ],
        environ={
            "KUNLUN_RAW_ROOT": str(raw_root),
            "INSTRUMENT_MASTER_RUNTIME_DSN": "postgresql://dedicated-runtime",
            "KUNLUN_POSTGRES_DSN": "postgresql://shared-must-not-be-used",
        },
        connection_factory=lambda dsn, schema: (seen.append((dsn, schema)) or connection),
    )

    assert exit_code == 0
    assert seen == [("postgresql://dedicated-runtime", "kunlun_instrument_provider")]
    assert connection.closed
    assert json.loads(capsys.readouterr().out) == json.loads(runtime._safe_output(expected))


def test_run_composition_preserves_work_base_exception_when_guard_recheck_fails() -> None:
    class _WorkInterrupt(BaseException):
        pass

    class _CleanupInterrupt(BaseException):
        pass

    work_error = _WorkInterrupt()
    cleanup_error = _CleanupInterrupt()

    class _Guard:
        calls = 0

        def assert_stable(self) -> None:
            self.calls += 1
            if self.calls == 2:
                raise cleanup_error

    class _Repository:
        def persist_authoritative_instrument_master_run(
            self,
            raw_storage: object,
            run_id: str,
            manifest_date: str,
            manifest_capture_id: str,
        ) -> InstrumentMasterPersistResult:
            del raw_storage, run_id, manifest_date, manifest_capture_id
            raise work_error

    with pytest.raises(_WorkInterrupt) as error:
        runtime.run_instrument_master_once(
            raw_storage=cast(RawStorage, object()),
            repository=cast(runtime._InstrumentMasterRepository, _Repository()),
            replay=True,
            run_id="00000000-0000-4000-8000-000000000001",
            manifest_date="2026-09-08",
            manifest_capture_id="manifest-1",
            raw_guard=cast(runtime._RawRootGuard, _Guard()),
        )

    assert error.value is work_error


def test_main_reraises_work_base_exception_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _WorkInterrupt(BaseException):
        pass

    class _Connection:
        closed = False

        def close(self) -> None:
            self.closed = True

    class _Guard:
        closed = False

        def assert_stable(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    connection = _Connection()
    guard = _Guard()
    work_error = _WorkInterrupt()

    def fake_open(_: Path) -> runtime._RawRootGuard:
        return cast(runtime._RawRootGuard, guard)

    def fake_run(**_: object) -> NoReturn:
        raise work_error

    monkeypatch.setattr(runtime._RawRootGuard, "open", fake_open)
    monkeypatch.setattr(
        runtime,
        "run_instrument_master_once",
        fake_run,
    )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()

    with pytest.raises(_WorkInterrupt) as error:
        runtime.main(
            [
                "--replay",
                "--run-id",
                "00000000-0000-4000-8000-000000000001",
                "--manifest-date",
                "2026-09-08",
                "--manifest-capture-id",
                "manifest-1",
            ],
            environ={
                "KUNLUN_RAW_ROOT": str(raw_root),
                "INSTRUMENT_MASTER_RUNTIME_DSN": "postgresql://dedicated-runtime",
            },
            connection_factory=lambda _dsn, _schema: connection,
        )

    assert error.value is work_error
    assert connection.closed
    assert guard.closed


def test_raw_root_guard_close_preserves_first_base_exception_and_closes_all(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _CleanupInterrupt(BaseException):
        pass

    first_error = _CleanupInterrupt()
    calls: list[int] = []
    guard = runtime._RawRootGuard(tmp_path, (1, 1), (1, 2), 101, 102)

    def close_file_descriptor(descriptor: int) -> None:
        calls.append(descriptor)
        if descriptor == 101:
            raise first_error

    monkeypatch.setattr(runtime.os, "close", close_file_descriptor)

    with pytest.raises(_CleanupInterrupt) as error:
        guard.close()

    assert error.value is first_error
    assert calls == [101, 102]
    assert guard._closed


def test_guarded_storage_preserves_work_base_exception_when_recheck_fails() -> None:
    class _WorkInterrupt(BaseException):
        pass

    class _CleanupInterrupt(BaseException):
        pass

    work_error = _WorkInterrupt()
    cleanup_error = _CleanupInterrupt()

    class _Guard:
        calls = 0

        def assert_stable(self) -> None:
            self.calls += 1
            if self.calls == 2:
                raise cleanup_error

    guard = _Guard()
    storage = runtime._GuardedRawStorage(
        cast(RawStorage, object()), cast(runtime._RawRootGuard, guard)
    )

    def work() -> None:
        raise work_error

    with pytest.raises(_WorkInterrupt) as error:
        storage._call(work)

    assert error.value is work_error
