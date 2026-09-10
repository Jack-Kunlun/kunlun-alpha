"""Bounded offline publication of sanitized market-quality snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ashare_contracts.data_quality_market_quality_evidence import (
    MarketQualityEvidenceCurrent,
    MarketQualityEvidenceSnapshot,
)
from data_worker.jobs.market_data.quality_projection import (
    MARKET_QUALITY_CURRENT_SCHEMA_VERSION,
    MARKET_QUALITY_MAX_BYTES,
    MARKET_QUALITY_MAX_CANDIDATE_FILES,
    MARKET_QUALITY_MAX_INPUT_BYTES,
    MARKET_QUALITY_MAX_RECORDS,
    MARKET_QUALITY_SNAPSHOT_SCHEMA_VERSION,
    MARKET_QUALITY_SOURCES,
    MarketQualityProjectionError,
    project_market_quality_evidence,
)
from data_worker.raw.manifest import (
    RawObjectManifest,
    validate_date_identifier,
    validate_identifier,
)
from data_worker.raw.storage import LocalFileStorage, RawStorageError

Clock = Callable[[], datetime]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MANIFEST_RE = re.compile(
    r"^(?P<capture>[A-Za-z0-9][A-Za-z0-9._-]*)\.(?P<digest>[0-9a-f]{64})\.json$"
)
_QUALITY_CAPTURE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_QUALITY_LOCK_NAME = ".market-quality.lock"
_LOCK_NAME_RE = re.compile(r"^\.[A-Za-z0-9._-]+\.lock$")
_PUBLIC_DIRECTORY_MODE = 0o755
_PUBLIC_FILE_MODE = 0o644


class MarketQualityExportError(RuntimeError):
    """A complete public snapshot could not be safely published."""


@dataclass(frozen=True, slots=True)
class MarketQualityExportResult:
    """Non-secret result of one offline export attempt."""

    snapshot_id: str
    published_at: datetime
    record_count: int


@dataclass(slots=True)
class _ScanBudget:
    """Bound every directory entry observed during one export attempt."""

    count: int = 0

    def consume(self) -> None:
        self.count += 1
        if self.count > MARKET_QUALITY_MAX_CANDIDATE_FILES:
            raise MarketQualityExportError("market-quality scan limit exceeded")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise MarketQualityExportError(
            "market-quality snapshot is not JSON serializable"
        ) from error
    return encoded.encode("utf-8")


def _ensure_no_symlink_components(path: Path) -> None:
    """Reject symlink path components before opening or creating a file."""

    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break
        except OSError as error:
            raise MarketQualityExportError("market-quality path is unavailable") from error
        if stat.S_ISLNK(mode):
            raise MarketQualityExportError("market-quality symlink path is not allowed")


def _require_directory(path: Path, *, allow_missing: bool) -> None:
    _ensure_no_symlink_components(path)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        if allow_missing:
            return
        raise MarketQualityExportError("market-quality directory is missing") from None
    except OSError as error:
        raise MarketQualityExportError("market-quality directory is unavailable") from error
    if not stat.S_ISDIR(mode):
        raise MarketQualityExportError("market-quality path is not a directory")


def _ensure_public_directory(path: Path) -> None:
    """Create a public directory with explicit mode or reject unsafe existing mode."""

    _ensure_no_symlink_components(path)
    created = False
    try:
        os.lstat(path)
    except FileNotFoundError:
        try:
            path.mkdir(parents=True, exist_ok=False, mode=_PUBLIC_DIRECTORY_MODE)
        except FileExistsError:
            pass
        except OSError as error:
            raise MarketQualityExportError("market-quality directory cannot be created") from error
        else:
            created = True
    except OSError as error:
        raise MarketQualityExportError("market-quality directory is unavailable") from error
    _require_directory(path, allow_missing=False)
    if os.name == "nt":
        return
    if created:
        try:
            os.chmod(path, _PUBLIC_DIRECTORY_MODE)
        except OSError as error:
            raise MarketQualityExportError(
                "market-quality directory mode is unavailable"
            ) from error
    try:
        mode = os.lstat(path).st_mode
    except OSError as error:
        raise MarketQualityExportError("market-quality directory is unavailable") from error
    if stat.S_IMODE(mode) != _PUBLIC_DIRECTORY_MODE:
        raise MarketQualityExportError("market-quality directory mode is invalid")


def _require_public_file_mode(path: Path) -> None:
    """Require the fixed public-file mode before reusing an existing snapshot."""

    if os.name == "nt":
        return
    _ensure_no_symlink_components(path)
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise MarketQualityExportError("market-quality public file is unavailable") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise MarketQualityExportError("market-quality public file is not regular")
    if stat.S_IMODE(metadata.st_mode) != _PUBLIC_FILE_MODE:
        raise MarketQualityExportError("market-quality public file mode is invalid")


def _read_limited(path: Path, maximum: int) -> bytes:
    _ensure_no_symlink_components(path)
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise MarketQualityExportError("market-quality candidate cannot be inspected") from error
    if not stat.S_ISREG(path_stat.st_mode):
        raise MarketQualityExportError("market-quality candidate is not a regular file")
    path_identity = (path_stat.st_dev, path_stat.st_ino)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise MarketQualityExportError("market-quality candidate is not a regular file")
        if (metadata.st_dev, metadata.st_ino) != path_identity:
            raise MarketQualityExportError("market-quality candidate changed during read")
        if metadata.st_size > maximum:
            raise MarketQualityExportError("market-quality candidate exceeds the size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise MarketQualityExportError("market-quality candidate exceeds the size limit")
        final_metadata = os.fstat(descriptor)
        if (final_metadata.st_dev, final_metadata.st_ino) != path_identity:
            raise MarketQualityExportError("market-quality candidate changed during read")
        try:
            final_path_stat = os.lstat(path)
        except OSError as error:
            raise MarketQualityExportError(
                "market-quality candidate changed during read"
            ) from error
        if (final_path_stat.st_dev, final_path_stat.st_ino) != path_identity:
            raise MarketQualityExportError("market-quality candidate changed during read")
        return b"".join(chunks)
    except MarketQualityExportError:
        raise
    except (OSError, ValueError) as error:
        raise MarketQualityExportError("market-quality candidate cannot be read") from error
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _read_json(path: Path, maximum: int) -> Mapping[str, object]:
    raw_bytes = _read_limited(path, maximum)
    try:
        value: object = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MarketQualityExportError("market-quality JSON is invalid") from error
    if not isinstance(value, Mapping):
        raise MarketQualityExportError("market-quality JSON must be an object")
    return cast(Mapping[str, object], value)


def _entry_is_lock(name: str) -> bool:
    return _LOCK_NAME_RE.fullmatch(name) is not None


def _directory_entries(path: Path, budget: _ScanBudget) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(path) as iterator:
            entries: list[os.DirEntry[str]] = []
            for entry in iterator:
                budget.consume()
                entries.append(entry)
            return sorted(entries, key=lambda entry: entry.name)
    except OSError as error:
        raise MarketQualityExportError("market-quality directory cannot be scanned") from error


def _reject_symlink(entry: os.DirEntry[str]) -> None:
    try:
        if entry.is_symlink():
            raise MarketQualityExportError("market-quality symlink candidate is not allowed")
    except OSError as error:
        raise MarketQualityExportError("market-quality candidate cannot be inspected") from error


def _quality_files(quality_root: Path, budget: _ScanBudget) -> list[Path]:
    _require_directory(quality_root, allow_missing=False)
    candidates: list[Path] = []
    for entry in _directory_entries(quality_root, budget):
        _reject_symlink(entry)
        if _entry_is_lock(entry.name):
            if not entry.is_file(follow_symlinks=False):
                raise MarketQualityExportError("market-quality lock is invalid")
            continue
        if not entry.name.endswith(".json") or not entry.is_file(follow_symlinks=False):
            raise MarketQualityExportError("market-quality directory contains an unknown file")
        capture_id = entry.name[:-5]
        if _QUALITY_CAPTURE_RE.fullmatch(capture_id) is None:
            raise MarketQualityExportError("market-quality quality filename is invalid")
        validate_identifier(capture_id, "capture_id")
        candidates.append(quality_root / entry.name)
    return candidates


def _manifest_files(
    raw_root: Path, budget: _ScanBudget, needed_captures: set[str]
) -> dict[str, RawObjectManifest]:
    index_root = raw_root / "index"
    _require_directory(index_root, allow_missing=False)
    result: dict[str, RawObjectManifest] = {}
    seen_captures: set[str] = set()
    for source_entry in _directory_entries(index_root, budget):
        _reject_symlink(source_entry)
        if not source_entry.is_dir(follow_symlinks=False):
            raise MarketQualityExportError("market-quality index contains an unknown entry")
        source = source_entry.name
        if source not in MARKET_QUALITY_SOURCES:
            raise MarketQualityExportError("market-quality index source is unsupported")
        source_root = index_root / source
        for date_entry in _directory_entries(source_root, budget):
            _reject_symlink(date_entry)
            if not date_entry.is_dir(follow_symlinks=False):
                raise MarketQualityExportError("market-quality index date is invalid")
            collection_date = date_entry.name
            if _DATE_RE.fullmatch(collection_date) is None:
                raise MarketQualityExportError("market-quality index date is invalid")
            validate_date_identifier(collection_date)
            date_root = source_root / collection_date
            for manifest_entry in _directory_entries(date_root, budget):
                _reject_symlink(manifest_entry)
                if _entry_is_lock(manifest_entry.name):
                    if not manifest_entry.is_file(follow_symlinks=False):
                        raise MarketQualityExportError("market-quality index lock is invalid")
                    continue
                if not manifest_entry.name.endswith(".json") or not manifest_entry.is_file(
                    follow_symlinks=False
                ):
                    raise MarketQualityExportError("market-quality index contains an unknown file")
                match = _MANIFEST_RE.fullmatch(manifest_entry.name)
                if match is None:
                    raise MarketQualityExportError("market-quality manifest filename is invalid")
                manifest_path = date_root / manifest_entry.name
                raw_manifest = _read_json(manifest_path, MARKET_QUALITY_MAX_INPUT_BYTES)
                try:
                    manifest = RawObjectManifest.from_dict(raw_manifest)
                except (TypeError, ValueError, KeyError) as error:
                    raise MarketQualityExportError("market-quality manifest is invalid") from error
                if (
                    manifest.capture_id != match.group("capture")
                    or manifest.content_digest() != match.group("digest")
                    or manifest.source != source
                    or manifest.date != collection_date
                    or not manifest.is_market_capture
                ):
                    raise MarketQualityExportError("market-quality manifest binding is invalid")
                if manifest.capture_id in seen_captures:
                    raise MarketQualityExportError("market-quality capture identity is ambiguous")
                seen_captures.add(manifest.capture_id)
                if manifest.capture_id in needed_captures:
                    result[manifest.capture_id] = manifest
    return result


def _load_current(public_root: Path) -> None:
    current_path = public_root / "current.json"
    try:
        os.lstat(current_path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise MarketQualityExportError("market-quality current pointer is unavailable") from error
    current = _read_json(current_path, MARKET_QUALITY_MAX_INPUT_BYTES)
    try:
        pointer = MarketQualityEvidenceCurrent.model_validate(current)
    except Exception as error:
        raise MarketQualityExportError("market-quality current pointer is invalid") from error
    snapshot_id = pointer.snapshot_id
    snapshot_path = public_root / "snapshots" / f"{snapshot_id}.json"
    snapshot_bytes = _read_limited(snapshot_path, MARKET_QUALITY_MAX_BYTES)
    if hashlib.sha256(snapshot_bytes).hexdigest() != snapshot_id:
        raise MarketQualityExportError("market-quality current snapshot digest is invalid")
    try:
        MarketQualityEvidenceSnapshot.model_validate(json.loads(snapshot_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as error:
        raise MarketQualityExportError("market-quality current snapshot is invalid") from error


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        raise MarketQualityExportError("market-quality directory sync is unavailable") from error
    try:
        os.fsync(descriptor)
    except OSError as error:
        raise MarketQualityExportError("market-quality directory sync is unavailable") from error
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: bytes) -> None:
    _ensure_no_symlink_components(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MarketQualityExportError("market-quality directory cannot be created") from error
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".market-quality-", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            fchmod = getattr(os, "fchmod", None)
            if fchmod is None:
                os.chmod(temporary.name, _PUBLIC_FILE_MODE)
            else:
                fchmod(temporary.fileno(), _PUBLIC_FILE_MODE)
            temporary.flush()
            os.fsync(temporary.fileno())
        if path.exists() or path.is_symlink():
            _ensure_no_symlink_components(path)
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(path.parent)
    except MarketQualityExportError:
        raise
    except OSError as error:
        raise MarketQualityExportError("market-quality atomic publish failed") from error
    finally:
        if temporary_path is not None:
            with suppress(FileNotFoundError):
                temporary_path.unlink()


def _validate_roots(raw_root: Path, public_root: Path) -> tuple[Path, Path]:
    raw = Path(raw_root)
    public = Path(public_root)
    if not raw.is_absolute() or not public.is_absolute():
        raise MarketQualityExportError("market-quality roots must be absolute")
    _ensure_no_symlink_components(raw)
    _ensure_no_symlink_components(public)
    raw_abs = Path(os.path.abspath(raw))
    public_abs = Path(os.path.abspath(public))
    if raw_abs == public_abs or raw_abs in public_abs.parents or public_abs in raw_abs.parents:
        raise MarketQualityExportError("market-quality roots must not overlap")
    _require_directory(raw_abs, allow_missing=False)
    _require_directory(public_abs, allow_missing=True)
    return raw_abs, public_abs


def _export_locked(raw: Path, public: Path, *, clock: Clock) -> MarketQualityExportResult:
    """Scan and publish while holding the public snapshot lock."""

    scan_budget = _ScanBudget()
    quality_paths = _quality_files(raw / "market-quality", scan_budget)
    if quality_paths:
        manifests = _manifest_files(raw, scan_budget, {path.stem for path in quality_paths})
    else:
        manifests = {}

    # Read the complete bounded input set before taking the service clock. A
    # capture written during a slow scan must not appear to be from the future.
    published_at = clock()
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise MarketQualityExportError("market-quality clock must be timezone-aware")
    published_at = published_at.astimezone(UTC)

    records: list[dict[str, object]] = []
    if len(quality_paths) > MARKET_QUALITY_MAX_RECORDS:
        raise MarketQualityExportError("market-quality record limit exceeded")
    projected_bytes = 0
    for quality_path in quality_paths:
        quality = _read_json(quality_path, MARKET_QUALITY_MAX_INPUT_BYTES)
        filename_capture_id = quality_path.stem
        capture_id = quality.get("captureId")
        if capture_id != filename_capture_id or not isinstance(capture_id, str):
            raise MarketQualityExportError("market-quality quality filename binding is invalid")
        manifest = manifests.get(capture_id)
        if manifest is None:
            raise MarketQualityExportError("market-quality manifest for evidence is missing")
        try:
            record = project_market_quality_evidence(quality, manifest, published_at=published_at)
        except MarketQualityProjectionError as error:
            raise MarketQualityExportError("market-quality evidence projection failed") from error
        record_bytes = _canonical_json(record)
        projected_bytes += len(record_bytes)
        if projected_bytes > MARKET_QUALITY_MAX_BYTES:
            raise MarketQualityExportError("market-quality projected records exceed the size limit")
        records.append(record)
    records.sort(key=lambda record: cast(str, record["evidenceId"]))

    snapshot_payload: dict[str, object] = {
        "schemaVersion": MARKET_QUALITY_SNAPSHOT_SCHEMA_VERSION,
        "publishedAt": published_at.isoformat(),
        "records": records,
    }
    try:
        snapshot = MarketQualityEvidenceSnapshot.model_validate(snapshot_payload)
    except Exception as error:
        raise MarketQualityExportError("market-quality snapshot is invalid") from error
    snapshot_bytes = _canonical_json(
        cast(dict[str, object], snapshot.model_dump(by_alias=True, mode="json"))
    )
    if len(snapshot_bytes) > MARKET_QUALITY_MAX_BYTES:
        raise MarketQualityExportError("market-quality snapshot exceeds the size limit")
    snapshot_id = hashlib.sha256(snapshot_bytes).hexdigest()
    pointer_payload = {
        "schemaVersion": MARKET_QUALITY_CURRENT_SCHEMA_VERSION,
        "snapshotId": snapshot_id,
    }
    try:
        pointer = MarketQualityEvidenceCurrent.model_validate(pointer_payload)
    except Exception as error:
        raise MarketQualityExportError("market-quality current pointer is invalid") from error
    pointer_bytes = _canonical_json(
        cast(dict[str, object], pointer.model_dump(by_alias=True, mode="json"))
    )

    snapshots_root = public / "snapshots"
    _ensure_public_directory(snapshots_root)
    try:
        _load_current(public)
        snapshot_path = snapshots_root / f"{snapshot_id}.json"
        if snapshot_path.exists() or snapshot_path.is_symlink():
            _require_public_file_mode(snapshot_path)
            existing = _read_limited(snapshot_path, MARKET_QUALITY_MAX_BYTES)
            if existing != snapshot_bytes:
                raise MarketQualityExportError("market-quality snapshot identity is conflicted")
        else:
            _atomic_write(snapshot_path, snapshot_bytes)
        _atomic_write(public / "current.json", pointer_bytes)
    except MarketQualityExportError:
        raise
    except (OSError, RawStorageError, ValueError) as error:
        raise MarketQualityExportError("market-quality public publish failed") from error
    return MarketQualityExportResult(snapshot_id, published_at, len(records))


def export_market_quality_evidence(
    raw_root: Path,
    public_root: Path,
    *,
    clock: Clock = _utc_now,
) -> MarketQualityExportResult:
    """Scan raw quality/manifest metadata and atomically publish one snapshot."""

    raw, public = _validate_roots(raw_root, public_root)
    _ensure_no_symlink_components(public)
    _ensure_public_directory(public)
    lock_path = public / _QUALITY_LOCK_NAME
    _ensure_no_symlink_components(lock_path)
    try:
        with LocalFileStorage._exclusive_lock(lock_path):  # pyright: ignore[reportPrivateUsage]
            return _export_locked(raw, public, clock=clock)
    except MarketQualityExportError:
        raise
    except (OSError, RawStorageError, ValueError) as error:
        raise MarketQualityExportError("market-quality public publish failed") from error


class MarketQualityPublicPublisher:
    """Runtime hook that publishes only when explicitly configured."""

    def __init__(self, raw_root: Path, public_root: Path, *, clock: Clock = _utc_now) -> None:
        self._raw_root = Path(raw_root)
        self._public_root = Path(public_root)
        if not self._raw_root.is_absolute() or not self._public_root.is_absolute():
            raise MarketQualityExportError("market-quality roots must be absolute")
        raw_abs = Path(os.path.abspath(self._raw_root))
        public_abs = Path(os.path.abspath(self._public_root))
        if raw_abs == public_abs or raw_abs in public_abs.parents or public_abs in raw_abs.parents:
            raise MarketQualityExportError("market-quality roots must not overlap")
        self._prepare_runtime_quality_root()
        # Validate the explicit mount before the first capture reaches the
        # collector. Offline export itself still rejects a missing quality tree.
        _validate_roots(self._raw_root, self._public_root)
        self._clock = clock
        self._cycle_had_publish = False

    def _prepare_runtime_quality_root(self) -> None:
        quality_root = self._raw_root / "market-quality"
        _ensure_no_symlink_components(self._raw_root)
        _ensure_no_symlink_components(quality_root)
        try:
            self._raw_root.mkdir(parents=True, exist_ok=True)
            quality_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise MarketQualityExportError(
                "market-quality runtime directory is unavailable"
            ) from error
        _require_directory(self._raw_root, allow_missing=False)
        _require_directory(quality_root, allow_missing=False)

    def publish_capture(self) -> MarketQualityExportResult:
        result = export_market_quality_evidence(
            self._raw_root, self._public_root, clock=self._clock
        )
        self._cycle_had_publish = True
        return result

    def publish_cycle(self) -> MarketQualityExportResult | None:
        if self._cycle_had_publish:
            self._cycle_had_publish = False
            return None
        result = export_market_quality_evidence(
            self._raw_root, self._public_root, clock=self._clock
        )
        self._cycle_had_publish = False
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish sanitized market-quality evidence.")
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--public-root", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        result = export_market_quality_evidence(arguments.raw_root, arguments.public_root)
    except MarketQualityExportError:
        raise SystemExit("market-quality export failed") from None
    print(
        json.dumps(
            {
                "published": True,
                "snapshotId": result.snapshot_id,
                "recordCount": result.record_count,
            },
            sort_keys=True,
        )
    )


__all__ = [
    "MarketQualityExportError",
    "MarketQualityExportResult",
    "MarketQualityPublicPublisher",
    "export_market_quality_evidence",
    "main",
]
