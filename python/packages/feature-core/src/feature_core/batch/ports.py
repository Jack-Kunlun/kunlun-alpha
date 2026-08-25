from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from feature_core.registry import FeatureSpec

from .models import (
    BatchCheckpoint,
    BatchInputBatch,
    BatchInputRow,
    BatchPartition,
    BatchPartitionResult,
    CalculatedFeature,
    CommitResult,
    PartitionReadRequest,
)

type BatchCalculator = Callable[
    [FeatureSpec, BatchPartition, tuple[BatchInputRow, ...]],
    Iterable[CalculatedFeature],
]


class BatchPartitionSource(Protocol):
    def read_partition(self, request: PartitionReadRequest) -> BatchInputBatch: ...


class FeatureDependencyResolver(Protocol):
    def resolve(self, run_id: str) -> BatchPartitionResult | None: ...


class FeaturePartitionStore(Protocol):
    def get(self, run_id: str) -> BatchPartitionResult | None: ...

    def commit(
        self,
        result: BatchPartitionResult,
    ) -> CommitResult[BatchPartitionResult]: ...


class BatchCheckpointStore(Protocol):
    def get(self, run_id: str) -> BatchCheckpoint | None: ...

    def commit(self, checkpoint: BatchCheckpoint) -> CommitResult[BatchCheckpoint]: ...
