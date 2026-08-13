"""Task scheduler: state machine, lease, backoff and dead-letter.

A task progresses PENDING -> RUNNING -> SUCCEEDED (or FAILED / DEAD). A
running task holds a lease so a second process does not re-execute it; when a
process dies the lease expires and another can take over. Transient errors are
retried with exponential backoff; permanent errors are dead-lettered (DEAD)
without retry. A task that already SUCCEEDED is never re-run, so confirmed
data is never rewritten.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data_worker.scheduler.store import TaskStore

TaskStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DEAD"]


class PermanentError(Exception):
    """A non-retryable failure (bad input, auth, data error)."""


class TransientError(Exception):
    """A retryable failure (rate limit, timeout, unavailable)."""


@dataclass
class TaskRecord:
    """State of one scheduled task."""

    task_id: str
    status: TaskStatus = "PENDING"
    attempts: int = 0
    lease_expires_at: float | None = None


@dataclass(frozen=True)
class BackoffPolicy:
    """Exponential backoff with a cap."""

    base_seconds: float = 1.0
    max_seconds: float = 60.0

    def delay(self, attempt: int) -> float:
        return min(self.base_seconds * (2**attempt), self.max_seconds)


class TaskScheduler:
    """Runs a task function through the lifecycle state machine."""

    def __init__(
        self, store: TaskStore, backoff: BackoffPolicy | None = None, lease_seconds: float = 60.0
    ) -> None:
        self._store = store
        self._backoff = backoff or BackoffPolicy()
        self._lease_seconds = lease_seconds

    def run(self, task_id: str, job_fn: Callable[[], None], max_attempts: int = 3) -> TaskStatus:
        record = self._store.get(task_id)
        if record.status == "SUCCEEDED":
            return "SUCCEEDED"  # confirmed data is never rewritten

        if not self._store.acquire_lease(task_id, self._lease_seconds):
            return "RUNNING"  # another process holds the lease

        try:
            for attempt in range(max_attempts):
                try:
                    job_fn()
                    self._store.mark_succeeded(task_id)
                    return "SUCCEEDED"
                except PermanentError:
                    self._store.mark_dead(task_id)
                    return "DEAD"
                except TransientError:
                    if attempt == max_attempts - 1:
                        self._store.mark_failed(task_id)
                        return "FAILED"
                    time.sleep(self._backoff.delay(attempt))
            return "FAILED"
        finally:
            self._store.release_lease(task_id)
