from __future__ import annotations

from threading import Lock

from .models import (
    BatchCheckpoint,
    BatchPartitionResult,
    CommitResult,
    CommitStatus,
)


class InMemoryFeaturePartitionStore:
    def __init__(self) -> None:
        self._results: dict[str, BatchPartitionResult] = {}
        self._lock = Lock()

    def get(self, run_id: str) -> BatchPartitionResult | None:
        with self._lock:
            return self._results.get(run_id)

    def resolve(self, run_id: str) -> BatchPartitionResult | None:
        return self.get(run_id)

    def commit(
        self,
        result: BatchPartitionResult,
    ) -> CommitResult[BatchPartitionResult]:
        run_id = result.metadata.run_id
        with self._lock:
            existing = self._results.get(run_id)
            if existing is None:
                self._results[run_id] = result
                return CommitResult(CommitStatus.CREATED, result)
            if existing.result_checksum == result.result_checksum:
                return CommitResult(CommitStatus.EXISTING_SAME, existing)
            return CommitResult(CommitStatus.CONFLICT, existing)

    @property
    def results(self) -> tuple[BatchPartitionResult, ...]:
        with self._lock:
            return tuple(self._results[key] for key in sorted(self._results))


class InMemoryBatchCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: dict[str, BatchCheckpoint] = {}
        self._lock = Lock()

    def get(self, run_id: str) -> BatchCheckpoint | None:
        with self._lock:
            return self._checkpoints.get(run_id)

    def commit(self, checkpoint: BatchCheckpoint) -> CommitResult[BatchCheckpoint]:
        with self._lock:
            existing = self._checkpoints.get(checkpoint.run_id)
            if existing is None:
                self._checkpoints[checkpoint.run_id] = checkpoint
                return CommitResult(CommitStatus.CREATED, checkpoint)
            if existing == checkpoint:
                return CommitResult(CommitStatus.EXISTING_SAME, existing)
            return CommitResult(CommitStatus.CONFLICT, existing)

    @property
    def checkpoints(self) -> tuple[BatchCheckpoint, ...]:
        with self._lock:
            return tuple(self._checkpoints[key] for key in sorted(self._checkpoints))
