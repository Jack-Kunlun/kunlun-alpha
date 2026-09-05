"""Remote managed market-data settings tests."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import stat
import threading
from dataclasses import replace
from http.client import HTTPMessage
from pathlib import Path
from typing import cast
from urllib.error import HTTPError
from urllib.request import Request

import data_worker.jobs.market_data.runtime as runtime_module
import pytest
from data_worker.jobs.market_data import checkpoint as checkpoint_module
from data_worker.jobs.market_data.collector import MarketDataCollector
from data_worker.jobs.market_data.quality import MarketDataQualitySink
from data_worker.jobs.market_data.remote_settings import (
    MAX_REMOTE_SETTINGS_RESPONSE_BYTES,
    RemoteMarketDataSettings,
    RemoteMarketDataSettingsError,
    fetch_remote_market_data_settings,
    load_remote_market_data_settings,
)
from data_worker.jobs.market_data.runtime import (
    MarketDataSyncSettings,
    MarketDataSyncSummary,
    build_market_data_runner,
    load_market_data_settings,
    managed_market_data_checkpoint_root,
    refresh_managed_market_data_settings,
    run_market_data_sync,
)
from data_worker.raw.storage import LocalFileStorage

_WORKER_TOKEN = "worker-token-" + "x" * 32
_URL = "https://control.example.test/api/v1/internal/market-data/settings"


class _Response:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self._body
        return self._body[:size]

    def close(self) -> None:
        self.closed = True


class _Transport:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response
        self.requests: list[tuple[Request, float]] = []

    def __call__(self, request: Request, timeout_seconds: float) -> _Response:
        self.requests.append((request, timeout_seconds))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _body(*, provider: str = "akshare", revision: int = 1, token: str | None = None) -> bytes:
    return json.dumps(
        {
            "schemaVersion": "market-data-worker-settings-v1",
            "provider": provider,
            "revision": revision,
            "token": token,
        }
    ).encode()


def _environment(url: str = _URL) -> dict[str, str]:
    return {
        "MARKET_DATA_SETTINGS_URL": url,
        "MARKET_DATA_SETTINGS_WORKER_TOKEN": _WORKER_TOKEN,
    }


def test_remote_settings_are_loaded_from_the_internal_endpoint() -> None:
    transport = _Transport(_Response(200, _body()))

    result = fetch_remote_market_data_settings(_URL, _WORKER_TOKEN, transport=transport)

    assert result.provider == "akshare"
    assert result.revision == 1


def test_remote_settings_requires_exact_schema_and_provider_token_pair() -> None:
    for payload in (
        {"schemaVersion": "market-data-worker-settings-v1", "provider": "akshare", "revision": 1},
        {
            "schemaVersion": "market-data-worker-settings-v1",
            "provider": "akshare",
            "revision": 1,
            "token": None,
            "extra": True,
        },
        {
            "schemaVersion": "market-data-worker-settings-v1",
            "provider": "tushare",
            "revision": 1,
            "token": None,
        },
        {
            "schemaVersion": "market-data-worker-settings-v1",
            "provider": "akshare",
            "revision": 1,
            "token": "unexpected",
        },
    ):
        body = json.dumps(payload).encode()
        with pytest.raises(RemoteMarketDataSettingsError):
            fetch_remote_market_data_settings(
                _URL, _WORKER_TOKEN, transport=_Transport(_Response(200, body))
            )


def test_remote_settings_reject_bool_revision_and_non_printable_token() -> None:
    for revision, token in ((True, None), (0, "contains space"), (0, "bad\nvalue")):
        with pytest.raises(RemoteMarketDataSettingsError):
            fetch_remote_market_data_settings(
                _URL,
                _WORKER_TOKEN,
                transport=_Transport(_Response(200, _body(revision=revision, token=token))),
            )


def test_remote_transport_is_get_bearer_bounded_and_response_is_closed() -> None:
    response = _Response(200, _body())
    transport = _Transport(response)

    result = fetch_remote_market_data_settings(_URL, _WORKER_TOKEN, transport=transport)

    assert result == RemoteMarketDataSettings(provider="akshare", revision=1, token=None)
    request, timeout_seconds = transport.requests[0]
    assert request.method == "GET"
    assert request.get_header("Authorization") == f"Bearer {_WORKER_TOKEN}"
    assert timeout_seconds == 5.0
    assert response.closed is True


def test_remote_settings_reject_oversized_response() -> None:
    response = _Response(200, b"x" * (MAX_REMOTE_SETTINGS_RESPONSE_BYTES + 1))

    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(_URL, _WORKER_TOKEN, transport=_Transport(response))
    assert response.closed is True


def test_remote_transport_failures_are_generic_and_close_http_errors() -> None:
    error = HTTPError(_URL, 302, "secret response", HTTPMessage(), None)

    with pytest.raises(RemoteMarketDataSettingsError) as raised:
        fetch_remote_market_data_settings(_URL, _WORKER_TOKEN, transport=_Transport(error))

    message = str(raised.value)
    assert "secret response" not in message
    assert _URL not in message
    assert _WORKER_TOKEN not in message
    assert error.fp is None or error.fp.closed

    with pytest.raises(RemoteMarketDataSettingsError) as transport_error:
        fetch_remote_market_data_settings(
            _URL,
            _WORKER_TOKEN,
            transport=_Transport(
                RemoteMarketDataSettingsError(f"{_URL} {_WORKER_TOKEN} response-body")
            ),
        )
    assert str(transport_error.value) == "managed market-data settings request failed"


def test_remote_settings_reject_duplicate_json_fields() -> None:
    body = (
        b'{"schemaVersion":"market-data-worker-settings-v1",'
        b'"provider":"akshare","revision":1,"revision":2,"token":null}'
    )

    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            _URL, _WORKER_TOKEN, transport=_Transport(_Response(200, body))
        )


def test_worker_credential_matches_internal_service_printable_ascii_bounds() -> None:
    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            _URL, "x" * 31, transport=_Transport(_Response(200, _body()))
        )
    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            _URL,
            "x" * 513,
            transport=_Transport(_Response(200, _body())),
        )
    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            _URL,
            "x" * 31 + "\n",
            transport=_Transport(_Response(200, _body())),
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://control.example.test/api/v1/internal/market-data/settings?token=secret",
        "https://control.example.test/api/v1/internal/market-data/settings#fragment",
        "https://control.example.test/api/v1/internal/market-data/settings/",
        "https://user:password@control.example.test/api/v1/internal/market-data/settings",
        "http://server:3002/api/v1/internal/market-data/settings",
    ],
)
def test_remote_settings_url_security_validation(url: str) -> None:
    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            url,
            _WORKER_TOKEN,
            transport=_Transport(_Response(200, _body())),
        )


def test_local_http_is_allowed_only_for_loopback_or_explicit_compose_origin() -> None:
    for url in (
        "http://localhost:3002/api/v1/internal/market-data/settings",
        "http://127.0.0.1:3002/api/v1/internal/market-data/settings",
        "http://[::1]:3002/api/v1/internal/market-data/settings",
    ):
        fetch_remote_market_data_settings(
            url,
            _WORKER_TOKEN,
            transport=_Transport(_Response(200, _body())),
        )

    with pytest.raises(RemoteMarketDataSettingsError):
        fetch_remote_market_data_settings(
            "http://server:3002/api/v1/internal/market-data/settings",
            _WORKER_TOKEN,
            transport=_Transport(_Response(200, _body())),
        )
    fetch_remote_market_data_settings(
        "http://server:3002/api/v1/internal/market-data/settings",
        _WORKER_TOKEN,
        allow_local_http=True,
        transport=_Transport(_Response(200, _body())),
    )


def test_remote_mode_requires_url_and_worker_token_and_is_opt_in() -> None:
    assert (
        load_remote_market_data_settings({}, transport=_Transport(_Response(200, _body()))) is None
    )
    with pytest.raises(RemoteMarketDataSettingsError):
        load_remote_market_data_settings(
            {"MARKET_DATA_SETTINGS_URL": _URL}, transport=_Transport(_Response(200, _body()))
        )
    with pytest.raises(RemoteMarketDataSettingsError):
        load_remote_market_data_settings(
            {"MARKET_DATA_SETTINGS_WORKER_TOKEN": _WORKER_TOKEN},
            transport=_Transport(_Response(200, _body())),
        )


def test_remote_mode_does_not_require_env_tushare_token_and_pins_endpoint() -> None:
    transport = _Transport(_Response(200, _body(provider="tushare", token="managed-token")))
    settings = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_PROVIDER": "untrusted-env-value",
            "TUSHARE_API_URL": "https://evil.example.test/steal",
        },
        remote_transport=transport,
    )

    assert settings.provider == "tushare"
    assert settings.token == "managed-token"
    assert settings.tushare_endpoint == "https://api.tushare.pro"
    assert settings.managed_revision == 1
    assert "managed-token" not in repr(settings)
    assert _WORKER_TOKEN not in repr(settings)


def test_remote_akshare_ignores_env_tushare_token() -> None:
    transport = _Transport(_Response(200, _body(provider="akshare", token=None)))
    settings = load_market_data_settings(
        {**_environment(), "TUSHARE_TOKEN": "env-secret"}, remote_transport=transport
    )
    assert settings.provider == "akshare"
    assert settings.token is None
    assert "env-secret" not in repr(settings)


def test_refresh_rejects_unavailable_remote_without_fallback(tmp_path: Path) -> None:
    initial = load_market_data_settings(
        {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)},
        remote_transport=_Transport(_Response(200, _body(provider="akshare"))),
    )

    with pytest.raises(RemoteMarketDataSettingsError):
        refresh_managed_market_data_settings(
            initial,
            remote_transport=_Transport(ConnectionError("secret body")),
        )


def test_remote_revision_namespace_is_separate_but_raw_root_is_shared(tmp_path: Path) -> None:
    settings = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_RAW_ROOT": str(tmp_path),
        },
        remote_transport=_Transport(_Response(200, _body(revision=7))),
    )
    runner = build_market_data_runner(settings)

    assert runner._checkpoint_store is not None  # pyright: ignore[reportPrivateUsage]
    assert runner._checkpoint_store.root == (  # pyright: ignore[reportPrivateUsage]
        tmp_path / "managed-checkpoints" / "akshare" / "7"
    )
    marker = tmp_path / "managed-checkpoints" / ".managed-settings-state-v1.json"
    assert marker.exists()
    marker_text = marker.read_text(encoding="utf-8")
    assert _WORKER_TOKEN not in marker_text
    assert "managed-token" not in marker_text
    collector = cast(MarketDataCollector, runner._collector)  # pyright: ignore[reportPrivateUsage]
    raw_storage = cast(  # pyright: ignore[reportPrivateUsage]
        LocalFileStorage,
        collector._raw_storage,  # pyright: ignore[reportPrivateUsage]
    )
    assert raw_storage._root == tmp_path  # pyright: ignore[reportPrivateUsage]
    quality_sink = cast(MarketDataQualitySink, collector._quality_sink)  # pyright: ignore[reportPrivateUsage]
    assert quality_sink.root == tmp_path / "market-quality"
    restarted = build_market_data_runner(settings)
    assert restarted._checkpoint_store is not None  # pyright: ignore[reportPrivateUsage]
    assert restarted._checkpoint_store.root == runner._checkpoint_store.root  # pyright: ignore[reportPrivateUsage]

    newer = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_RAW_ROOT": str(tmp_path),
        },
        remote_transport=_Transport(_Response(200, _body(revision=8))),
    )
    newer_runner = build_market_data_runner(newer)
    assert newer_runner._checkpoint_store is not None  # pyright: ignore[reportPrivateUsage]
    assert newer_runner._checkpoint_store.root == (  # pyright: ignore[reportPrivateUsage]
        tmp_path / "managed-checkpoints" / "akshare" / "8"
    )  # pyright: ignore[reportPrivateUsage]


def test_managed_revision_digest_is_keyed_and_requires_valid_worker_credential(
    tmp_path: Path,
) -> None:
    settings = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_RAW_ROOT": str(tmp_path),
        },
        remote_transport=_Transport(_Response(200, _body(revision=7))),
    )
    build_market_data_runner(settings)
    marker = tmp_path / "managed-checkpoints" / ".managed-settings-state-v1.json"
    marker_text = marker.read_text(encoding="utf-8")
    digest = json.loads(marker_text)["digest"]
    material = b"akshare\x00"
    plain_digest = hashlib.sha256(material).hexdigest()
    expected_digest = hmac.new(_WORKER_TOKEN.encode(), material, hashlib.sha256).hexdigest()
    assert digest == expected_digest
    assert digest != plain_digest
    assert _WORKER_TOKEN not in marker_text

    alternate_worker = replace(
        settings,
        managed_settings_worker_token="alternate-worker-" + "y" * 32,
    )
    alternate_token = replace(settings, token="managed-token")
    alternate_provider = replace(settings, provider="tushare", token="managed-token")
    assert (
        runtime_module._managed_settings_digest(  # pyright: ignore[reportPrivateUsage]
            alternate_worker
        )
        != digest
    )
    assert (
        runtime_module._managed_settings_digest(  # pyright: ignore[reportPrivateUsage]
            alternate_token
        )
        != digest
    )
    assert (
        runtime_module._managed_settings_digest(  # pyright: ignore[reportPrivateUsage]
            alternate_provider
        )
        != digest
    )

    invalid_worker = replace(settings, managed_settings_worker_token="short")
    with pytest.raises(RuntimeError, match="worker credential"):
        runtime_module._managed_settings_digest(  # pyright: ignore[reportPrivateUsage]
            invalid_worker
        )


def test_same_revision_mutation_and_rollback_fail_closed(tmp_path: Path) -> None:
    env = {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)}
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(provider="akshare", revision=3))),
    )
    build_market_data_runner(initial)

    mutated = load_market_data_settings(
        env,
        remote_transport=_Transport(
            _Response(200, _body(provider="tushare", revision=3, token="managed"))
        ),
    )
    with pytest.raises(RuntimeError):
        build_market_data_runner(mutated)

    rollback = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(provider="akshare", revision=2))),
    )
    with pytest.raises(RuntimeError):
        build_market_data_runner(rollback)


def test_same_revision_reuses_runner_at_each_cycle_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)}
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=4))),
    )
    response = _Response(200, _body(revision=4))
    transport = _Transport(response)
    built: list[object] = []

    class FakeRunner:
        def run_cycle(self) -> MarketDataSyncSummary:
            return MarketDataSyncSummary("2026-09-05", 0, 0, 0, False, ())

    def build(settings: object, **_: object) -> FakeRunner:
        built.append(settings)
        return FakeRunner()

    monkeypatch.setattr("data_worker.jobs.market_data.runtime.build_market_data_runner", build)
    run_market_data_sync(initial, remote_transport=transport)

    assert len(built) == 1
    assert len(transport.requests) == 1


def test_changed_revision_builds_a_new_namespace_and_keeps_old_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {
        **_environment(),
        "MARKET_DATA_RAW_ROOT": str(tmp_path),
        "MARKET_DATA_RUN_MODE": "continuous",
        "MARKET_DATA_POLL_SECONDS": "60",
    }
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=4))),
    )
    responses = [
        _Response(200, _body(revision=5)),
    ]
    built: list[object] = []

    class FakeRunner:
        def run_cycle(self) -> MarketDataSyncSummary:
            return MarketDataSyncSummary("2026-09-05", 0, 0, 0, False, ())

    def build(settings: object, **_: object) -> FakeRunner:
        built.append(settings)
        return FakeRunner()

    def stop(_: float) -> None:
        raise StopIteration

    transport = _Transport(responses[0])
    monkeypatch.setattr("data_worker.jobs.market_data.runtime.build_market_data_runner", build)
    with pytest.raises(StopIteration):
        run_market_data_sync(initial, sleeper=stop, remote_transport=transport)

    assert len(built) == 2
    first = cast(MarketDataSyncSettings, built[0])
    second = cast(MarketDataSyncSettings, built[1])
    assert managed_market_data_checkpoint_root(first) == (
        tmp_path / "managed-checkpoints" / "akshare" / "4"
    )
    assert managed_market_data_checkpoint_root(second) == (
        tmp_path / "managed-checkpoints" / "akshare" / "5"
    )


def test_non_remote_settings_keep_legacy_checkpoint_root(tmp_path: Path) -> None:
    settings = load_market_data_settings({"MARKET_DATA_RAW_ROOT": str(tmp_path)})
    runner = build_market_data_runner(settings)
    assert runner._checkpoint_store is not None  # pyright: ignore[reportPrivateUsage]
    assert runner._checkpoint_store.root == tmp_path  # pyright: ignore[reportPrivateUsage]

    custom = build_market_data_runner(settings, checkpoint_root=tmp_path / "custom-checkpoints")
    assert custom._checkpoint_store is not None  # pyright: ignore[reportPrivateUsage]
    assert custom._checkpoint_store.root == tmp_path / "custom-checkpoints"  # pyright: ignore[reportPrivateUsage]


def test_managed_revision_marker_lock_serializes_old_and_new_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)}
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=0))),
    )
    build_market_data_runner(initial)
    revision_one = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=1))),
    )
    revision_two = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=2))),
    )

    original_read = runtime_module._read_managed_state  # pyright: ignore[reportPrivateUsage]
    old_read_started = threading.Event()
    release_old_read = threading.Event()
    new_done = threading.Event()
    first_read = True
    read_guard = threading.Lock()

    def controlled_read(path: Path) -> tuple[int, str, str] | None:
        nonlocal first_read
        result = original_read(path)
        with read_guard:
            should_pause = first_read
            first_read = False
        if should_pause:
            old_read_started.set()
            assert release_old_read.wait(2)
        return result

    monkeypatch.setattr(runtime_module, "_read_managed_state", controlled_read)
    monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0.2)
    old_errors: list[BaseException] = []
    new_errors: list[BaseException] = []

    def start_old() -> None:
        try:
            build_market_data_runner(revision_one)
        except BaseException as error:  # pragma: no cover - diagnostic handoff only
            old_errors.append(error)

    def start_new() -> None:
        try:
            build_market_data_runner(revision_two)
        except BaseException as error:  # pragma: no cover - diagnostic handoff only
            new_errors.append(error)
        finally:
            new_done.set()

    old_thread = threading.Thread(target=start_old)
    old_thread.start()
    assert old_read_started.wait(2)
    new_thread = threading.Thread(target=start_new)
    new_thread.start()
    assert new_done.wait(0.05) is False
    release_old_read.set()
    old_thread.join(2)
    new_thread.join(2)
    assert not old_thread.is_alive()
    assert not new_thread.is_alive()
    assert old_errors == []
    assert new_errors == []

    marker = tmp_path / "managed-checkpoints" / ".managed-settings-state-v1.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["revision"] == 2


def test_managed_revision_marker_lock_rejects_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_RAW_ROOT": str(tmp_path),
        },
        remote_transport=_Transport(_Response(200, _body(revision=1))),
    )
    build_market_data_runner(settings)
    lock_store = checkpoint_module.MarketDataCheckpointStore(tmp_path / "managed-checkpoints")
    monkeypatch.setattr(checkpoint_module, "_LOCK_WAIT_SECONDS", 0.01)

    with lock_store.locked(), pytest.raises(RuntimeError, match="managed market-data settings"):
        build_market_data_runner(settings)


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not available on Windows")
def test_managed_revision_marker_fsyncs_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_market_data_settings(
        {
            **_environment(),
            "MARKET_DATA_RAW_ROOT": str(tmp_path),
        },
        remote_transport=_Transport(_Response(200, _body(revision=1))),
    )
    real_fsync = os.fsync
    directory_fsyncs: list[bool] = []

    def recording_fsync(fd: int) -> None:
        directory_fsyncs.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(runtime_module.os, "fsync", recording_fsync)
    build_market_data_runner(settings)

    assert any(directory_fsyncs)


@pytest.mark.skipif(os.name == "nt", reason="directory fsync is not available on Windows")
def test_managed_revision_marker_directory_fsync_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)}
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=1))),
    )
    build_market_data_runner(initial)
    old_checkpoint = (
        tmp_path / "managed-checkpoints" / "akshare" / "1" / "market-data-checkpoint-v1.json"
    )
    old_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    old_checkpoint.write_text("preserve", encoding="utf-8")
    newer = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=2))),
    )
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EIO, "simulated directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(runtime_module.os, "fsync", fail_directory_fsync)
    with pytest.raises(RuntimeError, match="managed market-data settings state"):
        build_market_data_runner(newer)
    assert old_checkpoint.read_text(encoding="utf-8") == "preserve"
    assert list((tmp_path / "managed-checkpoints").glob("*.tmp")) == []


def test_managed_revision_marker_replace_is_atomic_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = {**_environment(), "MARKET_DATA_RAW_ROOT": str(tmp_path)}
    initial = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=1))),
    )
    build_market_data_runner(initial)
    newer = load_market_data_settings(
        env,
        remote_transport=_Transport(_Response(200, _body(revision=2))),
    )
    marker = tmp_path / "managed-checkpoints" / ".managed-settings-state-v1.json"

    def fail_replace(source: str, destination: str) -> None:
        del source, destination
        raise OSError("simulated replace interruption")

    monkeypatch.setattr(runtime_module.os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="managed market-data settings state"):
        build_market_data_runner(newer)
    assert json.loads(marker.read_text(encoding="utf-8"))["revision"] == 1
    assert list(marker.parent.glob("*.tmp")) == []
