"""Deterministic replay helpers for immutable raw captures."""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal

from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.storage import RawStorage


def replay(
    storage: RawStorage,
    source: str,
    date: str,
    handler: Callable[[RawObjectManifest, bytes], None],
) -> int:
    """Replay every capture in deterministic ingest-time/capture order.

    The manifest is passed for every capture, even when multiple captures
    point to one shared content object.  Integrity is checked against the
    manifest's checksum and byte size before the handler is invoked.
    """

    manifests = storage.list(source, date)
    for manifest in manifests:
        content = storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
        handler(manifest, content)
    return len(manifests)


def decode_json(content: bytes) -> object:
    """Decode a JSON payload without binary-float ingress.

    JSON numbers containing a decimal point or exponent become ``Decimal``;
    integer values remain Python integers.  The original bytes remain the
    immutable source of truth in the raw object store.
    """

    return json.loads(content.decode("utf-8"), parse_float=Decimal)


def replay_json(
    storage: RawStorage,
    source: str,
    date: str,
    handler: Callable[[RawObjectManifest, object], None],
) -> int:
    """Replay JSON captures using :func:`decode_json` for each response."""

    manifests = storage.list(source, date)
    for manifest in manifests:
        content = storage.get(
            manifest.object_id,
            checksum=manifest.checksum,
            size=manifest.size,
        )
        handler(manifest, decode_json(content))
    return len(manifests)
