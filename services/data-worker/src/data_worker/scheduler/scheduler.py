"""Task scheduler: owner-bound leases, retry backoff and dead-lettering."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from data_worker.scheduler.store import TaskStore

TaskStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "DEAD"]
type JsonValue = object


class PermanentError(Exception):
    """A non-retryable failure (bad input, auth, data error)."""

    def __init__(
        self, message: str = "permanent task failure", *, category: str = "permanent"
    ) -> None:
        self.category = category
        super().__init__(message)


class TransientError(Exception):
    """A retryable failure (rate limit, timeout, unavailable)."""

    def __init__(
        self, message: str = "transient task failure", *, category: str = "transient"
    ) -> None:
        self.category = category
        super().__init__(message)


class LeaseLostError(RuntimeError):
    """Raised when a worker loses its owner lease before finalization."""


@dataclass(frozen=True, slots=True)
class SchedulerLeaseContext:
    """Owner-bound context passed to jobs that need fenced page commits."""

    task_id: str
    lease_token: str
    lease_expires_at: datetime


# Short alias for callers that use the storage/scheduler lease vocabulary.
LeaseContext = SchedulerLeaseContext


@dataclass
class TaskRecord:
    """Durable state for one scheduled task."""

    task_id: str
    kind: str = "default"
    status: TaskStatus = "PENDING"
    attempts: int = 0
    max_attempts: int = 3
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    next_run_at: datetime | None = None
    checkpoint: JsonValue | None = None
    error_category: str | None = None
    error_detail: JsonValue | None = None
    dead_letter_detail: JsonValue | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        self,
        store: TaskStore,
        backoff: BackoffPolicy | None = None,
        lease_seconds: float = 60.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._backoff = backoff or BackoffPolicy()
        self._lease_seconds = lease_seconds
        self._now = now or (lambda: datetime.now(UTC))

    def run(
        self,
        task_id: str,
        job_fn: Callable[..., None],
        max_inline_attempts: int = 3,
    ) -> TaskStatus:
        """Run one leased scheduling cycle with bounded process-local retries.

        ``max_inline_attempts`` is distinct from the store's persisted
        ``max_attempts`` lease-acquisition budget. It is validated before any
        task record or lease is created.
        """

        if type(max_inline_attempts) is not int or max_inline_attempts <= 0:
            raise ValueError("max_inline_attempts must be a positive integer")
        record = self._store.get(task_id)
        if record.status == "SUCCEEDED":
            return "SUCCEEDED"  # confirmed data is never rewritten
        if record.status == "DEAD":
            return "DEAD"

        lease_token = self._store.acquire_lease(task_id, self._lease_seconds)
        if lease_token is None:
            refreshed = self._store.get(task_id)
            return (
                refreshed.status if refreshed.status in {"RUNNING", "FAILED", "DEAD"} else "RUNNING"
            )

        leased_record = self._store.get(task_id)
        if leased_record.lease_expires_at is None:
            # The store returned a token without a usable expiry.  Do not
            # invoke a job that could write beyond an owner fence.
            self._store.release_lease(task_id, lease_token)
            raise LeaseLostError(f"lease has no expiry for task {task_id}")
        lease_context = SchedulerLeaseContext(
            task_id=task_id,
            lease_token=lease_token,
            lease_expires_at=leased_record.lease_expires_at,
        )

        try:
            for attempt in range(max_inline_attempts):
                try:
                    _invoke_job(job_fn, lease_context)
                    if not self._store.mark_succeeded(task_id, lease_token):
                        raise LeaseLostError(f"lease lost before succeeding task {task_id}")
                    return "SUCCEEDED"
                except PermanentError as error:
                    if not self._store.mark_dead(
                        task_id,
                        lease_token,
                        error_category=error.category,
                        error_detail=_safe_error_detail(error.category),
                        dead_letter_detail=_safe_error_detail(error.category),
                    ):
                        raise LeaseLostError(
                            f"lease lost before dead-lettering task {task_id}"
                        ) from None
                    return "DEAD"
                except TransientError as error:
                    if attempt == max_inline_attempts - 1:
                        if not self._store.mark_failed(
                            task_id,
                            lease_token,
                            error_category=error.category,
                            error_detail=_safe_error_detail(error.category),
                            next_run_at=self._now()
                            + timedelta(seconds=self._backoff.delay(attempt)),
                        ):
                            raise LeaseLostError(
                                f"lease lost before failing task {task_id}"
                            ) from None
                        return self._store.get(task_id).status
                    time.sleep(self._backoff.delay(attempt))
                except Exception:
                    # An opaque provider/runtime failure must never leave a
                    # durable task in RUNNING after its lease is released.
                    # Persist only the controlled category, then re-raise the
                    # original exception for the caller's diagnostics.
                    if not self._store.mark_failed(
                        task_id,
                        lease_token,
                        error_category="internal",
                        error_detail=_safe_error_detail("internal"),
                        next_run_at=self._now() + timedelta(seconds=self._backoff.delay(0)),
                    ):
                        raise LeaseLostError(
                            f"lease lost before recording internal failure for task {task_id}"
                        ) from None
                    raise
            return "FAILED"
        finally:
            self._store.release_lease(task_id, lease_token)


def _invoke_job(job_fn: Callable[..., None], context: SchedulerLeaseContext) -> None:
    """Pass context to opt-in jobs while preserving zero-argument callers."""
    try:
        signature = inspect.signature(job_fn)
    except (TypeError, ValueError):
        job_fn(context)
        return
    positional = tuple(
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        }
    )
    if positional:
        job_fn(context)
    else:
        job_fn()


def _safe_error_detail(category: str) -> dict[str, str]:
    """Persist only a bounded category label, never raw exception text."""

    return {"message": f"{category} task failure"}
