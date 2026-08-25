from __future__ import annotations

from .models import (
    FeatureAsOfQuery,
    FeatureHistoryAppendResult,
    FeatureHistoryConflictError,
    FeatureHistoryIntegrityError,
    FeatureHistoryPage,
    FeatureHistoryRecord,
    canonical_checksum,
)
from .ports import FeatureHistoryBackend


def _validate_candidate(
    record: object,
    query: FeatureAsOfQuery,
) -> FeatureHistoryRecord:
    if type(record) is not FeatureHistoryRecord:
        raise FeatureHistoryIntegrityError("history backend returned an invalid record type")
    if (
        record.registry_ref.namespace_id != query.namespace_id
        or record.registry_ref.feature_name != query.feature_name
        or record.registry_ref.feature_version != query.feature_version
        or record.registry_ref.feature_fingerprint != query.feature_fingerprint
        or record.entity_id not in query.entity_ids
        or not query.event_start <= record.event_time < query.event_end
    ):
        raise FeatureHistoryIntegrityError(
            "history backend returned a record outside the query boundary"
        )
    if record.available_time > query.as_of:
        raise FeatureHistoryIntegrityError("history backend returned a future-visible record")
    if record.processing_time > query.as_of:
        raise FeatureHistoryIntegrityError("history backend returned a future-processed record")
    if record.value_checksum != canonical_checksum(record.value):
        raise FeatureHistoryIntegrityError("history record value checksum is invalid")
    return record


class FeatureHistoryRepository:
    def __init__(self, backend: FeatureHistoryBackend) -> None:
        self._backend = backend

    def append(
        self,
        records: tuple[FeatureHistoryRecord, ...],
    ) -> FeatureHistoryAppendResult:
        if not records:
            raise FeatureHistoryIntegrityError(
                "feature history append requires at least one record"
            )
        by_revision: dict[str, FeatureHistoryRecord] = {}
        for record in records:
            if type(record) is not FeatureHistoryRecord:
                raise FeatureHistoryIntegrityError(
                    "feature history append contains an invalid record"
                )
            existing = by_revision.get(record.revision_id)
            if existing is not None and existing != record:
                raise FeatureHistoryConflictError("append batch contains a conflicting revision_id")
            by_revision[record.revision_id] = record
        return self._backend.append(tuple(by_revision.values()))

    def query_as_of(self, query: FeatureAsOfQuery) -> FeatureHistoryPage:
        candidates = self._backend.fetch_candidates(query)
        if len(candidates) >= query.candidate_limit:
            raise FeatureHistoryIntegrityError(
                "candidate limit reached before point-in-time selection"
            )

        revisions: dict[str, FeatureHistoryRecord] = {}
        for candidate in candidates:
            record = _validate_candidate(candidate, query)
            existing = revisions.get(record.revision_id)
            if existing is not None and existing != record:
                raise FeatureHistoryConflictError(
                    "same revision_id has conflicting historical payloads"
                )
            revisions[record.revision_id] = record

        grouped: dict[
            tuple[str, str, str, str, str, object],
            list[FeatureHistoryRecord],
        ] = {}
        for record in revisions.values():
            grouped.setdefault(record.logical_key, []).append(record)

        selected: list[FeatureHistoryRecord] = []
        for records in grouped.values():
            ordered = sorted(
                records,
                key=lambda record: record.visibility_order,
                reverse=True,
            )
            if (
                len(ordered) > 1
                and (
                    ordered[0].available_time,
                    ordered[0].processing_time,
                )
                == (
                    ordered[1].available_time,
                    ordered[1].processing_time,
                )
                and ordered[0].record_checksum != ordered[1].record_checksum
            ):
                raise FeatureHistoryConflictError(
                    "latest visible revision is ambiguous at the same timestamps"
                )
            selected.append(ordered[0])

        selected.sort(key=lambda record: (record.entity_id, record.event_time))
        truncated = len(selected) > query.max_rows
        page = tuple(selected[: query.max_rows])
        return FeatureHistoryPage(
            records=page,
            truncated=truncated,
            query_checksum=canonical_checksum(query),
        )
