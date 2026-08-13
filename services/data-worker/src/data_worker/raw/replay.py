"""Replay entry point.

Replays every raw object for a source and collection date in a deterministic
order, invoking a handler per object. This is how a normalized result set can
be rebuilt from the immutable raw zone after a bug fix or a schema change.
"""

from __future__ import annotations

from collections.abc import Callable

from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.storage import RawStorage


def replay(
    storage: RawStorage,
    source: str,
    date: str,
    handler: Callable[[RawObjectManifest, bytes], None],
) -> int:
    """Replay all raw objects for source/date, returning the count replayed."""
    manifests = storage.list(source, date)
    for manifest in manifests:
        content = storage.get(manifest.object_id)
        handler(manifest, content)
    return len(manifests)
