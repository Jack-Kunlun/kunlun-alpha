"""Task scheduler tests.

Covers the lifecycle state machine: success is never re-run (confirmed data
not rewritten), transient errors retry with backoff, permanent errors are
dead-lettered, leases prevent concurrent execution, and failed tasks replay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from data_worker.scheduler import (
    BackoffPolicy,
    InMemoryTaskStore,
    LeaseLostError,
    PermanentError,
    TaskScheduler,
    TransientError,
)


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 14, 7, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def _scheduler() -> tuple[TaskScheduler, InMemoryTaskStore]:
    store = InMemoryTaskStore()
    return TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0)), store


def test_success_marks_succeeded() -> None:
    scheduler, store = _scheduler()
    status = scheduler.run("t1", lambda: None)
    assert status == "SUCCEEDED"
    assert store.get("t1").status == "SUCCEEDED"


def test_succeeded_task_is_not_rerun() -> None:
    scheduler, _ = _scheduler()
    scheduler.run("t1", lambda: None)

    calls = 0

    def job() -> None:
        nonlocal calls
        calls += 1

    scheduler.run("t1", job)
    assert calls == 0  # confirmed data never rewritten


def test_transient_error_retries_then_succeeds() -> None:
    scheduler, _ = _scheduler()
    attempts = 0

    def job() -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise TransientError("throttled")

    status = scheduler.run("t2", job)
    assert status == "SUCCEEDED"
    assert attempts == 2


def test_controlled_transient_category_persists_through_backoff_and_dead_letter() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now, max_attempts=2)
    scheduler = TaskScheduler(
        store,
        backoff=BackoffPolicy(base_seconds=5.0, max_seconds=30.0),
        now=clock.now,
    )

    def fail() -> None:
        raise TransientError("opaque provider text", category="timeout")

    assert scheduler.run("controlled-timeout", fail, max_inline_attempts=1) == "FAILED"
    first = store.get("controlled-timeout")
    assert first.status == "FAILED"
    assert first.error_category == "timeout"
    assert first.error_detail == {"message": "timeout task failure"}
    assert first.next_run_at == clock.now() + timedelta(seconds=5)

    clock.advance(5)
    assert scheduler.run("controlled-timeout", fail, max_inline_attempts=1) == "DEAD"
    second = store.get("controlled-timeout")
    assert second.status == "DEAD"
    assert second.error_category == "timeout"
    assert second.dead_letter_detail == {"message": "retry limit reached"}


def test_permanent_error_is_dead_lettered_without_retry() -> None:
    scheduler, store = _scheduler()
    attempts = 0

    def job() -> None:
        nonlocal attempts
        attempts += 1
        raise PermanentError("bad input")

    status = scheduler.run("t3", job)
    assert status == "DEAD"
    assert store.get("t3").status == "DEAD"
    assert attempts == 1


def test_lease_prevents_concurrent_execution() -> None:
    scheduler, store = _scheduler()
    # Manually hold a lease on the task.
    store.acquire_lease("t4", lease_seconds=60)

    calls = 0

    def job() -> None:
        nonlocal calls
        calls += 1

    status = scheduler.run("t4", job)
    assert status == "RUNNING"
    assert calls == 0


def test_failed_task_can_replay() -> None:
    scheduler, store = _scheduler()

    def always_fail() -> None:
        raise TransientError("unavailable")

    first = scheduler.run("t5", always_fail, max_inline_attempts=1)
    assert first == "FAILED"
    assert store.get("t5").status == "FAILED"

    second = scheduler.run("t5", lambda: None)
    assert second == "SUCCEEDED"


def test_lease_uses_opaque_token_and_timezone_aware_expiry() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)

    token = store.acquire_lease("token-task", lease_seconds=30)

    assert isinstance(token, str)
    record = store.get("token-task")
    assert record.lease_token == token
    assert record.lease_expires_at == datetime(2026, 8, 14, 7, 0, 30, tzinfo=UTC)


def test_expired_lease_takeover_rejects_stale_owner_transitions() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    first_token = store.acquire_lease("takeover-task", lease_seconds=10)
    assert first_token is not None

    clock.advance(11)
    assert store.release_lease("takeover-task", first_token) is False
    assert store.mark_succeeded("takeover-task", first_token) is False
    assert store.mark_failed("takeover-task", first_token) is False
    assert store.mark_dead("takeover-task", first_token) is False
    assert store.save_checkpoint("takeover-task", first_token, {"cursor": "stale"}) is False

    second_token = store.acquire_lease("takeover-task", lease_seconds=10)
    assert second_token is not None
    assert second_token != first_token

    assert store.release_lease("takeover-task", first_token) is False
    assert store.mark_succeeded("takeover-task", first_token) is False
    assert store.mark_failed("takeover-task", first_token) is False
    assert store.mark_dead("takeover-task", first_token) is False
    assert store.get("takeover-task").lease_token == second_token


def test_next_run_at_blocks_lease_until_database_time_reaches_it() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    record = store.get("backoff-task")
    record.next_run_at = clock.now() + timedelta(seconds=20)

    assert store.acquire_lease("backoff-task", lease_seconds=10) is None
    clock.advance(20)
    assert store.acquire_lease("backoff-task", lease_seconds=10) is not None


def test_checkpoint_and_failure_details_round_trip_under_owner_cas() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    token = store.acquire_lease("checkpoint-task", lease_seconds=30)
    assert token is not None

    checkpoint = {"cursor": "page-2", "seen": ["600519.SH"]}
    assert store.save_checkpoint("checkpoint-task", token, checkpoint)
    assert store.get_checkpoint("checkpoint-task") == checkpoint

    next_run_at = clock.now() + timedelta(minutes=1)
    assert store.mark_failed(
        "checkpoint-task",
        token,
        error_category="transient",
        error_detail={"code": "timeout"},
        next_run_at=next_run_at,
    )
    failed = store.get("checkpoint-task")
    assert failed.status == "FAILED"
    assert failed.error_category == "transient"
    assert failed.error_detail == {"code": "timeout"}
    assert failed.next_run_at == next_run_at


def test_dead_letter_detail_is_persisted_for_permanent_failure() -> None:
    store = InMemoryTaskStore()
    token = store.acquire_lease("dead-task", lease_seconds=30)
    assert token is not None

    assert store.mark_dead(
        "dead-task",
        token,
        error_category="permanent",
        error_detail={"reason": "invalid_payload"},
        dead_letter_detail={"source": "provider-a"},
    )
    dead = store.get("dead-task")
    assert dead.status == "DEAD"
    assert dead.dead_letter_detail == {"source": "provider-a"}


def test_error_category_is_a_controlled_non_sensitive_value() -> None:
    store = InMemoryTaskStore()
    categories = ("unknown", "Authorization: Bearer abc", "x" * 129)
    for index, category in enumerate(categories):
        task_id = f"invalid-category-{index}"
        token = store.acquire_lease(task_id, lease_seconds=30)
        assert token is not None
        with pytest.raises(ValueError, match="error_category"):
            store.mark_failed(task_id, token, error_category=category)

        dead_task_id = f"invalid-dead-category-{index}"
        dead_token = store.acquire_lease(dead_task_id, lease_seconds=30)
        assert dead_token is not None
        with pytest.raises(ValueError, match="error_category"):
            store.mark_dead(dead_task_id, dead_token, error_category=category)


@pytest.mark.parametrize(
    "payload",
    [
        {"apiKey": "value"},
        {"privateKey": "value"},
        {"set-cookie": "session=value"},
        {"nested": {"Authorization": "Bearer value"}},
    ],
)
def test_json_payload_rejects_normalized_sensitive_keys(payload: object) -> None:
    store = InMemoryTaskStore()
    token = store.acquire_lease("sensitive-key-task", lease_seconds=30)
    assert token is not None

    with pytest.raises(ValueError, match="sensitive"):
        store.save_checkpoint("sensitive-key-task", token, payload)


@pytest.mark.parametrize(
    "payload",
    [
        "Authorization: Bearer abc",
        "Basic YWJj",
        "postgresql://user:password@example.invalid/db",
        "Cookie: session=secret",
        "https://user:password@example.invalid/private",
    ],
)
def test_json_payload_rejects_sensitive_string_values(payload: str) -> None:
    store = InMemoryTaskStore()
    token = store.acquire_lease("sensitive-value-task", lease_seconds=30)
    assert token is not None

    with pytest.raises(ValueError, match="sensitive"):
        store.mark_failed("sensitive-value-task", token, error_detail=payload)


def test_scheduler_does_not_persist_raw_sensitive_exception_text() -> None:
    store = InMemoryTaskStore()
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0))

    def job() -> None:
        raise TransientError("Authorization: Bearer abc")

    assert scheduler.run("redacted-error-task", job, max_inline_attempts=1) == "FAILED"
    detail = store.get("redacted-error-task").error_detail
    assert detail == {"message": "transient task failure"}


def test_persisted_attempt_limit_dead_letters_after_total_lease_attempts() -> None:
    store = InMemoryTaskStore(max_attempts=2)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0))

    def fail() -> None:
        raise TransientError("unavailable")

    assert scheduler.run("attempt-limit-task", fail, max_inline_attempts=1) == "FAILED"
    assert scheduler.run("attempt-limit-task", fail, max_inline_attempts=1) == "DEAD"
    assert scheduler.run("attempt-limit-task", lambda: None, max_inline_attempts=1) == "DEAD"
    record = store.get("attempt-limit-task")
    assert record.attempts == 2
    assert record.max_attempts == 2
    assert record.dead_letter_detail == {"message": "retry limit reached"}


@pytest.mark.parametrize("max_attempts", [0, -1, 0.5, True])
def test_scheduler_rejects_non_positive_inline_attempts_before_acquiring_lease(
    max_attempts: object,
) -> None:
    store = InMemoryTaskStore()
    scheduler = TaskScheduler(store)

    with pytest.raises(ValueError, match="max_inline_attempts must be a positive integer"):
        scheduler.run(
            "invalid-inline-attempts",
            lambda: None,
            max_inline_attempts=cast(int, max_attempts),
        )

    record = store.get("invalid-inline-attempts")
    assert record.status == "PENDING"
    assert record.attempts == 0
    assert record.lease_token is None


def test_crashed_task_at_persisted_attempt_limit_is_dead_without_running_job() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now, max_attempts=1)
    crashed = store.get("crashed-limit-task")
    crashed.status = "FAILED"
    crashed.attempts = 1
    crashed.max_attempts = 1
    crashed.lease_token = "crashed-owner"
    crashed.lease_expires_at = clock.now() - timedelta(seconds=1)
    scheduler = TaskScheduler(store, now=clock.now)
    called = False

    def should_not_run() -> None:
        nonlocal called
        called = True

    assert scheduler.run("crashed-limit-task", should_not_run) == "DEAD"
    assert called is False
    assert store.get("crashed-limit-task").dead_letter_detail == {"message": "retry limit reached"}


def test_scheduler_fails_closed_when_success_finalization_loses_lease() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0), now=clock.now)

    def job() -> None:
        clock.advance(61)

    with pytest.raises(LeaseLostError):
        scheduler.run("stale-success", job, max_inline_attempts=1)
    assert store.get("stale-success").status == "RUNNING"


def test_scheduler_fails_closed_when_failure_finalization_loses_lease() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0), now=clock.now)

    def job() -> None:
        clock.advance(61)
        raise TransientError("timeout")

    with pytest.raises(LeaseLostError):
        scheduler.run("stale-failed", job, max_inline_attempts=1)
    assert store.get("stale-failed").status == "RUNNING"


def test_scheduler_fails_closed_when_dead_letter_finalization_loses_lease() -> None:
    clock = _Clock()
    store = InMemoryTaskStore(now=clock.now)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0), now=clock.now)

    def job() -> None:
        clock.advance(61)
        raise PermanentError("invalid")

    with pytest.raises(LeaseLostError):
        scheduler.run("stale-dead", job, max_inline_attempts=1)
    assert store.get("stale-dead").status == "RUNNING"
