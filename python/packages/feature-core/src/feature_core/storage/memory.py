from __future__ import annotations

from threading import Lock

from .models import (
    FeatureAsOfQuery,
    FeatureHistoryAppendResult,
    FeatureHistoryConflictError,
    FeatureHistoryRecord,
)


class InMemoryFeatureHistoryBackend:
    def __init__(self) -> None:
        self._records: dict[str, FeatureHistoryRecord] = {}
        self._lock = Lock()

    def append(
        self,
        records: tuple[FeatureHistoryRecord, ...],
    ) -> FeatureHistoryAppendResult:
        inserted = 0
        existing_count = 0
        with self._lock:
            staged = dict(self._records)
            for record in records:
                existing = staged.get(record.revision_id)
                if existing is None:
                    staged[record.revision_id] = record
                    inserted += 1
                elif existing == record:
                    existing_count += 1
                else:
                    raise FeatureHistoryConflictError(
                        "revision_id already exists with different content"
                    )
            self._records = staged
        return FeatureHistoryAppendResult(inserted, existing_count)

    def fetch_candidates(
        self,
        query: FeatureAsOfQuery,
    ) -> tuple[FeatureHistoryRecord, ...]:
        with self._lock:
            records = tuple(self._records.values())
        matching = [
            record
            for record in records
            if record.registry_ref.namespace_id == query.namespace_id
            and record.registry_ref.feature_name == query.feature_name
            and record.registry_ref.feature_version == query.feature_version
            and record.registry_ref.feature_fingerprint == query.feature_fingerprint
            and record.entity_id in query.entity_ids
            and query.event_start <= record.event_time < query.event_end
            and record.available_time <= query.as_of
        ]
        matching.sort(
            key=lambda record: (
                record.entity_id,
                record.event_time,
                record.available_time,
                record.processing_time,
                record.revision_id,
            ),
        )
        return tuple(matching[: query.candidate_limit])

    @property
    def records(self) -> tuple[FeatureHistoryRecord, ...]:
        with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))
