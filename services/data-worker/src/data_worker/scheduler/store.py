"""Task store."""

from __future__ import annotations

import time
from typing import Protocol

from data_worker.scheduler.scheduler import TaskRecord


class TaskStore(Protocol):
    """Persistence for task records and leases."""

    def get(self, task_id: str) -> TaskRecord: ...

    def acquire_lease(self, task_id: str, lease_seconds: float) -> bool: ...

    def release_lease(self, task_id: str) -> None: ...

    def mark_succeeded(self, task_id: str) -> None: ...

    def mark_failed(self, task_id: str) -> None: ...

    def mark_dead(self, task_id: str) -> None: ...


class InMemoryTaskStore:
    """In-memory task store with lease support."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}

    def get(self, task_id: str) -> TaskRecord:
        record = self._records.get(task_id)
        if record is None:
            record = TaskRecord(task_id=task_id)
            self._records[task_id] = record
        return record

    def acquire_lease(self, task_id: str, lease_seconds: float) -> bool:
        record = self.get(task_id)
        now = time.monotonic()
        if record.lease_expires_at is not None and record.lease_expires_at > now:
            return False
        record.status = "RUNNING"
        record.attempts += 1
        record.lease_expires_at = now + lease_seconds
        return True

    def release_lease(self, task_id: str) -> None:
        self.get(task_id).lease_expires_at = None

    def mark_succeeded(self, task_id: str) -> None:
        self.get(task_id).status = "SUCCEEDED"

    def mark_failed(self, task_id: str) -> None:
        self.get(task_id).status = "FAILED"

    def mark_dead(self, task_id: str) -> None:
        self.get(task_id).status = "DEAD"
