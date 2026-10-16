"""Bounded, lock-protected market-quality public export tests."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from data_worker.jobs.market_data.quality import MarketDataQualitySink
from data_worker.jobs.market_data.quality_export import (
    MarketQualityExportError,
    MarketQualityPublicPublisher,
    _read_limited,  # pyright: ignore[reportPrivateUsage]
    export_market_quality_evidence,
)
from data_worker.raw import LocalFileStorage
from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.storage import RawStorageError


def _manifest(
    tmp_path: Path,
    *,
    source: str = "akshare-eastmoney",
    capture_id: str = "export-capture-1",
) -> RawObjectManifest:
    return LocalFileStorage(tmp_path / "raw").put(
        source,
        "2026-08-27",
        "GET /market-data?code=600000",
        b"[]",
        content_type="application/json",
        capture_id=capture_id,
        ingest_time=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
        schema_version="market-bar-v1",
        capture_version="capture-v1",
        api_name="stock_zh_a_hist",
        unified_code="600000.SH",
        interval="DAILY",
        requested_start="2026-08-26",
        requested_end="2026-08-27",
        source_version="provider:v1",
        market_run_id="market-run-export",
        capture_ordinal=1,
    )


def _record(raw_root: Path, manifest: RawObjectManifest) -> None:
    MarketDataQualitySink(raw_root / "market-quality").record(
        manifest,
        reason_code="BAR_QUALITY_REJECTED",
        reason_detail="bar failed quality validation",
        rejected_records=[
            {
                "record": {"unifiedCode": "600000.SH", "price": 1},
                "reason": "bar quality rule",
            }
        ],
        quality_events=[
            {
                "kind": "OUT_OF_ORDER",
                "unifiedCode": "600000.SH",
                "timestamp": "2026-08-27T01:31:00Z",
                "detail": "raw detail",
            }
        ],
        recorded_at=datetime(2026, 8, 27, 4, 1, tzinfo=UTC),
    )


def test_export_publishes_hash_bound_sanitized_snapshot_without_reading_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    manifest = _manifest(tmp_path)
    _record(raw_root, manifest)

    def fail_get(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("public export must not read raw objects")

    monkeypatch.setattr(LocalFileStorage, "get", fail_get)
    result = export_market_quality_evidence(
        raw_root,
        tmp_path / "public",
        clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC),
    )

    snapshot_path = tmp_path / "public" / "snapshots" / f"{result.snapshot_id}.json"
    snapshot_bytes = snapshot_path.read_bytes()
    assert hashlib.sha256(snapshot_bytes).hexdigest() == result.snapshot_id
    assert json.loads((tmp_path / "public" / "current.json").read_text()) == {
        "schemaVersion": "market-quality-current-v1",
        "snapshotId": result.snapshot_id,
    }
    snapshot = json.loads(snapshot_bytes)
    assert snapshot["schemaVersion"] == "market-quality-snapshot-v1"
    assert snapshot["records"][0]["qualityRecordedAt"] == "2026-08-27T04:01:00Z"
    assert "export-capture-1" not in snapshot_bytes.decode()
    assert "raw detail" not in snapshot_bytes.decode()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_public_export_files_are_owner_writable_and_inputs_unchanged(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = _manifest(tmp_path)
    _record(raw_root, manifest)
    before_raw = {
        path.relative_to(raw_root): (path.stat().st_mode & 0o777, path.read_bytes())
        for path in raw_root.rglob("*")
        if path.is_file()
    }
    public_root = tmp_path / "public"

    first = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    second = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
    )

    public_files = [
        public_root / "current.json",
        public_root / "snapshots" / f"{first.snapshot_id}.json",
        public_root / "snapshots" / f"{second.snapshot_id}.json",
    ]
    assert all(path.stat().st_mode & 0o777 == 0o644 for path in public_files)
    assert public_root.stat().st_mode & 0o777 == 0o755
    assert (public_root / "snapshots").stat().st_mode & 0o777 == 0o755
    after_raw = {
        path.relative_to(raw_root): (path.stat().st_mode & 0o777, path.read_bytes())
        for path in raw_root.rglob("*")
        if path.is_file()
    }
    assert after_raw == before_raw


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_existing_public_directory_with_unsafe_mode_is_rejected(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    public_root.mkdir(mode=0o700)
    os.chmod(public_root, 0o700)

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
        )

    assert public_root.stat().st_mode & 0o777 == 0o700
    assert not (public_root / "current.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_public_export_chmod_failure_preserves_current_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    old_current = (public_root / "current.json").read_bytes()

    import data_worker.jobs.market_data.quality_export as export_module

    def fail_fchmod(_descriptor: int, _mode: int) -> None:
        raise OSError("simulated public mode failure")

    monkeypatch.setattr(export_module.os, "fchmod", fail_fchmod)
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )

    assert (public_root / "current.json").read_bytes() == old_current


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_public_current_fchmod_failure_preserves_current_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    old_current = (public_root / "current.json").read_bytes()

    import data_worker.jobs.market_data.quality_export as export_module

    original_fchmod = export_module.os.fchmod
    calls = 0

    def fail_current_fchmod(descriptor: int, mode: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated current mode failure")
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(export_module.os, "fchmod", fail_current_fchmod)
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )

    assert calls == 2
    assert (public_root / "current.json").read_bytes() == old_current


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_existing_legacy_snapshot_mode_is_not_reused(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    baseline = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    snapshot_path = public_root / "snapshots" / f"{baseline.snapshot_id}.json"
    os.chmod(snapshot_path, 0o600)
    old_current = (public_root / "current.json").read_bytes()

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
        )

    assert (public_root / "current.json").read_bytes() == old_current
    assert snapshot_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("mode", [0o700, 0o750])
@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")
def test_existing_snapshots_directory_with_unsafe_mode_is_rejected(
    tmp_path: Path, mode: int
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    snapshots_root = public_root / "snapshots"
    os.chmod(snapshots_root, mode)
    old_current = (public_root / "current.json").read_bytes()

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )

    assert snapshots_root.stat().st_mode & 0o777 == mode
    assert (public_root / "current.json").read_bytes() == old_current


def test_public_directory_creation_permission_error_is_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    original_mkdir = Path.mkdir

    def fail_public_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == public_root:
            raise PermissionError("synthetic-private-path")
        original_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", fail_public_mkdir)
    with pytest.raises(MarketQualityExportError, match="market-quality directory") as error:
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
        )

    assert "synthetic-private-path" not in str(error.value)


def test_export_accepts_existing_empty_quality_tree_and_publishes_zero_records(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)

    result = export_market_quality_evidence(
        raw_root,
        tmp_path / "public",
        clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC),
    )

    snapshot = json.loads(
        (tmp_path / "public" / "snapshots" / f"{result.snapshot_id}.json").read_text()
    )
    assert snapshot["records"] == []
    assert result.record_count == 0


def test_export_failure_preserves_previous_current_pointer(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    before = (public_root / "current.json").read_bytes()
    (raw_root / "market-quality" / "not-a-capture.json").write_text("{}")

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )
    assert (public_root / "current.json").read_bytes() == before


def test_public_current_replace_failure_preserves_old_pointer_and_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    baseline = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    old_current = (public_root / "current.json").read_bytes()
    old_snapshot = (public_root / "snapshots" / f"{baseline.snapshot_id}.json").read_bytes()

    import data_worker.jobs.market_data.quality_export as export_module

    original_replace = export_module.os.replace

    def fail_current_replace(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == public_root / "current.json":
            raise OSError("simulated current replace failure")
        original_replace(source, destination)

    monkeypatch.setattr(export_module.os, "replace", fail_current_replace)
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )

    assert (public_root / "current.json").read_bytes() == old_current
    assert (public_root / "snapshots" / f"{baseline.snapshot_id}.json").read_bytes() == old_snapshot
    assert hashlib.sha256(old_snapshot).hexdigest() == baseline.snapshot_id


def test_public_current_fsync_failure_reports_uncertain_new_pointer_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)
    public_root = tmp_path / "public"
    baseline = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )

    import data_worker.jobs.market_data.quality_export as export_module

    original_fsync_directory = export_module._fsync_directory  # pyright: ignore[reportPrivateUsage]

    def fail_public_fsync(path: Path) -> None:
        if path == public_root:
            raise OSError("simulated current directory fsync failure")
        original_fsync_directory(path)

    monkeypatch.setattr(export_module, "_fsync_directory", fail_public_fsync)
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(
            raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
        )

    current = json.loads((public_root / "current.json").read_text())
    assert current["snapshotId"] != baseline.snapshot_id
    new_snapshot = public_root / "snapshots" / f"{current['snapshotId']}.json"
    new_snapshot_bytes = new_snapshot.read_bytes()
    assert hashlib.sha256(new_snapshot_bytes).hexdigest() == current["snapshotId"]
    assert json.loads(new_snapshot_bytes)["schemaVersion"] == "market-quality-snapshot-v1"


def test_export_replay_keeps_recorded_at_and_updates_published_at(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = _manifest(tmp_path)
    _record(raw_root, manifest)
    public_root = tmp_path / "public"
    first = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC)
    )
    second = export_market_quality_evidence(
        raw_root, public_root, clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC)
    )
    first_snapshot = json.loads(
        (public_root / "snapshots" / f"{first.snapshot_id}.json").read_text()
    )
    second_snapshot = json.loads(
        (public_root / "snapshots" / f"{second.snapshot_id}.json").read_text()
    )
    assert first_snapshot["records"][0]["qualityRecordedAt"] == "2026-08-27T04:01:00Z"
    assert second_snapshot["records"][0]["qualityRecordedAt"] == "2026-08-27T04:01:00Z"
    assert first_snapshot["publishedAt"] != second_snapshot["publishedAt"]


def test_export_rejects_missing_manifest_and_wrong_manifest_digest(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    manifest = _manifest(tmp_path)
    _record(raw_root, manifest)
    manifest_path = next((raw_root / "index").rglob("*.json"))
    manifest_path.unlink()
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(raw_root, tmp_path / "public")

    manifest = _manifest(tmp_path)
    _record(raw_root, manifest)
    manifest_path = next(
        path for path in (raw_root / "index").rglob("*.json") if not path.name.startswith(".")
    )
    wrong_path = manifest_path.with_name(f"{manifest.capture_id}.{'0' * 64}.json")
    manifest_path.rename(wrong_path)
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(raw_root, tmp_path / "public-2")


def test_export_uses_one_scan_budget_for_quality_and_index_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    quality_root = raw_root / "market-quality"
    quality_root.mkdir(parents=True)
    (quality_root / "capture-1.json").write_text("{}")
    (quality_root / ".market-quality.lock").touch()
    date_root = raw_root / "index" / "akshare-eastmoney" / "2026-08-27"
    date_root.mkdir(parents=True)
    (date_root / ".capture.lock").touch()
    monkeypatch.setattr(
        "data_worker.jobs.market_data.quality_export.MARKET_QUALITY_MAX_CANDIDATE_FILES", 4
    )

    with pytest.raises(MarketQualityExportError, match="scan limit"):
        export_market_quality_evidence(raw_root, tmp_path / "public")


def test_export_rejects_quality_symlink(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    quality_root = raw_root / "market-quality"
    quality_root.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text("{}")
    try:
        (quality_root / "capture-1.json").symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(raw_root, tmp_path / "public")


def test_export_rejects_oversized_quality_input(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    quality_root = raw_root / "market-quality"
    quality_root.mkdir(parents=True)
    (quality_root / "capture-1.json").write_bytes(b"{" + b"a" * (1024 * 1024 + 1))

    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(raw_root, tmp_path / "public")


def test_public_lock_prevents_slow_old_scan_from_overwriting_new_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_root = tmp_path / "old" / "raw"
    new_root = tmp_path / "new" / "raw"
    old_manifest = _manifest(tmp_path / "old", capture_id="old-capture")
    new_manifest = _manifest(tmp_path / "new", capture_id="new-capture")
    _record(old_root, old_manifest)
    _record(new_root, new_manifest)
    public_root = tmp_path / "public"

    import data_worker.jobs.market_data.quality_export as export_module

    original_quality_files = export_module._quality_files  # pyright: ignore[reportPrivateUsage]
    first_scan_started = threading.Event()
    second_scan_started = threading.Event()
    release_first_scan = threading.Event()
    call_count = 0
    call_lock = threading.Lock()

    def gated_quality_files(path: Path, budget: object) -> list[Path]:
        nonlocal call_count
        with call_lock:
            call_count += 1
            ordinal = call_count
        if ordinal == 1:
            first_scan_started.set()
            assert release_first_scan.wait(timeout=5)
        elif ordinal == 2:
            second_scan_started.set()
        return original_quality_files(path, budget)  # type: ignore[arg-type]

    monkeypatch.setattr(export_module, "_quality_files", gated_quality_files)
    errors: list[BaseException] = []

    def run_old() -> None:
        try:
            export_market_quality_evidence(
                old_root,
                public_root,
                clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC),
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    def run_new() -> None:
        try:
            export_market_quality_evidence(
                new_root,
                public_root,
                clock=lambda: datetime(2026, 8, 27, 4, 3, tzinfo=UTC),
            )
        except BaseException as error:  # pragma: no cover - assertion below reports it
            errors.append(error)

    old_thread = threading.Thread(target=run_old)
    new_thread = threading.Thread(target=run_new)
    old_thread.start()
    assert first_scan_started.wait(timeout=5)
    new_thread.start()
    time.sleep(0.1)
    assert not second_scan_started.is_set()
    release_first_scan.set()
    old_thread.join(timeout=5)
    new_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert not new_thread.is_alive()
    assert errors == []

    current = json.loads((public_root / "current.json").read_text())
    final_snapshot = json.loads(
        (public_root / "snapshots" / f"{current['snapshotId']}.json").read_text()
    )
    assert final_snapshot["publishedAt"] == "2026-08-27T04:03:00Z"
    assert final_snapshot["records"][0]["evidenceId"] != ""


def test_public_lock_timeout_is_a_controlled_export_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = tmp_path / "raw"
    (raw_root / "market-quality").mkdir(parents=True)

    @contextmanager
    def fail_lock(_path: Path):
        raise RawStorageError("timed out waiting for lock")
        yield

    monkeypatch.setattr(LocalFileStorage, "_exclusive_lock", staticmethod(fail_lock))
    with pytest.raises(MarketQualityExportError):
        export_market_quality_evidence(raw_root, tmp_path / "public")


def test_limited_read_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO is unavailable")

    fifo = tmp_path / "candidate.json"
    os.mkfifo(fifo)
    with pytest.raises(MarketQualityExportError):
        _read_limited(fifo, 1024)


@pytest.mark.parametrize("deny_replacement", [False, True])
def test_limited_read_rejects_path_replacement_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, deny_replacement: bool
) -> None:
    path = tmp_path / "candidate.json"
    path.write_bytes(b"old")
    original_read = os.read
    swapped = False
    replacement_denied = False

    def read_and_swap(descriptor: int, size: int) -> bytes:
        nonlocal swapped, replacement_denied
        data = original_read(descriptor, size)
        if not swapped:
            swapped = True
            replacement = tmp_path / "replacement.json"
            replacement.write_bytes(b"new")
            try:
                if deny_replacement:
                    raise PermissionError("open file replacement denied")
                path.unlink()
                os.replace(replacement, path)
            except PermissionError:
                # Windows can deny removal of the still-open file. Both that
                # denial and a successful POSIX replacement must fail closed.
                replacement_denied = True
                raise
        return data

    monkeypatch.setattr("data_worker.jobs.market_data.quality_export.os.read", read_and_swap)
    with pytest.raises(MarketQualityExportError) as rejected:
        _read_limited(path, 1024)
    if replacement_denied:
        assert str(rejected.value) == "market-quality candidate cannot be read"
        assert isinstance(rejected.value.__cause__, PermissionError)
        assert path.read_bytes() == b"old"
    else:
        assert str(rejected.value) == "market-quality candidate changed during read"
        assert path.read_bytes() == b"new"


def test_runtime_publisher_initializes_clean_quality_tree_for_zero_snapshot(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "runtime-raw"
    public_root = tmp_path / "runtime-public"
    publisher = MarketQualityPublicPublisher(
        raw_root,
        public_root,
        clock=lambda: datetime(2026, 8, 27, 4, 2, tzinfo=UTC),
    )

    result = publisher.publish_cycle()

    assert result is not None
    assert result.record_count == 0
    assert (raw_root / "market-quality").is_dir()


def test_runtime_publisher_rejects_relative_or_overlapping_roots(tmp_path: Path) -> None:
    with pytest.raises(MarketQualityExportError):
        MarketQualityPublicPublisher(Path("relative-raw"), tmp_path / "public")
    with pytest.raises(MarketQualityExportError):
        MarketQualityPublicPublisher(tmp_path / "raw", tmp_path / "raw" / "public")
