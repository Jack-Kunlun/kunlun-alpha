"""Raw landing zone tests.

Verifies the immutability contract: a repeated fetch never overwrites a
previous object, the manifest locates the source and request, checksums match,
and replay rebuilds from the raw zone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from data_worker.raw.manifest import RawObjectManifest
from data_worker.raw.replay import replay
from data_worker.raw.storage import LocalFileStorage


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_repeated_fetch_does_not_overwrite(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"code": "600000"}'

    first = storage.put("provider-x", "2026-08-13", "GET /instruments", content)
    second = storage.put("provider-x", "2026-08-13", "GET /instruments", content)

    assert first.object_id == second.object_id
    assert storage.get(first.object_id) == content


def test_different_content_produces_distinct_objects(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    a = storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "600000"}')
    b = storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "000001"}')

    assert a.object_id != b.object_id
    assert storage.get(a.object_id) == b'{"code": "600000"}'
    assert storage.get(b.object_id) == b'{"code": "000001"}'


def test_manifest_locates_source_and_request(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"code": "600000"}'
    storage.put("provider-x", "2026-08-13", "GET /instruments?exchange=SH", content)

    manifests = storage.list("provider-x", "2026-08-13")
    assert len(manifests) == 1
    manifest = manifests[0]
    assert manifest.source == "provider-x"
    assert manifest.date == "2026-08-13"
    assert manifest.request == "GET /instruments?exchange=SH"


def test_manifest_checksum_matches_content(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b"raw payload"
    manifest = storage.put("provider-x", "2026-08-13", "GET /raw", content)

    assert manifest.checksum == _sha256(content)
    assert manifest.size == len(content)


def test_replay_rebuilds_every_object(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "600000"}')
    storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "000001"}')

    replayed: list[tuple[RawObjectManifest, bytes]] = []
    count = replay(storage, "provider-x", "2026-08-13", lambda m, c: replayed.append((m, c)))

    assert count == 2
    assert sorted(m.request for m, _ in replayed) == ["GET /instruments", "GET /instruments"]
