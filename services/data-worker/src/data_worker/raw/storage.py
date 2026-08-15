"""Immutable raw-object and capture-manifest storage.

``LocalFileStorage`` keeps one content-addressed object for each SHA-256
payload and one independently keyed manifest for every response capture.  A
capture id (or explicit idempotency key) is the retry boundary; payload bytes
never decide whether two response events are the same event.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, cast

from data_worker.raw.manifest import (
    SOURCE_REVISION_SENTINEL,
    RawObjectManifest,
    utc_now,
    validate_date_identifier,
    validate_fund_endpoint_kind,
    validate_identifier,
)

_LOCK_WAIT_SECONDS = 2.0
_LOCK_POLL_SECONDS = 0.01
_MANIFEST_NAME_RE = re.compile(
    r"^(?P<capture>[A-Za-z0-9][A-Za-z0-9._-]*)\.(?P<digest>[0-9a-f]{64})\.json$"
)
_LEGACY_MANIFEST_NAME_RE = re.compile(r"^(?P<object>[0-9a-f]{64})\.json$")


class RawIntegrityError(ValueError):
    """Stored bytes or metadata failed an integrity check."""


class RawStorageError(RuntimeError):
    """The storage backend could not safely publish an immutable file."""


class CaptureConflictError(ValueError):
    """An idempotent capture id was reused for a different response event."""


def content_id(content: object) -> str:
    """Return the content-addressed SHA-256 object id."""

    if not isinstance(content, bytes):
        raise TypeError("raw content must be bytes")
    return hashlib.sha256(content).hexdigest()


def _canonical_bytes(data: Mapping[str, object]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _acquire_os_lock(handle: BinaryIO) -> None:
    """Acquire one byte using the platform's standard-library lock API."""

    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_os_lock(handle: BinaryIO) -> None:
    """Release one byte previously acquired by :func:`_acquire_os_lock`."""

    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RawStorage(ABC):
    """Immutable raw object store interface."""

    @abstractmethod
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
    ) -> RawObjectManifest:
        """Store a response and return its immutable capture manifest."""

    @abstractmethod
    def get(
        self,
        object_id: str,
        *,
        checksum: str | None = None,
        size: int | None = None,
    ) -> bytes:
        """Retrieve bytes, validating checksum and optional manifest size."""

    @abstractmethod
    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        """List capture manifests in deterministic ingest-time/capture order."""


class LocalFileStorage(RawStorage):
    """Filesystem-backed raw storage with capture-level OS locking.

    Layout: ``<root>/objects/<object_id>`` contains immutable bytes,
    ``<root>/index/<source>/<date>/<capture_id>.<manifest_digest>.json``
    contains one content-bound manifest per response capture, and
    ``<root>/pending/<source>/<date>/<capture_id>.<pending_digest>.json`` is a
    crash-recoverable intent written before object publication.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._objects = self._root / "objects"
        self._index = self._root / "index"
        self._pending = self._root / "pending"

    def _object_path(self, object_id: str) -> Path:
        validate_identifier(object_id, "object_id", max_length=64)
        return self._objects / object_id

    def _index_dir(self, source: str, date: str) -> Path:
        validate_identifier(source, "source")
        validate_date_identifier(date)
        return self._index / source / date

    def _pending_dir(self, source: str, date: str) -> Path:
        validate_identifier(source, "source")
        validate_date_identifier(date)
        return self._pending / source / date

    def _capture_lock_path(self, source: str, date: str, capture_id: str) -> Path:
        validate_identifier(capture_id, "capture_id")
        return self._index_dir(source, date) / f".{capture_id}.lock"

    @staticmethod
    @contextmanager
    def _exclusive_lock(path: Path) -> Generator[None, None, None]:
        """Acquire a bounded, OS-backed exclusive lock.

        The lock marker is intentionally persistent; ownership is the OS file
        lock, which is released automatically when a process exits.  We never
        infer ownership from mtime and never steal a live lock.
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        handle: BinaryIO = os.fdopen(descriptor, "r+b", closefd=True)
        acquired = False
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\x00")
                handle.flush()
            handle.seek(0)
            deadline = time.monotonic() + _LOCK_WAIT_SECONDS
            while not acquired:
                try:
                    _acquire_os_lock(handle)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise RawStorageError(f"timed out waiting for lock: {path.name}") from exc
                    time.sleep(_LOCK_POLL_SECONDS)
            try:
                yield
            finally:
                if acquired:
                    with suppress(OSError):
                        _release_os_lock(handle)
        finally:
            handle.close()

    @staticmethod
    def _capture_id(
        capture_id: str | None,
        idempotency_key: str | None,
    ) -> str:
        if capture_id is not None and idempotency_key is not None:
            raise ValueError("provide capture_id or idempotency_key, not both")
        if capture_id is not None:
            return validate_identifier(capture_id, "capture_id")
        if idempotency_key is not None:
            if not idempotency_key or "\x00" in idempotency_key:
                raise ValueError("idempotency_key must be a non-empty string")
            if any(ord(char) < 32 or ord(char) == 127 for char in idempotency_key):
                raise ValueError("idempotency_key contains an unsafe control character")
            # Keep generated ids bounded for portable manifest filenames.  A
            # 128-bit digest remains collision-resistant for an idempotency
            # namespace while fitting Windows MAX_PATH alongside the full
            # content-bound manifest digest.
            digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
            return f"idem-{digest}"
        return uuid.uuid4().hex

    @staticmethod
    def _write_exclusive(path: Path, data: bytes) -> bool:
        """Atomically publish *data* if *path* does not already exist."""

        path.parent.mkdir(parents=True, exist_ok=True)
        target_lock = path.with_name(
            f".{hashlib.sha256(path.name.encode('utf-8')).hexdigest()}.lock"
        )
        temporary_path: Path | None = None
        with LocalFileStorage._exclusive_lock(target_lock):
            try:
                if path.exists():
                    return False
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=path.parent,
                    # Keep the temporary basename short: content-bound
                    # pending names are intentionally long and Windows still
                    # enforces MAX_PATH for the complete temporary path.
                    prefix=".raw-",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    temporary.write(data)
                    temporary.flush()
                    os.fsync(temporary.fileno())

                assert temporary_path is not None
                try:
                    os.link(temporary_path, path)
                    return True
                except FileExistsError:
                    return False
                except OSError:
                    # Hard-link-unavailable filesystems use an atomic rename
                    # while the target lock is held.  All writers use this
                    # same lock, so the no-target check cannot be overtaken by
                    # another cooperative publisher.
                    if path.exists():
                        return False
                    os.replace(temporary_path, path)
                    return True
            finally:
                if temporary_path is not None:
                    with suppress(FileNotFoundError):
                        temporary_path.unlink()

    @staticmethod
    def _read_json_object(path: Path) -> Mapping[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RawIntegrityError(f"invalid raw metadata: {path.name}") from exc
        if not isinstance(raw, dict):
            raise RawIntegrityError(f"raw metadata must be an object: {path.name}")
        return cast(Mapping[str, object], raw)

    @staticmethod
    def _read_manifest(path: Path) -> RawObjectManifest:
        try:
            return RawObjectManifest.from_dict(LocalFileStorage._read_json_object(path))
        except (KeyError, TypeError, ValueError) as exc:
            raise RawIntegrityError(f"invalid raw capture manifest: {path.name}") from exc

    @staticmethod
    def _parse_bound_filename(path: Path) -> tuple[str, str]:
        match = _MANIFEST_NAME_RE.fullmatch(path.name)
        if match is None:
            raise RawIntegrityError(f"manifest filename binding is invalid: {path.name}")
        return match.group("capture"), match.group("digest")

    @staticmethod
    def _read_bound_manifest(path: Path) -> RawObjectManifest:
        capture_id, digest = LocalFileStorage._parse_bound_filename(path)
        manifest = LocalFileStorage._read_manifest(path)
        if manifest.capture_id != capture_id or manifest.content_digest() != digest:
            raise RawIntegrityError(f"manifest filename/content digest mismatch: {path.name}")
        return manifest

    @staticmethod
    def _read_legacy_manifest(path: Path) -> RawObjectManifest:
        match = _LEGACY_MANIFEST_NAME_RE.fullmatch(path.name)
        if match is None:
            raise RawIntegrityError(f"legacy manifest filename is invalid: {path.name}")
        expected_object_id = match.group("object")
        raw = LocalFileStorage._read_json_object(path)
        object_id = raw.get("object_id")
        checksum = raw.get("checksum")
        if object_id != expected_object_id or checksum != expected_object_id:
            raise RawIntegrityError(
                f"legacy manifest filename/object binding mismatch: {path.name}"
            )
        date_value = raw.get("date")
        try:
            date = validate_date_identifier(date_value)
            fallback_time = datetime.fromisoformat(f"{date}T00:00:00+00:00")
            legacy_raw = dict(raw)
            legacy_raw["capture_id"] = f"legacy-object-{expected_object_id[:32]}"
            if "ingest_time" not in raw or "available_time" not in raw:
                legacy_raw["ingest_time"] = fallback_time.isoformat()
                legacy_raw["available_time"] = fallback_time.isoformat()
            return RawObjectManifest.from_dict(legacy_raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise RawIntegrityError(f"invalid legacy capture manifest: {path.name}") from exc

    @staticmethod
    def _read_manifest_file(path: Path) -> RawObjectManifest:
        if _MANIFEST_NAME_RE.fullmatch(path.name) is not None:
            return LocalFileStorage._read_bound_manifest(path)
        return LocalFileStorage._read_legacy_manifest(path)

    @staticmethod
    def _same_capture(left: RawObjectManifest, right: RawObjectManifest) -> bool:
        """Compare immutable event identity while tolerating retry timestamps."""

        return (
            left.capture_id == right.capture_id
            and left.object_id == right.object_id
            and left.source == right.source
            and left.date == right.date
            and left.request == right.request
            and left.checksum == right.checksum
            and left.size == right.size
            and left.content_type == right.content_type
            and left.endpoint_kind == right.endpoint_kind
            and left.run_id == right.run_id
            and left.source_revision == right.source_revision
            and left.attempt_id == right.attempt_id
            and left.page_ordinal == right.page_ordinal
        )

    @staticmethod
    def _pending_payload(manifest: RawObjectManifest) -> dict[str, object]:
        payload = manifest.to_dict()
        payload["manifest_digest"] = manifest.content_digest()
        return payload

    def _pending_path(self, manifest: RawObjectManifest) -> Path:
        payload = self._pending_payload(manifest)
        digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
        return self._pending_dir(manifest.source, manifest.date) / (
            f"{manifest.capture_id}.{digest}.json"
        )

    @staticmethod
    def _read_bound_pending(path: Path) -> RawObjectManifest:
        capture_id, digest = LocalFileStorage._parse_bound_filename(path)
        raw = LocalFileStorage._read_json_object(path)
        manifest_digest = raw.get("manifest_digest")
        if not isinstance(manifest_digest, str):
            raise RawIntegrityError(f"pending intent missing manifest digest: {path.name}")
        manifest = LocalFileStorage._read_manifest(path)
        if manifest.capture_id != capture_id or manifest.content_digest() != manifest_digest:
            raise RawIntegrityError(f"pending intent binding mismatch: {path.name}")
        if hashlib.sha256(_canonical_bytes(raw)).hexdigest() != digest:
            raise RawIntegrityError(f"pending intent filename digest mismatch: {path.name}")
        return manifest

    def _find_manifest(
        self, source: str, date: str, capture_id: str
    ) -> tuple[Path, RawObjectManifest] | None:
        index_dir = self._index_dir(source, date)
        if not index_dir.exists():
            return None
        matches: list[tuple[Path, RawObjectManifest]] = []
        for path in index_dir.glob("*.json"):
            manifest = self._read_manifest_file(path)
            if manifest.capture_id == capture_id:
                matches.append((path, manifest))
        if len(matches) > 1:
            raise RawIntegrityError(f"multiple manifests for capture_id {capture_id!r}")
        return matches[0] if matches else None

    def _find_pending(
        self, source: str, date: str, capture_id: str
    ) -> tuple[Path, RawObjectManifest] | None:
        pending_dir = self._pending_dir(source, date)
        if not pending_dir.exists():
            return None
        matches: list[tuple[Path, RawObjectManifest]] = []
        for path in pending_dir.glob("*.json"):
            manifest = self._read_bound_pending(path)
            if manifest.capture_id == capture_id:
                matches.append((path, manifest))
        if len(matches) > 1:
            raise RawIntegrityError(f"multiple pending intents for capture_id {capture_id!r}")
        return matches[0] if matches else None

    @staticmethod
    def _manifest_bytes(manifest: RawObjectManifest) -> bytes:
        return json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )

    @staticmethod
    def _pending_bytes(manifest: RawObjectManifest) -> bytes:
        return json.dumps(
            LocalFileStorage._pending_payload(manifest),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")

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
    ) -> RawObjectManifest:
        """Store one response under a capture-level transaction lock."""

        validate_identifier(source, "source")
        validate_date_identifier(date)
        if endpoint_kind is not None:
            validate_fund_endpoint_kind(endpoint_kind)
            if run_id is None:
                raise ValueError("routed fund capture requires run_id and source_revision")
            if source_revision_absent:
                if source_revision is not None:
                    raise ValueError(
                        "source_revision_absent requires source_revision to be omitted"
                    )
                source_revision = SOURCE_REVISION_SENTINEL
            elif source_revision is None:
                raise ValueError("routed fund capture requires run_id and source_revision")
            elif source_revision == SOURCE_REVISION_SENTINEL:
                raise ValueError("source_revision sentinel is reserved for provider absence")
            if attempt_id is None or page_ordinal is None:
                raise ValueError("routed fund capture requires attempt_id and page_ordinal")
        else:
            if source_revision_absent:
                raise ValueError("source_revision_absent requires endpoint_kind")
            if source_revision == SOURCE_REVISION_SENTINEL:
                raise ValueError("source_revision sentinel is reserved for provider absence")
            if attempt_id is not None or page_ordinal is not None:
                raise ValueError("attempt lineage requires endpoint_kind")
        resolved_capture_id = self._capture_id(capture_id, idempotency_key)
        resolved_ingest_time = utc_now() if ingest_time is None else ingest_time
        resolved_available_time = resolved_ingest_time if available_time is None else available_time
        object_id = content_id(content)
        manifest = RawObjectManifest(
            object_id=object_id,
            source=source,
            date=date,
            request=request,
            checksum=object_id,
            size=len(content),
            content_type=content_type,
            capture_id=resolved_capture_id,
            ingest_time=resolved_ingest_time,
            available_time=resolved_available_time,
            endpoint_kind=endpoint_kind,
            run_id=run_id,
            source_revision=source_revision,
            attempt_id=attempt_id,
            page_ordinal=page_ordinal,
        )

        capture_lock = self._capture_lock_path(source, date, manifest.capture_id)
        with self._exclusive_lock(capture_lock):
            existing = self._find_manifest(source, date, manifest.capture_id)
            pending = self._find_pending(source, date, manifest.capture_id)
            if existing is not None:
                existing_path, existing_manifest = existing
                if not self._same_capture(existing_manifest, manifest):
                    raise CaptureConflictError(
                        f"capture_id {manifest.capture_id!r} already identifies "
                        "a different response"
                    )
                if pending is not None:
                    if not self._same_capture(pending[1], existing_manifest):
                        raise CaptureConflictError(
                            f"pending capture_id {manifest.capture_id!r} conflicts "
                            "with final manifest"
                        )
                    with suppress(FileNotFoundError):
                        pending[0].unlink()
                self._read_and_verify(
                    self._object_path(existing_manifest.object_id),
                    existing_manifest.checksum,
                    existing_manifest.size,
                )
                _ = existing_path
                return existing_manifest

            if pending is not None:
                if not self._same_capture(pending[1], manifest):
                    raise CaptureConflictError(
                        f"capture_id {manifest.capture_id!r} already identifies "
                        "a different response"
                    )
                capture_manifest = pending[1]
                pending_path = pending[0]
            else:
                capture_manifest = manifest
                pending_path = self._pending_path(capture_manifest)
                if not self._write_exclusive(pending_path, self._pending_bytes(capture_manifest)):
                    pending_match = self._find_pending(source, date, manifest.capture_id)
                    if pending_match is None or not self._same_capture(
                        pending_match[1], capture_manifest
                    ):
                        raise CaptureConflictError(
                            f"capture_id {manifest.capture_id!r} pending intent conflict"
                        )
                    pending_path = pending_match[0]

            object_path = self._object_path(capture_manifest.object_id)
            if object_path.exists() or not self._write_exclusive(object_path, content):
                self._read_and_verify(object_path, capture_manifest.checksum, capture_manifest.size)

            manifest_path = self._index_dir(source, date) / (
                f"{capture_manifest.capture_id}.{capture_manifest.content_digest()}.json"
            )
            if not self._write_exclusive(manifest_path, self._manifest_bytes(capture_manifest)):
                final = self._find_manifest(source, date, capture_manifest.capture_id)
                if final is None:
                    raise RawIntegrityError("manifest publish lost without a readable manifest")
                if not self._same_capture(final[1], capture_manifest):
                    raise CaptureConflictError(
                        f"capture_id {capture_manifest.capture_id!r} already identifies "
                        "a different response"
                    )
                final_manifest = final[1]
            else:
                final_manifest = self._read_bound_manifest(manifest_path)

            self._read_and_verify(
                self._object_path(final_manifest.object_id),
                final_manifest.checksum,
                final_manifest.size,
            )
            with suppress(FileNotFoundError):
                pending_path.unlink()
            return final_manifest

    @staticmethod
    def _read_and_verify(path: Path, checksum: str, size: int | None) -> bytes:
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RawIntegrityError(f"unable to read raw object {path.name}") from exc
        if size is not None and len(content) != size:
            raise RawIntegrityError(
                f"raw object {path.name} size mismatch: expected {size}, got {len(content)}"
            )
        actual_checksum = content_id(content)
        if actual_checksum != checksum:
            raise RawIntegrityError(
                f"raw object {path.name} checksum mismatch: expected {checksum}, "
                f"got {actual_checksum}"
            )
        return content

    def get(
        self,
        object_id: str,
        *,
        checksum: str | None = None,
        size: int | None = None,
    ) -> bytes:
        """Retrieve bytes and reject checksum/size corruption."""

        path = self._object_path(object_id)
        expected_checksum = object_id if checksum is None else checksum
        return self._read_and_verify(path, expected_checksum, size)

    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        """List all capture manifests in deterministic order."""

        index_dir = self._index_dir(source, date)
        if not index_dir.exists():
            return []
        manifests: list[RawObjectManifest] = []
        seen_capture_ids: set[str] = set()
        for path in sorted(index_dir.glob("*.json")):
            manifest = self._read_manifest_file(path)
            if manifest.source != source or manifest.date != date:
                raise RawIntegrityError(f"manifest partition mismatch: {path.name}")
            if manifest.capture_id in seen_capture_ids:
                raise RawIntegrityError(
                    f"multiple manifests for capture_id {manifest.capture_id!r}"
                )
            seen_capture_ids.add(manifest.capture_id)
            manifests.append(manifest)
        manifests.sort(key=lambda item: (item.ingest_time, item.capture_id))
        return manifests


StorageCallback = Callable[[RawObjectManifest, bytes], None]
