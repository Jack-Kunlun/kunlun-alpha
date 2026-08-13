"""Task scheduler tests.

Covers the lifecycle state machine: success is never re-run (confirmed data
not rewritten), transient errors retry with backoff, permanent errors are
dead-lettered, leases prevent concurrent execution, and failed tasks replay.
"""

from __future__ import annotations

from data_worker.scheduler import (
    BackoffPolicy,
    InMemoryTaskStore,
    PermanentError,
    TaskScheduler,
    TransientError,
)


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

    first = scheduler.run("t5", always_fail, max_attempts=1)
    assert first == "FAILED"
    assert store.get("t5").status == "FAILED"

    second = scheduler.run("t5", lambda: None)
    assert second == "SUCCEEDED"
