"""Append-only filesystem repository for canonical run artifacts."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .artifact import (
    RegressionRunArtifact,
    RegressionValidationError,
    safe_id,
)
from .canonical import canonical_bytes, parse_canonical_json, require_sha256


class ArtifactRepositoryError(RuntimeError):
    """Base repository failure."""


class ArtifactConflictError(ArtifactRepositoryError):
    """Raised when immutable identity or content is reused inconsistently."""


class ArtifactCorruptionError(ArtifactRepositoryError):
    """Raised when an object, ref, or path is malformed or tampered with."""


def _reject_symlink(path: Path) -> None:
    try:
        if path.is_symlink():
            raise ArtifactCorruptionError(f"symlink is not an artifact object: {path}")
    except OSError as error:
        raise ArtifactCorruptionError(f"cannot inspect artifact path: {path}") from error


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _assert_secure_path(root: Path, path: Path) -> Path:
    root_absolute = root.absolute()
    target = path.absolute()
    try:
        relative = target.relative_to(root_absolute)
    except ValueError as error:
        raise ArtifactCorruptionError(f"artifact path escapes root: {path}") from error
    _reject_symlink(root_absolute)
    current = root_absolute
    for part in relative.parts:
        if part in ("", ".", ".."):
            raise ArtifactCorruptionError(f"artifact path is not canonical: {path}")
        current /= part
        if _path_exists(current):
            _reject_symlink(current)
    try:
        root_real = Path(os.path.realpath(root_absolute))
        target_real = Path(os.path.realpath(target))
        target_real.relative_to(root_real)
    except (OSError, ValueError) as error:
        raise ArtifactCorruptionError(f"artifact path is outside root: {path}") from error
    return target


def _ensure_secure_directory(root: Path, relative: str) -> Path:
    current = _assert_secure_path(root, root)
    for part in relative.split("/"):
        if not part or part in (".", ".."):
            raise ArtifactCorruptionError(f"artifact directory is not canonical: {relative}")
        current = _assert_secure_path(root, current / part)
        if _path_exists(current):
            if not current.is_dir():
                raise ArtifactCorruptionError(f"artifact path is not a directory: {current}")
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ArtifactRepositoryError(
                    f"cannot create artifact directory: {current}"
                ) from error
    return current


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileRunArtifactRepository:
    """Write-once object/ref store with no overwrite publication path."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path("work") / "backtest-regression-artifacts" if root is None else Path(root)
        if self.root.exists() and self.root.is_symlink():
            raise ArtifactCorruptionError(f"artifact root must not be a symlink: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        _assert_secure_path(self.root, self.root)
        for component in ("objects", "identities", "baselines"):
            _assert_secure_path(self.root, self.root / component)

    def _object_path(self, digest: str) -> Path:
        if _SHA256_RE.fullmatch(digest) is None:
            raise RegressionValidationError("artifact digest must be lowercase SHA-256")
        return _assert_secure_path(
            self.root,
            self.root / "objects" / "sha256" / digest[:2] / f"{digest}.json",
        )

    def _ref_path(self, suite_id: str, run_id: str) -> Path:
        safe_id(suite_id, "suiteId")
        safe_id(run_id, "runId")
        return _assert_secure_path(
            self.root,
            self.root / "identities" / suite_id / f"{run_id}.ref.json",
        )

    def _read_object(self, digest: str) -> RegressionRunArtifact:
        path = self._object_path(digest)
        _reject_symlink(path)
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ArtifactCorruptionError(f"artifact object is unavailable: {path}") from error
        try:
            artifact = RegressionRunArtifact.from_dict(
                parse_canonical_json(raw, field_name="object")
            )
        except (RegressionValidationError, ValueError) as error:
            raise ArtifactCorruptionError(f"artifact object is corrupt: {path}") from error
        if artifact.artifact_sha256 != digest:
            raise ArtifactCorruptionError("object filename and artifact digest disagree")
        return artifact

    def _read_ref(self, suite_id: str, run_id: str) -> str:
        path = self._ref_path(suite_id, run_id)
        _reject_symlink(path)
        try:
            raw = path.read_bytes()
            payload = parse_canonical_json(raw, field_name="identity ref")
        except (OSError, RegressionValidationError, ValueError) as error:
            raise ArtifactCorruptionError(f"identity ref is corrupt: {path}") from error
        keys = {"schemaVersion", "suiteId", "runId", "artifactSha256"}
        if set(payload) != keys or payload["schemaVersion"] != "backtest-regression-ref-v1":
            raise ArtifactCorruptionError("identity ref schema is unsupported")
        if payload["suiteId"] != suite_id or payload["runId"] != run_id:
            raise ArtifactCorruptionError("identity ref does not match requested identity")
        digest = payload["artifactSha256"]
        try:
            return require_sha256(digest, "identity ref artifactSha256")
        except ValueError as error:
            raise ArtifactCorruptionError("identity ref digest is malformed") from error

    def _publish_exclusive(self, path: Path, raw: bytes) -> None:
        path = _assert_secure_path(self.root, path)
        relative_parent = path.parent.relative_to(self.root.absolute()).as_posix()
        _ensure_secure_directory(self.root, relative_parent)
        if _path_exists(path):
            _reject_symlink(path)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                existing = path.read_bytes()
                if existing != raw:
                    raise ArtifactConflictError(
                        f"immutable path already contains different bytes: {path}"
                    ) from None
            except (AttributeError, NotImplementedError, OSError) as error:
                raise ArtifactRepositoryError(
                    "exclusive hard-link publication is unavailable"
                ) from error
            _fsync_directory(path.parent)
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as error:
                raise ArtifactRepositoryError(
                    f"cannot clean publication temp file: {temp_path}"
                ) from error

    def append(self, artifact: RegressionRunArtifact | object) -> str:
        typed = (
            artifact
            if isinstance(artifact, RegressionRunArtifact)
            else RegressionRunArtifact.from_dict(artifact)
        )
        object_path = self._object_path(typed.artifact_sha256)
        if _path_exists(object_path):
            _reject_symlink(object_path)
            existing = self._read_object(typed.artifact_sha256)
            if existing.payload != typed.payload:
                raise ArtifactConflictError("same object digest contains different content")
        else:
            self._publish_exclusive(object_path, typed.canonical_bytes())

        ref_path = self._ref_path(typed.suite_id, typed.run_id)
        ref = {
            "schemaVersion": "backtest-regression-ref-v1",
            "suiteId": typed.suite_id,
            "runId": typed.run_id,
            "artifactSha256": typed.artifact_sha256,
        }
        ref_bytes = canonical_bytes(ref)
        if _path_exists(ref_path):
            _reject_symlink(ref_path)
            try:
                existing_ref = ref_path.read_bytes()
            except OSError as error:
                raise ArtifactRepositoryError(
                    f"cannot read existing identity ref: {ref_path}"
                ) from error
            if existing_ref != ref_bytes:
                raise ArtifactConflictError("identity is already bound to a different artifact")
        else:
            self._publish_exclusive(ref_path, ref_bytes)
        return typed.artifact_sha256

    def get(self, suite_id: str, run_id: str) -> RegressionRunArtifact:
        digest = self._read_ref(suite_id, run_id)
        artifact = self._read_object(digest)
        if artifact.suite_id != suite_id or artifact.run_id != run_id:
            raise ArtifactCorruptionError("ref object identity mismatch")
        return artifact

    def list(self, suite_id: str) -> tuple[RegressionRunArtifact, ...]:
        safe_id(suite_id, "suiteId")
        directory = self.root / "identities" / suite_id
        directory = _assert_secure_path(self.root, directory)
        if not _path_exists(directory):
            return ()
        if not directory.is_dir():
            raise ArtifactCorruptionError(f"identity path is not a directory: {directory}")
        result: list[RegressionRunArtifact] = []
        for path in sorted(directory.glob("*.ref.json"), key=lambda item: item.name):
            _assert_secure_path(self.root, path)
            run_id = path.name[: -len(".ref.json")]
            result.append(self.get(suite_id, run_id))
        return tuple(result)


class InMemoryRunArtifactRepository:
    """Small deterministic repository used by unit tests and local orchestration."""

    def __init__(self, artifacts: tuple[RegressionRunArtifact, ...] = ()) -> None:
        self._artifacts: dict[tuple[str, str], RegressionRunArtifact] = {
            (item.suite_id, item.run_id): item for item in artifacts
        }

    def append(self, artifact: RegressionRunArtifact) -> str:
        key = (artifact.suite_id, artifact.run_id)
        previous = self._artifacts.get(key)
        if previous is not None and previous.artifact_sha256 != artifact.artifact_sha256:
            raise ArtifactConflictError("identity is already bound to a different artifact")
        self._artifacts[key] = artifact
        return artifact.artifact_sha256

    def get(self, suite_id: str, run_id: str) -> RegressionRunArtifact:
        safe_id(suite_id, "suiteId")
        safe_id(run_id, "runId")
        try:
            return self._artifacts[(suite_id, run_id)]
        except KeyError as error:
            raise ArtifactRepositoryError("artifact identity is missing") from error

    def list(self, suite_id: str) -> tuple[RegressionRunArtifact, ...]:
        safe_id(suite_id, "suiteId")
        return tuple(
            value
            for (candidate_suite, _), value in sorted(self._artifacts.items())
            if candidate_suite == suite_id
        )


__all__ = [
    "ArtifactConflictError",
    "ArtifactCorruptionError",
    "ArtifactRepositoryError",
    "FileRunArtifactRepository",
    "InMemoryRunArtifactRepository",
]
