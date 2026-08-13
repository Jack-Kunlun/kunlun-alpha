"""Raw object storage.

``RawStorage`` is the immutable landing zone abstraction. ``LocalFileStorage``
is a filesystem implementation (MinIO/S3 can back the same interface later).
Objects are content-addressed by SHA-256, so re-fetching identical content is
idempotent and never overwrites a previous object.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path

from data_worker.raw.manifest import RawObjectManifest


def content_id(content: bytes) -> str:
    """Content-addressed object id (SHA-256 hex digest)."""
    return hashlib.sha256(content).hexdigest()


class RawStorage(ABC):
    """Immutable raw object store."""

    @abstractmethod
    def put(
        self,
        source: str,
        date: str,
        request: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> RawObjectManifest:
        """Store content immutably and return its manifest."""

    @abstractmethod
    def get(self, object_id: str) -> bytes:
        """Retrieve raw content by object id."""

    @abstractmethod
    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        """List manifests for a source on a collection date."""


class LocalFileStorage(RawStorage):
    """Filesystem-backed raw storage.

    Layout: ``<root>/objects/<object_id>`` for content and
    ``<root>/index/<source>/<date>/<object_id>.json`` for manifests, so the
    source and request of any object can be located by listing its index.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._objects = self._root / "objects"
        self._index = self._root / "index"

    def _object_path(self, object_id: str) -> Path:
        return self._objects / object_id

    def _index_dir(self, source: str, date: str) -> Path:
        return self._index / source / date

    def _manifest_path(self, source: str, date: str, object_id: str) -> Path:
        return self._index_dir(source, date) / f"{object_id}.json"

    def put(
        self,
        source: str,
        date: str,
        request: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> RawObjectManifest:
        object_id = content_id(content)
        checksum = object_id
        manifest = RawObjectManifest(
            object_id=object_id,
            source=source,
            date=date,
            request=request,
            checksum=checksum,
            size=len(content),
            content_type=content_type,
        )

        object_path = self._object_path(object_id)
        object_path.parent.mkdir(parents=True, exist_ok=True)
        if not object_path.exists():
            object_path.write_bytes(content)

        index_dir = self._index_dir(source, date)
        index_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._manifest_path(source, date, object_id)
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return manifest

    def get(self, object_id: str) -> bytes:
        return self._object_path(object_id).read_bytes()

    def list(self, source: str, date: str) -> list[RawObjectManifest]:
        index_dir = self._index_dir(source, date)
        if not index_dir.exists():
            return []
        manifests: list[RawObjectManifest] = []
        for path in sorted(index_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            manifests.append(RawObjectManifest.from_dict(data))
        return manifests
