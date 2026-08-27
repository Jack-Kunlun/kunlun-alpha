"""Validated volatile repository for published ranking snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from typing import cast

from ashare_contracts import RankingTerminalSnapshot


class RankingSnapshotStoreError(ValueError):
    """Base ranking snapshot repository error."""


class RankingSnapshotNotFoundError(RankingSnapshotStoreError):
    """No published snapshot exists at the requested point in time."""


class RankingSnapshotConflictError(RankingSnapshotStoreError):
    """A snapshot identifier was reused with different content."""


class RankingSnapshotStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[str, tuple[str, RankingTerminalSnapshot]] = {}

    def publish(self, raw: Mapping[str, object]) -> dict[str, object]:
        snapshot = RankingTerminalSnapshot.model_validate(raw)
        if snapshot.generated_at < snapshot.as_of:
            raise RankingSnapshotStoreError("generatedAt must not be earlier than asOf")
        canonical = snapshot.model_dump_json(by_alias=True)
        fingerprint = sha256(canonical.encode("utf-8")).hexdigest()
        with self._lock:
            current = self._snapshots.get(snapshot.snapshot_id)
            if current is not None and current[0] != fingerprint:
                raise RankingSnapshotConflictError("snapshotId already has different content")
            self._snapshots[snapshot.snapshot_id] = (fingerprint, snapshot)
        return self._payload(snapshot)

    def latest(self, as_of: str | None = None) -> dict[str, object]:
        cutoff = None if as_of is None else self._instant(as_of)
        with self._lock:
            candidates = [
                value[1]
                for value in self._snapshots.values()
                if cutoff is None or value[1].as_of <= cutoff
            ]
        if not candidates:
            raise RankingSnapshotNotFoundError("no published ranking snapshot")
        selected = max(
            candidates,
            key=lambda item: (item.as_of, item.generated_at, item.snapshot_id),
        )
        return self._payload(selected)

    @staticmethod
    def _instant(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise RankingSnapshotStoreError("asOf must be RFC3339") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise RankingSnapshotStoreError("asOf must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _payload(snapshot: RankingTerminalSnapshot) -> dict[str, object]:
        return cast(dict[str, object], snapshot.model_dump(by_alias=True, mode="json"))
