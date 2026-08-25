from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from .models import (
    FeatureAsOfQuery,
    FeatureHistoryAppendResult,
    FeatureHistoryRecord,
)


class FeatureHistoryBackend(Protocol):
    def append(
        self,
        records: tuple[FeatureHistoryRecord, ...],
    ) -> FeatureHistoryAppendResult: ...

    def fetch_candidates(
        self,
        query: FeatureAsOfQuery,
    ) -> tuple[FeatureHistoryRecord, ...]: ...


class ClickHouseFeatureClient(Protocol):
    def insert(
        self,
        table: str,
        rows: Sequence[Sequence[object]],
        *,
        column_names: Sequence[str],
    ) -> None: ...

    def query(
        self,
        sql: str,
        *,
        parameters: Mapping[str, object],
    ) -> Iterable[Mapping[str, object]]: ...
