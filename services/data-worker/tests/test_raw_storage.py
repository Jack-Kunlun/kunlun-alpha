"""Raw landing zone tests.

Verifies the immutability contract: a repeated fetch never overwrites a
previous object, the manifest locates the source and request, checksums match,
and replay rebuilds from the raw zone.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from data_worker.raw import manifest as manifest_module
from data_worker.raw.manifest import RawObjectManifest, sanitize_request_identity
from data_worker.raw.replay import decode_json, replay, replay_json
from data_worker.raw.storage import (
    CaptureConflictError,
    LocalFileStorage,
    RawIntegrityError,
    RawStorageError,
    content_id,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_repeated_fetch_does_not_overwrite(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"code": "600000"}'

    first = storage.put("provider-x", "2026-08-13", "GET /instruments", content)
    second = storage.put("provider-x", "2026-08-13", "GET /instruments", content)

    assert first.object_id == second.object_id
    assert storage.get(first.object_id) == content


def test_identical_payloads_create_distinct_capture_manifests(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"code": "600000"}'
    ingest_time = datetime(2026, 8, 13, 1, 30, tzinfo=UTC)

    first = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /instruments?exchange=SH",
        content,
        capture_id="capture-a",
        ingest_time=ingest_time,
        available_time=ingest_time,
    )
    second = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /instruments?exchange=SZ",
        content,
        capture_id="capture-b",
        ingest_time=ingest_time,
        available_time=ingest_time,
    )

    assert first.capture_id != second.capture_id
    assert first.object_id == second.object_id
    assert first.request_identity.endswith("exchange=SH")
    assert second.request_identity.endswith("exchange=SZ")
    assert [manifest.capture_id for manifest in storage.list("provider-x", "2026-08-13")] == [
        "capture-a",
        "capture-b",
    ]
    assert (
        len([path for path in (tmp_path / "objects").iterdir() if not path.name.startswith(".")])
        == 1
    )
    manifest_files = list((tmp_path / "index" / "provider-x" / "2026-08-13").glob("*.json"))
    assert len(manifest_files) == 2
    assert all(path.name.startswith(("capture-a.", "capture-b.")) for path in manifest_files)


def test_capture_id_is_explicit_idempotency_key(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    first = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw",
        b"raw payload",
        capture_id="capture-retry",
    )
    retry = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw",
        b"raw payload",
        capture_id="capture-retry",
    )

    assert retry == first
    assert len(storage.list("provider-x", "2026-08-13")) == 1
    with pytest.raises(CaptureConflictError):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /raw?different=true",
            b"different payload",
            capture_id="capture-retry",
        )


def test_capture_conflict_is_rejected_before_new_object_write(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    first = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw",
        b"raw payload",
        capture_id="capture-conflict",
    )
    object_paths_before = {path.name for path in (tmp_path / "objects").iterdir()}

    with pytest.raises(CaptureConflictError):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /different",
            b"different payload",
            capture_id="capture-conflict",
        )

    assert first.object_id in object_paths_before
    assert {path.name for path in (tmp_path / "objects").iterdir()} == object_paths_before


def test_available_time_cannot_precede_ingest_time(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    ingest_time = datetime(2026, 8, 13, 1, 30, tzinfo=UTC)

    with pytest.raises(ValueError, match="available_time"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /raw",
            b"payload",
            capture_id="capture-time-order",
            ingest_time=ingest_time,
            available_time=datetime(2026, 8, 13, 1, 29, tzinfo=UTC),
        )

    assert not tmp_path.exists() or not any(tmp_path.iterdir())


def test_atomic_fallback_does_not_publish_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "capture.json"

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError("hard links unavailable")

    def failed_replace(_source: Path, _destination: Path) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr("data_worker.raw.storage.os.link", unsupported_link)
    monkeypatch.setattr("data_worker.raw.storage.os.replace", failed_replace)

    with pytest.raises(OSError, match="rename failed"):
        LocalFileStorage._write_exclusive(target, b"complete payload")

    assert not target.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_fallback_serializes_publish_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "capture.json"
    first_publish_started = threading.Event()
    release_first_publish = threading.Event()
    original_replace = os.replace
    first_replace = True

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise OSError("hard links unavailable")

    def controlled_replace(source: Path, destination: Path) -> None:
        nonlocal first_replace
        if destination == target and first_replace:
            first_replace = False
            first_publish_started.set()
            assert release_first_publish.wait(timeout=2)
        original_replace(source, destination)

    monkeypatch.setattr("data_worker.raw.storage.os.link", unsupported_link)
    monkeypatch.setattr("data_worker.raw.storage.os.replace", controlled_replace)
    outcomes: list[bool] = []

    first_thread = threading.Thread(
        target=lambda: outcomes.append(LocalFileStorage._write_exclusive(target, b"first"))
    )
    second_thread = threading.Thread(
        target=lambda: outcomes.append(LocalFileStorage._write_exclusive(target, b"second"))
    )
    first_thread.start()
    assert first_publish_started.wait(timeout=2)
    second_thread.start()
    release_first_publish.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert sorted(outcomes) == [False, True]
    assert target.read_bytes() == b"first"


def test_idempotency_key_derives_stable_capture_id(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    first = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw",
        b"raw payload",
        idempotency_key="request-attempt-1",
    )
    retry = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw",
        b"raw payload",
        idempotency_key="request-attempt-1",
    )

    assert retry.capture_id == first.capture_id
    assert len(storage.list("provider-x", "2026-08-13")) == 1


def test_manifest_redacts_sensitive_request_material(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw?exchange=SH&token=top-secret&account_id=001&cookie=session-secret",
        b"raw payload",
        capture_id="capture-safe",
    )

    assert "top-secret" not in manifest.request
    assert "session-secret" not in manifest.request
    assert "001" not in manifest.request
    stored_path = next(
        (tmp_path / "index" / "provider-x" / "2026-08-13").glob("capture-safe.*.json")
    )
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert "top-secret" not in json.dumps(stored)
    assert "exchange=SH" in stored["request_identity"]


def test_manifest_redacts_inline_sensitive_headers(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw Authorization: Bearer inline-secret Cookie: session=inline-cookie",
        b"raw payload",
        capture_id="capture-inline-safe",
    )

    assert "inline-secret" not in manifest.request
    assert "inline-cookie" not in manifest.request


def test_manifest_request_allowlist_drops_body_headers_and_path_identifiers(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        (
            "POST /accounts/001?exchange=SH&limit=20&x-api-key=query-secret"
            "\nProxy-Authorization: Bearer header-secret\n"
            '{"token":"body-secret","account_id":"001"}'
        ),
        b"raw payload",
        capture_id="capture-request-safe",
    )

    assert "001" not in manifest.request
    assert "query-secret" not in manifest.request
    assert "header-secret" not in manifest.request
    assert "body-secret" not in manifest.request
    assert "exchange=SH" in manifest.request
    assert "limit=20" in manifest.request
    assert "accounts" not in manifest.request


def test_legacy_manifest_is_read_only_compatible_and_coexists_with_new_capture(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"legacy": true}'
    object_id = content_id(content)
    object_path = tmp_path / "objects" / object_id
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(content)
    legacy_path = tmp_path / "index" / "provider-x" / "2026-08-13" / f"{object_id}.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_bytes = json.dumps(
        {
            "object_id": object_id,
            "source": "provider-x",
            "date": "2026-08-13",
            "request": "GET /legacy",
            "checksum": object_id,
            "size": len(content),
            "content_type": "application/json",
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    legacy_path.write_bytes(legacy_bytes)

    new_manifest = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /new",
        content,
        capture_id="new-capture",
        ingest_time=datetime(2026, 8, 13, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, tzinfo=UTC),
        content_type="application/json",
    )
    manifests = storage.list("provider-x", "2026-08-13")

    assert len(manifests) == 2
    legacy_manifest = next(item for item in manifests if item.capture_id.startswith("legacy-"))
    assert legacy_manifest.capture_id != new_manifest.capture_id
    assert legacy_manifest.capture_id == f"legacy-object-{object_id[:32]}"
    assert legacy_manifest.ingest_time == datetime(2026, 8, 13, tzinfo=UTC)
    assert legacy_manifest.available_time == legacy_manifest.ingest_time
    assert legacy_path.read_bytes() == legacy_bytes
    assert storage.get(object_id, checksum=object_id, size=len(content)) == content

    replayed: list[str] = []
    assert (
        replay(
            storage,
            "provider-x",
            "2026-08-13",
            lambda manifest, _content: replayed.append(manifest.capture_id),
        )
        == 2
    )
    assert sorted(replayed) == sorted({legacy_manifest.capture_id, new_manifest.capture_id})


def test_legacy_manifest_filename_mismatch_is_rejected(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    object_id = content_id(b"legacy")
    index_dir = tmp_path / "index" / "provider-x" / "2026-08-13"
    index_dir.mkdir(parents=True)
    manifest = {
        "object_id": object_id,
        "source": "provider-x",
        "date": "2026-08-13",
        "request": "GET /legacy",
        "checksum": object_id,
        "size": 6,
        "content_type": "application/octet-stream",
    }
    (index_dir / f"{'0' * 64}.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RawIntegrityError, match="legacy|filename|object"):
        storage.list("provider-x", "2026-08-13")


def test_legacy_manifest_corruption_is_rejected(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    object_id = content_id(b"legacy")
    index_dir = tmp_path / "index" / "provider-x" / "2026-08-13"
    index_dir.mkdir(parents=True)
    (index_dir / f"{object_id}.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(RawIntegrityError, match="invalid|legacy"):
        storage.list("provider-x", "2026-08-13")


@pytest.mark.parametrize(
    "identifier",
    [
        "CON",
        "con.txt",
        "PRN",
        "AUX.log",
        "NUL",
        "CLOCK$",
        "COM1",
        "com9.txt",
        "LPT1",
        "lpt9.log",
        "name.",
        "name ",
    ],
)
@pytest.mark.parametrize("field", ["source", "capture_id"])
def test_windows_reserved_and_trailing_identifiers_are_rejected(
    tmp_path: Path, field: str, identifier: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    kwargs = {"source": "provider-x", "capture_id": "capture-safe"}
    kwargs[field] = identifier

    with pytest.raises(ValueError):
        storage.put(
            kwargs["source"],
            "2026-08-13",
            "GET /raw",
            b"payload",
            capture_id=kwargs["capture_id"],
        )

    assert not (tmp_path / "objects").exists()
    assert not (tmp_path / "index").exists()


def test_manifest_tampering_is_rejected_by_content_bound_filename(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x", "2026-08-13", "GET /raw?exchange=SH", b"payload", capture_id="capture-bound"
    )
    manifest_path = next(
        (tmp_path / "index" / "provider-x" / "2026-08-13").glob("capture-bound.*.json")
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["object_id"] = content_id(b"other payload")
    manifest_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(RawIntegrityError, match="manifest|digest"):
        storage.list("provider-x", "2026-08-13")

    assert manifest.object_id != raw["object_id"]


def test_multiple_bound_manifests_for_one_capture_are_integrity_error(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put("provider-x", "2026-08-13", "GET /raw", b"payload", capture_id="capture-duplicate")
    manifest_path = next(
        (tmp_path / "index" / "provider-x" / "2026-08-13").glob("capture-duplicate.*.json")
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    duplicate_manifest = RawObjectManifest.from_dict(
        {**raw, "request_identity": "GET /other", "request": "GET /other"}
    )
    raw = duplicate_manifest.to_dict()
    duplicate_bytes = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    duplicate_digest = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    duplicate_path = manifest_path.with_name(f"capture-duplicate.{duplicate_digest}.json")
    duplicate_path.write_bytes(duplicate_bytes)

    with pytest.raises(RawIntegrityError, match="multiple"):
        storage.list("provider-x", "2026-08-13")


def test_capture_os_lock_cannot_be_stolen_while_old_owner_holds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "capture.lock"
    monkeypatch.setattr("data_worker.raw.storage._LOCK_WAIT_SECONDS", 0.05)

    def acquire_again() -> None:
        with LocalFileStorage._exclusive_lock(lock_path):
            pass

    with LocalFileStorage._exclusive_lock(lock_path):
        try:
            acquire_again()
        except RawStorageError as exc:
            assert "lock" in str(exc)
        else:  # pragma: no cover - the lock must remain held
            pytest.fail("a live lock was acquired twice")

    with LocalFileStorage._exclusive_lock(lock_path):
        assert lock_path.exists()


def test_persistent_lock_file_without_owner_is_reusable(tmp_path: Path) -> None:
    lock_path = tmp_path / "capture.lock"
    lock_path.write_bytes(b"persistent lock marker")

    with LocalFileStorage._exclusive_lock(lock_path):
        assert lock_path.exists()


def test_same_capture_concurrency_conflict_does_not_write_orphan_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    first_content = b"first payload"
    second_content = b"second payload"
    first_object = content_id(first_content)
    second_object = content_id(second_content)
    first_write_started = threading.Event()
    release_first_write = threading.Event()
    original_write = LocalFileStorage._write_exclusive

    def controlled_write(path: Path, data: bytes) -> bool:
        if path.name == first_object:
            first_write_started.set()
            assert release_first_write.wait(timeout=2)
        return original_write(path, data)

    monkeypatch.setattr(LocalFileStorage, "_write_exclusive", staticmethod(controlled_write))
    outcomes: list[object] = []

    def write_first() -> None:
        try:
            outcomes.append(
                storage.put(
                    "provider-x",
                    "2026-08-13",
                    "GET /first",
                    first_content,
                    capture_id="capture-race",
                )
            )
        except BaseException as exc:  # pragma: no cover - assertion below reports any failure
            outcomes.append(exc)

    def write_second() -> None:
        try:
            outcomes.append(
                storage.put(
                    "provider-x",
                    "2026-08-13",
                    "GET /second",
                    second_content,
                    capture_id="capture-race",
                )
            )
        except BaseException as exc:
            outcomes.append(exc)

    first_thread = threading.Thread(target=write_first)
    second_thread = threading.Thread(target=write_second)
    first_thread.start()
    assert first_write_started.wait(timeout=2)
    second_thread.start()
    assert not (tmp_path / "objects" / second_object).exists()
    release_first_write.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert len(outcomes) == 2
    assert sum(isinstance(outcome, CaptureConflictError) for outcome in outcomes) == 1
    assert not (tmp_path / "objects" / second_object).exists()


def test_pending_intent_recovers_after_object_publish_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    original_write = LocalFileStorage._write_exclusive
    fail_object = content_id(b"recoverable payload")
    should_fail = True

    def fail_once(path: Path, data: bytes) -> bool:
        nonlocal should_fail
        if path.name == fail_object and should_fail:
            should_fail = False
            raise OSError("simulated object publish failure")
        return original_write(path, data)

    monkeypatch.setattr(LocalFileStorage, "_write_exclusive", staticmethod(fail_once))
    with pytest.raises(OSError, match="simulated"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /recover",
            b"recoverable payload",
            capture_id="capture-pending",
        )

    pending_files = list(
        (tmp_path / "pending" / "provider-x" / "2026-08-13").glob("capture-pending.*.json")
    )
    assert len(pending_files) == 1
    assert not (tmp_path / "objects" / fail_object).exists()

    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /recover",
        b"recoverable payload",
        capture_id="capture-pending",
    )
    assert manifest.capture_id == "capture-pending"
    assert (
        list((tmp_path / "pending" / "provider-x" / "2026-08-13").glob("capture-pending.*.json"))
        == []
    )


def test_pending_recovery_after_object_publish_before_manifest_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(tmp_path)
    original_write = LocalFileStorage._write_exclusive
    fail_manifest = True
    index_dir = tmp_path / "index" / "provider-x" / "2026-08-13"

    def fail_before_final_manifest(path: Path, data: bytes) -> bool:
        nonlocal fail_manifest
        if fail_manifest and path.parent == index_dir and path.suffix == ".json":
            fail_manifest = False
            raise OSError("simulated final manifest crash")
        return original_write(path, data)

    monkeypatch.setattr(
        LocalFileStorage, "_write_exclusive", staticmethod(fail_before_final_manifest)
    )
    content = b"manifest crash window"
    with pytest.raises(OSError, match="final manifest crash"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /recover",
            content,
            capture_id="capture-window",
        )

    object_id = content_id(content)
    assert (tmp_path / "objects" / object_id).read_bytes() == content
    assert list(index_dir.glob("capture-window.*.json")) == []
    assert (
        len(
            list((tmp_path / "pending" / "provider-x" / "2026-08-13").glob("capture-window.*.json"))
        )
        == 1
    )

    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /recover",
        content,
        capture_id="capture-window",
    )
    assert manifest.capture_id == "capture-window"
    assert storage.list("provider-x", "2026-08-13") == [manifest]
    assert (
        list((tmp_path / "pending" / "provider-x" / "2026-08-13").glob("capture-window.*.json"))
        == []
    )


@pytest.mark.parametrize(
    ("source", "date", "capture_id"),
    [
        ("../provider-x", "2026-08-13", "capture-safe"),
        ("provider-x", "2026/08/13", "capture-safe"),
        ("provider-x", "2026-08-13", "../capture-safe"),
    ],
)
def test_unsafe_identifiers_are_rejected_before_filesystem_access(
    tmp_path: Path, source: str, date: str, capture_id: str
) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(ValueError):
        storage.put(source, date, "GET /raw", b"payload", capture_id=capture_id)

    assert not (tmp_path / "objects").exists()
    assert not (tmp_path / "index").exists()


def test_identifier_length_boundaries_are_rejected(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(ValueError, match="length"):
        storage.put("s" * 65, "2026-08-13", "GET /raw", b"payload", capture_id="capture-safe")
    with pytest.raises(ValueError, match="length"):
        storage.put("provider-x", "2026-08-13", "GET /raw", b"payload", capture_id="c" * 65)


def test_cursor_values_are_bounded_and_opaque_values_are_hashed() -> None:
    opaque_cursor = "opaque/token?" + ("secret-value-" * 20)
    request = (
        "GET /bars?exchange=SH&cursor="
        + opaque_cursor
        + "&page=1&code=600000.SH&x-api-key=query-secret"
    )

    sanitized = sanitize_request_identity(request)
    assert opaque_cursor not in sanitized
    assert "query-secret" not in sanitized
    assert "exchange=SH" in sanitized
    assert "page=1" in sanitized
    assert "code=600000.SH" in sanitized
    assert "cursor=sha256-" in sanitized
    assert sanitize_request_identity(sanitized) == sanitized
    assert "cursor=123" in sanitize_request_identity("GET /bars?cursor=123")
    assert "cursor=sha256-" in sanitize_request_identity("GET /bars?cursor=abc123")


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
    assert manifest.request == sanitize_request_identity("GET /instruments?exchange=SH")


def test_manifest_checksum_matches_content(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b"raw payload"
    manifest = storage.put("provider-x", "2026-08-13", "GET /raw", content)

    assert manifest.checksum == _sha256(content)
    assert manifest.size == len(content)
    assert manifest.ingest_time.tzinfo is not None
    assert manifest.available_time.tzinfo is not None
    assert manifest.object_id == manifest.checksum


def test_routed_manifest_binds_attempt_and_page_ordinal_without_changing_legacy_digest(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"items": [], "nextCursor": null}'
    legacy = RawObjectManifest(
        object_id=content_id(content),
        source="provider-x",
        date="2026-08-13",
        request="GET /funds/nav?exchange=SH",
        checksum=content_id(content),
        size=len(content),
        capture_id="legacy-route",
        ingest_time=datetime(2026, 8, 13, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, tzinfo=UTC),
        endpoint_kind="nav",
        run_id="run-1",
        source_revision="revision-1",
    )

    routed = storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        content,
        capture_id="capture-route",
        ingest_time=datetime(2026, 8, 13, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, tzinfo=UTC),
        endpoint_kind="nav",
        run_id="run-1",
        source_revision="revision-1",
        attempt_id="attempt-1",
        page_ordinal=0,
    )

    assert "attempt_id" not in legacy.to_dict()
    assert "page_ordinal" not in legacy.to_dict()
    assert routed.attempt_id == "attempt-1"
    assert routed.page_ordinal == 0
    assert routed.content_digest() != legacy.content_digest()
    assert RawObjectManifest.from_dict(routed.to_dict()) == routed


@pytest.mark.parametrize("changed", ["attempt_id", "page_ordinal"])
def test_same_capture_with_changed_attempt_lineage_fails_closed(
    tmp_path: Path, changed: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    content = b'{"items": [], "nextCursor": null}'
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        content,
        capture_id="capture-lineage-conflict",
        endpoint_kind="nav",
        run_id="run-1",
        source_revision="revision-1",
        attempt_id="attempt-1",
        page_ordinal=0,
    )
    changed_attempt_id = "attempt-2" if changed == "attempt_id" else "attempt-1"
    changed_page_ordinal = 0 if changed == "attempt_id" else 1

    with pytest.raises(CaptureConflictError):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            content,
            capture_id="capture-lineage-conflict",
            endpoint_kind="nav",
            run_id="run-1",
            source_revision="revision-1",
            attempt_id=changed_attempt_id,
            page_ordinal=changed_page_ordinal,
        )


def test_new_routed_manifest_requires_complete_attempt_lineage(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)

    with pytest.raises(ValueError, match="attempt|ordinal"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            b'{"items": [], "nextCursor": null}',
            endpoint_kind="nav",
            run_id="run-1",
            source_revision="revision-1",
        )


def test_new_routed_manifest_rejects_uncontrolled_source_revision_sentinel(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    sentinel = manifest_module.SOURCE_REVISION_SENTINEL

    with pytest.raises(ValueError, match="source_revision"):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            b'{"items": [], "nextCursor": null}',
            endpoint_kind="nav",
            run_id="run-1",
            source_revision=sentinel,
            attempt_id="attempt-1",
            page_ordinal=0,
        )


@pytest.mark.parametrize("endpoint_kind", ["metadata", "nav", "inav", "benchmark", "fees"])
def test_routed_manifest_lineage_supports_all_fund_endpoint_kinds(
    tmp_path: Path, endpoint_kind: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x",
        "2026-08-13",
        f"GET /funds/{endpoint_kind}?exchange=SH",
        b'{"items": [], "nextCursor": null}',
        capture_id=f"capture-{endpoint_kind}",
        endpoint_kind=endpoint_kind,
        run_id="run-all-kinds",
        source_revision="revision-1",
        attempt_id="attempt-all-kinds",
        page_ordinal=0,
    )

    assert RawObjectManifest.route_identity(manifest.to_dict()) == (
        endpoint_kind,
        "run-all-kinds",
        "revision-1",
        "attempt-all-kinds",
        0,
    )


def test_replay_rebuilds_every_object(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "600000"}')
    storage.put("provider-x", "2026-08-13", "GET /instruments", b'{"code": "000001"}')

    replayed: list[tuple[RawObjectManifest, bytes]] = []
    count = replay(storage, "provider-x", "2026-08-13", lambda m, c: replayed.append((m, c)))

    assert count == 2
    expected_request = sanitize_request_identity("GET /instruments")
    assert sorted(m.request for m, _ in replayed) == [expected_request, expected_request]


def test_replay_preserves_capture_provenance_in_deterministic_order(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    timestamp = datetime(2026, 8, 13, 1, 30, tzinfo=UTC)
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw?cursor=2",
        b'{"price": 1.2}',
        capture_id="capture-b",
        ingest_time=timestamp,
        available_time=timestamp,
        content_type="application/json",
    )
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /raw?cursor=1",
        b'{"price": 1.2}',
        capture_id="capture-a",
        ingest_time=timestamp,
        available_time=timestamp,
        content_type="application/json",
    )

    replayed: list[tuple[str, str]] = []
    count = replay(
        storage,
        "provider-x",
        "2026-08-13",
        lambda manifest, _content: replayed.append((manifest.capture_id, manifest.request)),
    )

    assert count == 2
    assert replayed == [
        ("capture-a", sanitize_request_identity("GET /raw?cursor=1")),
        ("capture-b", sanitize_request_identity("GET /raw?cursor=2")),
    ]


def test_corrupt_object_is_rejected_by_get_and_replay(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x", "2026-08-13", "GET /raw", b"raw payload", capture_id="capture-corrupt"
    )
    (tmp_path / "objects" / manifest.object_id).write_bytes(b"truncated")

    with pytest.raises(RawIntegrityError, match="checksum"):
        storage.get(manifest.object_id)
    with pytest.raises(RawIntegrityError, match="checksum|size"):
        replay(storage, "provider-x", "2026-08-13", lambda _manifest, _content: None)


def test_replay_rejects_manifest_size_mismatch(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    manifest = storage.put(
        "provider-x", "2026-08-13", "GET /raw", b"raw payload", capture_id="capture-size"
    )
    manifest_path = next(
        (tmp_path / "index" / "provider-x" / "2026-08-13").glob("capture-size.*.json")
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["size"] = manifest.size + 1
    tampered_bytes = json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    tampered_digest = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest_path.unlink()
    manifest_path.with_name(f"capture-size.{tampered_digest}.json").write_bytes(tampered_bytes)

    with pytest.raises(RawIntegrityError, match="size"):
        replay(storage, "provider-x", "2026-08-13", lambda _manifest, _content: None)


def test_json_replay_uses_decimal_for_price_sensitive_numbers(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /bars",
        b'{"price": 0.1, "nested": [1.25]}',
        capture_id="capture-json",
        content_type="application/json",
    )

    decoded = decode_json(b'{"price": 0.1, "nested": [1.25]}')
    assert decoded == {"price": Decimal("0.1"), "nested": [Decimal("1.25")]}

    replayed: list[object] = []
    assert (
        replay_json(
            storage,
            "provider-x",
            "2026-08-13",
            lambda _manifest, payload: replayed.append(payload),
        )
        == 1
    )
    assert replayed == [{"price": Decimal("0.1"), "nested": [Decimal("1.25")]}]
