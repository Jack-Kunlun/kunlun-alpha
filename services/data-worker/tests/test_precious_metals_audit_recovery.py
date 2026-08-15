"""Qualified RED coverage for the second-round P1-R07 recovery contract."""

from __future__ import annotations

import copy
import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector
from data_worker.raw import CaptureConflictError, LocalFileStorage
from data_worker.raw import manifest as manifest_module
from data_worker.scheduler import (
    BackoffPolicy,
    InMemoryTaskStore,
    PermanentError,
    TaskScheduler,
    TransientError,
)
from data_worker.storage import InMemoryFundStorage, LeaseContext, fund_checkpoint_key
from market_core.providers import (
    Provider,
    ProviderAuthError,
    ProviderDataError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RawFundProviderResponse,
)

_NOW = datetime(2026, 8, 13, 5, tzinfo=UTC)


def _item(value: str = "1.2500") -> dict[str, object]:
    return {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": value,
        "eventTime": "2026-08-13T01:00:00+00:00",
        "publishTime": "2026-08-13T02:00:00+00:00",
        "ingestTime": "2026-08-13T03:00:00+00:00",
        "availableTime": "2026-08-13T03:30:00+00:00",
        "processingTime": "2026-08-13T04:00:00+00:00",
        "source": "provider-x",
    }


def _response(
    items: list[dict[str, object]],
    next_cursor: str | None,
    *,
    run_id: str = "run-1",
    source_revision: str = "rev-1",
) -> RawFundProviderResponse:
    body = json.dumps(
        {"items": items, "nextCursor": next_cursor},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return RawFundProviderResponse(
        body=body,
        source="provider-x",
        request="GET /funds/nav?exchange=SH",
        ingest_time=datetime(2026, 8, 13, 3, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, 3, 30, tzinfo=UTC),
        endpoint_kind="nav",
        run_id=run_id,
        source_revision=source_revision,
    )


class _RawPagesProvider(Provider):
    def __init__(self, pages: dict[str | None, RawFundProviderResponse]) -> None:
        self.pages = pages
        self.calls: list[str | None] = []

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        self.calls.append(cursor)
        return self.pages[cursor]


class _RaisingProvider(Provider):
    """Provider fake that fails only at the raw fund fetch boundary."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.calls = 0

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        self.calls += 1
        raise self.error


class _SchedulerClock:
    def __init__(self) -> None:
        self.current = _NOW

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _collector(
    tmp_path: Path,
    provider: Provider,
    persistence: InMemoryFundStorage | None = None,
) -> FundCollector:
    return FundCollector(
        provider,
        LocalFileStorage(tmp_path),
        persistence or InMemoryFundStorage(),
        now=_NOW,
    )


def test_checkpoint_is_safe_and_marks_complete_only_after_final_page(tmp_path: Path) -> None:
    provider = _RawPagesProvider(
        {
            None: _response([_item()], "cursor-a"),
            "cursor-a": _response([_item("1.2600")], None),
        }
    )

    class _CommitCapture(InMemoryFundStorage):
        def __init__(self) -> None:
            super().__init__()
            self.commits: list[dict[str, object]] = []

        def commit_page(self, **kwargs: object):  # type: ignore[no-untyped-def]
            checkpoint = cast(dict[str, object], kwargs["checkpoint"])
            self.commits.append(copy.deepcopy(checkpoint))
            return super().commit_page(**kwargs)  # type: ignore[arg-type]

    persistence = _CommitCapture()
    result = _collector(tmp_path, provider, persistence).collect(
        "nav", "SH", collection_date="2026-08-13"
    )

    checkpoint = result.checkpoint
    assert "next_cursor" not in checkpoint
    assert "consumed_cursors" not in checkpoint
    assert checkpoint.get("run_id") == "run-1"
    assert checkpoint.get("kind") == "nav"
    assert checkpoint.get("exchange") == "SH"
    assert checkpoint.get("date") == "2026-08-13"
    assert checkpoint.get("committed_page_count") == 2
    assert isinstance(checkpoint.get("cursor_lineage_hash"), str)
    assert checkpoint.get("complete") is True
    assert [entry.get("complete") for entry in persistence.commits] == [False, True]


def test_restart_reads_checkpoint_and_rescans_from_first_page_with_new_capture(
    tmp_path: Path,
) -> None:
    provider = _RawPagesProvider({None: _response([_item()], None)})

    class _TrackingPersistence(InMemoryFundStorage):
        def __init__(self) -> None:
            super().__init__()
            self.checkpoint_reads: list[str] = []

        def get_checkpoint(self, task_id: str) -> dict[str, object] | None:
            self.checkpoint_reads.append(task_id)
            return super().get_checkpoint(task_id)

    persistence = _TrackingPersistence()
    collector = _collector(tmp_path, provider, persistence)
    context = LeaseContext("fund-task", "lease-1", datetime.now(UTC) + timedelta(minutes=5))
    collector.collect("nav", "SH", context=context, collection_date="2026-08-13")
    provider.calls.clear()
    collector.collect("nav", "SH", context=context, collection_date="2026-08-13")

    assert persistence.checkpoint_reads == [
        fund_checkpoint_key("fund-task", "nav", "SH"),
        fund_checkpoint_key("fund-task", "nav", "SH"),
    ]
    assert provider.calls == [None]
    assert len(persistence.observations("nav")) == 1
    assert len(persistence.evidence()) == 2


def _route_replay(
    collector: FundCollector,
    *,
    run_id: str,
    source_revision: str,
    attempt_id: str = "attempt-a",
) -> object:
    try:
        return collector.replay_captures(
            "nav",
            "provider-x",
            "2026-08-13",
            exchange="SH",
            run_id=run_id,
            source_revision=source_revision,
            attempt_id=attempt_id,
        )
    except TypeError as exc:
        pytest.fail(f"route-aware replay API is missing: {exc}")


def test_replay_route_isolates_run_and_revision(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    payload = json.dumps({"items": [_item()], "nextCursor": None}).encode("utf-8")
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        payload,
        capture_id="capture-run-a",
        endpoint_kind="nav",
        run_id="run-a",
        source_revision="rev-1",
        attempt_id="attempt-a",
        page_ordinal=0,
        ingest_time=_NOW,
        available_time=_NOW,
    )
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        payload,
        capture_id="capture-run-b",
        endpoint_kind="nav",
        run_id="run-b",
        source_revision="rev-1",
        attempt_id="attempt-b",
        page_ordinal=0,
        ingest_time=_NOW + timedelta(seconds=1),
        available_time=_NOW + timedelta(seconds=1),
    )
    collector = _collector(tmp_path, _RawPagesProvider({None: _response([_item()], None)}))

    result = _route_replay(collector, run_id="run-a", source_revision="rev-1")
    assert len(cast(list[object], getattr(result, "accepted", []))) == 1


def test_replay_reconstructs_multi_page_cursor_lineage_from_raw_payload(
    tmp_path: Path,
) -> None:
    storage = LocalFileStorage(tmp_path)
    first_payload = json.dumps(
        {"items": [_item()], "nextCursor": "cursor-a"}, separators=(",", ":")
    ).encode("utf-8")
    second_payload = json.dumps(
        {"items": [_item("1.2600")], "nextCursor": None}, separators=(",", ":")
    ).encode("utf-8")
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        first_payload,
        capture_id="capture-page-a",
        endpoint_kind="nav",
        run_id="run-a",
        source_revision="rev-1",
        attempt_id="attempt-a",
        page_ordinal=0,
        ingest_time=_NOW,
        available_time=_NOW,
    )
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        second_payload,
        capture_id="capture-page-b",
        endpoint_kind="nav",
        run_id="run-a",
        source_revision="rev-1",
        attempt_id="attempt-a",
        page_ordinal=1,
        # Replay runs at _NOW; keep this captured page available at the
        # processing clock so the trusted manifest floor remains point-in-time
        # valid while the test exercises cursor lineage.
        ingest_time=_NOW,
        available_time=_NOW,
    )
    collector = _collector(tmp_path, _RawPagesProvider({None: _response([_item()], None)}))

    result = _route_replay(collector, run_id="run-a", source_revision="rev-1")

    assert len(cast(list[object], getattr(result, "accepted", []))) == 2
    assert getattr(result, "checkpoint", {}).get("committed_page_count") == 2


def test_replay_provider_rejects_unknown_cursor_instead_of_page_zero_fallback() -> None:
    module = importlib.import_module("data_worker.jobs.precious_metals_funds.collector")
    replay_type = getattr(module, "_ReplayProvider", None)
    assert replay_type is not None
    provider = replay_type(
        "nav",
        [
            _response([_item()], "cursor-known"),
            _response([_item("1.2600")], None),
        ],
    )

    with pytest.raises(ValueError, match="cursor"):
        provider.fetch_fund_nav("SH", "cursor-unknown")


class _CrashBeforeCommit(InMemoryFundStorage):
    def commit_page(self, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated crash before page commit")


def test_restart_rescan_creates_new_attempt_and_explicit_replay_does_not_mix_pages(
    tmp_path: Path,
) -> None:
    first_provider = _RawPagesProvider(
        {None: _response([_item()], "cursor-a", run_id="run-rescan")}
    )
    with pytest.raises(RuntimeError, match="before page commit"):
        _collector(tmp_path, first_provider, _CrashBeforeCommit()).collect(
            "nav",
            "SH",
            collection_date="2026-08-13",
            run_id="run-rescan",
        )

    second_provider = _RawPagesProvider(
        {
            None: _response([_item()], "cursor-a", run_id="run-rescan"),
            "cursor-a": _response([_item("1.2600")], None, run_id="run-rescan"),
        }
    )
    persistence = InMemoryFundStorage()
    recovered = _collector(tmp_path, second_provider, persistence)
    recovered.collect(
        "nav",
        "SH",
        collection_date="2026-08-13",
        run_id="run-rescan",
    )

    manifests = LocalFileStorage(tmp_path).list("provider-x", "2026-08-13")
    assert len(manifests) == 3
    attempts = {manifest.attempt_id for manifest in manifests}
    assert None not in attempts
    assert len(attempts) == 2
    attempt_pages: dict[str, list[int | None]] = {}
    for manifest in manifests:
        assert manifest.attempt_id is not None
        attempt_pages.setdefault(manifest.attempt_id, []).append(manifest.page_ordinal)
    assert sorted(
        sorted(page for page in pages if page is not None) for pages in attempt_pages.values()
    ) == [
        [0],
        [0, 1],
    ]

    resumed_attempt = next(attempt for attempt, pages in attempt_pages.items() if len(pages) == 2)
    replayed = recovered.replay_captures(
        "nav",
        "provider-x",
        "2026-08-13",
        exchange="SH",
        run_id="run-rescan",
        source_revision="rev-1",
        attempt_id=resumed_attempt,
    )
    assert len(replayed.accepted) == 2
    assert replayed.checkpoint["attempt_id"] == resumed_attempt


def test_restart_reusing_provider_capture_id_fails_before_new_attempt_commit(
    tmp_path: Path,
) -> None:
    response = replace(_response([_item()], None, run_id="run-reuse"), capture_id="capture-reused")
    first_provider = _RawPagesProvider({None: response})
    with pytest.raises(RuntimeError, match="before page commit"):
        _collector(tmp_path, first_provider, _CrashBeforeCommit()).collect(
            "nav",
            "SH",
            collection_date="2026-08-13",
            run_id="run-reuse",
        )

    raw_storage = LocalFileStorage(tmp_path)
    first_manifest = raw_storage.list("provider-x", "2026-08-13")[0]
    assert first_manifest.attempt_id is not None

    restarted_persistence = InMemoryFundStorage()
    restarted = _collector(tmp_path, _RawPagesProvider({None: response}), restarted_persistence)
    with pytest.raises(CaptureConflictError):
        restarted.collect(
            "nav",
            "SH",
            collection_date="2026-08-13",
            run_id="run-reuse",
        )

    assert restarted_persistence.observations("nav") == []
    assert restarted_persistence.get_checkpoint(fund_checkpoint_key("default", "nav", "SH")) is None
    manifests = raw_storage.list("provider-x", "2026-08-13")
    assert len(manifests) == 1
    assert manifests[0].attempt_id == first_manifest.attempt_id


@pytest.mark.parametrize(
    ("ordinals", "message"),
    [([0, 2], "contiguous"), ([0, 0], "duplicate")],
)
def test_replay_rejects_duplicate_or_missing_page_ordinals(
    tmp_path: Path, ordinals: list[int], message: str
) -> None:
    storage = LocalFileStorage(tmp_path)
    payloads = (
        json.dumps({"items": [_item()], "nextCursor": "cursor-a"}).encode(),
        json.dumps({"items": [_item("1.2600")], "nextCursor": None}).encode(),
    )
    for index, ordinal in enumerate(ordinals):
        storage.put(
            "provider-x",
            "2026-08-13",
            "GET /funds/nav?exchange=SH",
            payloads[index],
            capture_id=f"capture-{index}",
            endpoint_kind="nav",
            run_id="run-ordinal",
            source_revision="rev-1",
            attempt_id="attempt-ordinal",
            page_ordinal=ordinal,
            ingest_time=_NOW + timedelta(seconds=index),
            available_time=_NOW + timedelta(seconds=index),
        )

    collector = _collector(tmp_path, _RawPagesProvider({None: _response([_item()], None)}))
    with pytest.raises(ValueError, match=message):
        collector.replay_captures(
            "nav",
            "provider-x",
            "2026-08-13",
            exchange="SH",
            run_id="run-ordinal",
            source_revision="rev-1",
            attempt_id="attempt-ordinal",
        )


def test_provider_without_source_revision_uses_controlled_sentinel(
    tmp_path: Path,
) -> None:
    sentinel = getattr(manifest_module, "SOURCE_REVISION_SENTINEL", None)
    assert isinstance(sentinel, str) and sentinel
    response = replace(_response([_item()], None, run_id="run-sentinel"), source_revision=None)
    provider = _RawPagesProvider({None: response})
    persistence = InMemoryFundStorage()
    collector = _collector(tmp_path, provider, persistence)

    result = collector.collect(
        "nav",
        "SH",
        collection_date="2026-08-13",
        run_id="run-sentinel",
    )
    manifest = LocalFileStorage(tmp_path).list("provider-x", "2026-08-13")[0]
    assert manifest.source_revision == sentinel
    assert result.checkpoint["source_revision"] == sentinel
    assert manifest.attempt_id is not None

    replayed = collector.replay_captures(
        "nav",
        "provider-x",
        "2026-08-13",
        exchange="SH",
        run_id="run-sentinel",
        source_revision=sentinel,
        attempt_id=manifest.attempt_id,
    )
    assert len(replayed.accepted) == 1


def test_provider_cannot_claim_reserved_source_revision_sentinel(tmp_path: Path) -> None:
    sentinel = manifest_module.SOURCE_REVISION_SENTINEL
    response = replace(_response([_item()], None, run_id="run-sentinel"), source_revision=sentinel)
    provider = _RawPagesProvider({None: response})
    persistence = InMemoryFundStorage()

    with pytest.raises(ValueError, match="source_revision"):
        _collector(tmp_path, provider, persistence).collect(
            "nav",
            "SH",
            collection_date="2026-08-13",
            run_id="run-sentinel",
        )

    assert persistence.observations("nav") == []
    assert persistence.get_checkpoint(fund_checkpoint_key("default", "nav", "SH")) is None
    assert LocalFileStorage(tmp_path).list("provider-x", "2026-08-13") == []


def test_public_collect_rejects_reserved_source_revision_sentinel_before_fetch(
    tmp_path: Path,
) -> None:
    sentinel = manifest_module.SOURCE_REVISION_SENTINEL
    provider = _RawPagesProvider({None: _response([_item()], None)})

    with pytest.raises(ValueError, match="source_revision"):
        _collector(tmp_path, provider).collect(
            "nav",
            "SH",
            collection_date="2026-08-13",
            source_revision=sentinel,
        )

    assert provider.calls == []
    assert LocalFileStorage(tmp_path).list("provider-x", "2026-08-13") == []


def test_replay_rejects_legacy_manifest_without_route(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    payload = json.dumps({"items": [_item()], "nextCursor": None}).encode("utf-8")
    storage.put(
        "provider-x",
        "2026-08-13",
        "GET /funds/nav?exchange=SH",
        payload,
        capture_id="capture-legacy",
        ingest_time=_NOW,
        available_time=_NOW,
    )
    collector = _collector(tmp_path, _RawPagesProvider({None: _response([_item()], None)}))

    with pytest.raises(ValueError, match="route"):
        _route_replay(collector, run_id="run-a", source_revision="rev-1")


@pytest.mark.parametrize(
    ("provider_error", "category"),
    (
        (ProviderTimeoutError("timeout secret"), "timeout"),
        (ProviderRateLimitError("rate secret"), "rate_limit"),
        (ProviderUnavailableError("unavailable secret"), "unavailable"),
    ),
)
def test_scheduler_collect_transient_provider_errors_retry_with_backoff_and_dead_letter(
    tmp_path: Path,
    provider_error: ProviderError,
    category: str,
) -> None:
    """Exercise TaskScheduler -> FundCollector -> provider, not only a mapper."""

    provider = _RaisingProvider(provider_error)
    collector = _collector(tmp_path, provider)
    clock = _SchedulerClock()
    store = InMemoryTaskStore(now=clock.now, max_attempts=2)
    scheduler = TaskScheduler(
        store,
        backoff=BackoffPolicy(base_seconds=5.0, max_seconds=30.0),
        now=clock.now,
    )

    def job(context: object) -> None:
        collector.collect(
            "nav",
            "SH",
            context=cast(LeaseContext, context),
            collection_date="2026-08-13",
        )

    first = scheduler.run("provider-transient", job, max_inline_attempts=1)
    first_record = store.get("provider-transient")
    assert first == "FAILED"
    assert first_record.status == "FAILED"
    assert first_record.attempts == 1
    assert first_record.error_category == category
    assert first_record.error_detail == {"message": f"{category} task failure"}
    assert first_record.dead_letter_detail is None
    assert first_record.next_run_at == clock.now() + timedelta(seconds=5)
    assert provider.calls == 1

    clock.advance(5)
    second = scheduler.run("provider-transient", job, max_inline_attempts=1)
    second_record = store.get("provider-transient")
    assert second == "DEAD"
    assert second_record.status == "DEAD"
    assert second_record.attempts == 2
    assert second_record.error_category == category
    assert second_record.dead_letter_detail == {"message": "retry limit reached"}
    assert second_record.next_run_at is None
    assert provider.calls == 2


@pytest.mark.parametrize(
    ("provider_error", "category"),
    (
        (ProviderAuthError("auth secret"), "auth"),
        (ProviderNotFoundError("not found secret"), "not_found"),
        (ProviderDataError("data secret"), "data_error"),
    ),
)
def test_scheduler_collect_permanent_provider_errors_dead_letter_without_retry(
    tmp_path: Path,
    provider_error: ProviderError,
    category: str,
) -> None:
    provider = _RaisingProvider(provider_error)
    collector = _collector(tmp_path, provider)
    clock = _SchedulerClock()
    store = InMemoryTaskStore(now=clock.now, max_attempts=3)
    scheduler = TaskScheduler(store, now=clock.now)

    def job(context: object) -> None:
        collector.collect(
            "nav",
            "SH",
            context=cast(LeaseContext, context),
            collection_date="2026-08-13",
        )

    status = scheduler.run("provider-permanent", job, max_inline_attempts=3)
    record = store.get("provider-permanent")
    assert status == "DEAD"
    assert record.status == "DEAD"
    assert record.attempts == 1
    assert record.error_category == category
    assert record.error_detail == {"message": f"{category} task failure"}
    assert record.dead_letter_detail == {"message": f"{category} task failure"}
    assert record.next_run_at is None
    assert provider.calls == 1


def test_scheduler_collect_unknown_provider_exception_is_internal_and_not_running(
    tmp_path: Path,
) -> None:
    provider = _RaisingProvider(RuntimeError("Authorization: Bearer opaque-secret"))
    collector = _collector(tmp_path, provider)
    clock = _SchedulerClock()
    store = InMemoryTaskStore(now=clock.now, max_attempts=3)
    scheduler = TaskScheduler(
        store,
        backoff=BackoffPolicy(base_seconds=5.0, max_seconds=30.0),
        now=clock.now,
    )

    def job(context: object) -> None:
        collector.collect(
            "nav",
            "SH",
            context=cast(LeaseContext, context),
            collection_date="2026-08-13",
        )

    with pytest.raises(RuntimeError, match="opaque-secret"):
        scheduler.run("provider-unknown", job, max_inline_attempts=1)

    record = store.get("provider-unknown")
    assert record.status == "FAILED"
    assert record.status != "RUNNING"
    assert record.error_category == "internal"
    assert record.error_detail == {"message": "internal task failure"}
    assert record.dead_letter_detail is None
    assert record.next_run_at == clock.now() + timedelta(seconds=5)
    assert provider.calls == 1


def test_provider_errors_map_to_safe_scheduler_categories() -> None:
    module = importlib.import_module("data_worker.jobs.precious_metals_funds.collector")
    mapper = getattr(module, "map_provider_error", None)
    assert callable(mapper)
    cases = (
        (ProviderTimeoutError(), "timeout", TransientError),
        (ProviderRateLimitError(), "rate_limit", TransientError),
        (ProviderUnavailableError(), "unavailable", TransientError),
        (ProviderAuthError(), "auth", PermanentError),
        (ProviderNotFoundError(), "not_found", PermanentError),
        (ProviderDataError(), "data_error", PermanentError),
        (RuntimeError("opaque"), "internal", PermanentError),
    )
    for error, category, expected_type in cases:
        mapped = mapper(error)
        assert isinstance(mapped, expected_type)
        assert getattr(mapped, "category", None) == category


def test_unknown_failure_does_not_leave_scheduler_task_running() -> None:
    store = InMemoryTaskStore(max_attempts=1)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0, max_seconds=0.0))

    def job(_context: object) -> None:
        raise RuntimeError("opaque provider failure")

    with pytest.raises(RuntimeError):
        scheduler.run("fund-task", job)

    record = store.get("fund-task")
    assert record.status != "RUNNING"
    assert record.error_category == "internal"


def test_legacy_nav_collector_is_not_a_public_last_wins_bypass() -> None:
    package = importlib.import_module("data_worker.jobs.precious_metals_funds")
    assert not hasattr(package, "NavCollector")
