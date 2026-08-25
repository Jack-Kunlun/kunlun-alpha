from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from feature_core.batch.models import JsonValue, RegistrySnapshotRef
from feature_core.registry import FeatureValueType

from .models import (
    FeatureAsOfQuery,
    FeatureHistoryAppendResult,
    FeatureHistoryConflictError,
    FeatureHistoryIntegrityError,
    FeatureHistoryRecord,
    canonical_json_text,
)
from .ports import ClickHouseFeatureClient

FEATURE_HISTORY_TABLE = "feature_history_v1"

FEATURE_HISTORY_COLUMNS = (
    "registry_namespace_id",
    "registry_head_fingerprint",
    "feature_name",
    "feature_version",
    "feature_fingerprint",
    "algorithm_version",
    "entity_id",
    "event_time",
    "available_time",
    "processing_time",
    "value_type",
    "value_json",
    "value_checksum",
    "materialization_id",
    "revision_nonce",
    "revision_id",
    "input_checksum",
    "calculator_implementation_fingerprint",
    "input_manifest_checksum",
    "lineage_checksum",
    "source_kind",
    "source_snapshot_version",
    "record_checksum",
)

_SELECT_COLUMNS = ",\n    ".join(FEATURE_HISTORY_COLUMNS)

FETCH_CANDIDATES_SQL = f"""
SELECT
    {_SELECT_COLUMNS}
FROM {FEATURE_HISTORY_TABLE}
WHERE registry_namespace_id = {{namespace_id:String}}
  AND feature_name = {{feature_name:String}}
  AND feature_version = {{feature_version:String}}
  AND feature_fingerprint = {{feature_fingerprint:String}}
  AND entity_id IN {{entity_ids:Array(String)}}
  AND event_time >= {{event_start:DateTime64(6, 'UTC')}}
  AND event_time < {{event_end:DateTime64(6, 'UTC')}}
  AND available_time <= {{as_of:DateTime64(6, 'UTC')}}
  AND processing_time <= {{as_of:DateTime64(6, 'UTC')}}
ORDER BY entity_id, event_time, available_time, processing_time, revision_id
LIMIT {{candidate_limit:UInt32}}
""".strip()

FETCH_REVISIONS_SQL = f"""
SELECT
    {_SELECT_COLUMNS}
FROM {FEATURE_HISTORY_TABLE}
WHERE revision_id IN {{revision_ids:Array(String)}}
ORDER BY revision_id, available_time, processing_time
LIMIT {{revision_limit:UInt32}}
""".strip()


class ClickHouseFeatureHistoryBackend:
    """ClickHouse adapter for append-only historical feature records."""

    def __init__(self, client: ClickHouseFeatureClient) -> None:
        self._client = client

    def append(
        self,
        records: tuple[FeatureHistoryRecord, ...],
    ) -> FeatureHistoryAppendResult:
        if not records:
            return FeatureHistoryAppendResult(inserted_count=0, existing_count=0)

        requested: dict[str, FeatureHistoryRecord] = {}
        for record in records:
            prior = requested.get(record.revision_id)
            if prior is not None and prior.record_checksum != record.record_checksum:
                raise FeatureHistoryConflictError(
                    f"revision_id {record.revision_id!r} has conflicting payloads"
                )
            requested.setdefault(record.revision_id, record)

        revision_limit = len(requested) * 16 + 1
        existing_rows = tuple(
            self._client.query(
                FETCH_REVISIONS_SQL,
                parameters={
                    "revision_ids": tuple(sorted(requested)),
                    "revision_limit": revision_limit,
                },
            )
        )
        if len(existing_rows) >= revision_limit:
            raise FeatureHistoryIntegrityError(
                "revision lookup exceeded its bounded candidate limit"
            )

        existing: dict[str, FeatureHistoryRecord] = {}
        for row in existing_rows:
            persisted = _record_from_row(row)
            if persisted.revision_id not in requested:
                raise FeatureHistoryIntegrityError(
                    "revision lookup returned a record outside the requested IDs"
                )
            prior = existing.get(persisted.revision_id)
            if prior is not None and prior.record_checksum != persisted.record_checksum:
                raise FeatureHistoryConflictError(
                    f"persisted revision_id {persisted.revision_id!r} is ambiguous"
                )
            existing.setdefault(persisted.revision_id, persisted)

        pending: list[FeatureHistoryRecord] = []
        existing_count = 0
        for revision_id, record in requested.items():
            persisted = existing.get(revision_id)
            if persisted is None:
                pending.append(record)
                continue
            if persisted.record_checksum != record.record_checksum:
                raise FeatureHistoryConflictError(
                    f"revision_id {revision_id!r} already has a different payload"
                )
            existing_count += 1

        if pending:
            self._client.insert(
                FEATURE_HISTORY_TABLE,
                tuple(_record_to_row(record) for record in pending),
                column_names=FEATURE_HISTORY_COLUMNS,
            )

        return FeatureHistoryAppendResult(
            inserted_count=len(pending),
            existing_count=existing_count,
        )

    def fetch_candidates(
        self,
        query: FeatureAsOfQuery,
    ) -> tuple[FeatureHistoryRecord, ...]:
        rows = self._client.query(
            FETCH_CANDIDATES_SQL,
            parameters={
                "namespace_id": query.namespace_id,
                "feature_name": query.feature_name,
                "feature_version": query.feature_version,
                "feature_fingerprint": query.feature_fingerprint,
                "entity_ids": query.entity_ids,
                "event_start": query.event_start,
                "event_end": query.event_end,
                "as_of": query.as_of,
                "candidate_limit": query.candidate_limit,
            },
        )
        return tuple(_record_from_row(row) for row in rows)


def _record_to_row(record: FeatureHistoryRecord) -> tuple[object, ...]:
    ref = record.registry_ref
    return (
        ref.namespace_id,
        ref.head_fingerprint,
        ref.feature_name,
        ref.feature_version,
        ref.feature_fingerprint,
        ref.algorithm_version,
        record.entity_id,
        record.event_time,
        record.available_time,
        record.processing_time,
        record.value_type.value,
        canonical_json_text(record.value),
        record.value_checksum,
        record.materialization_id,
        record.revision_nonce,
        record.revision_id,
        record.input_checksum,
        record.calculator_implementation_fingerprint,
        record.input_manifest_checksum,
        record.lineage_checksum,
        record.source_kind,
        record.source_snapshot_version,
        record.record_checksum,
    )


def _record_from_row(row: Mapping[str, object]) -> FeatureHistoryRecord:
    try:
        value_json = _row_text(row, "value_json")
        value = cast(JsonValue, json.loads(value_json))
        record = FeatureHistoryRecord._restore(  # pyright: ignore[reportPrivateUsage]
            registry_ref=RegistrySnapshotRef(
                namespace_id=_row_text(row, "registry_namespace_id"),
                head_fingerprint=_row_text(row, "registry_head_fingerprint"),
                feature_name=_row_text(row, "feature_name"),
                feature_version=_row_text(row, "feature_version"),
                feature_fingerprint=_row_text(row, "feature_fingerprint"),
                algorithm_version=_row_text(row, "algorithm_version"),
            ),
            entity_id=_row_text(row, "entity_id"),
            event_time=_row_datetime(row, "event_time"),
            available_time=_row_datetime(row, "available_time"),
            processing_time=_row_datetime(row, "processing_time"),
            value_type=FeatureValueType(_row_text(row, "value_type")),
            value=value,
            value_checksum=_row_text(row, "value_checksum"),
            materialization_id=_row_text(row, "materialization_id"),
            revision_nonce=_row_text(row, "revision_nonce"),
            revision_id=_row_text(row, "revision_id"),
            input_checksum=_row_text(row, "input_checksum"),
            calculator_implementation_fingerprint=_row_text(
                row, "calculator_implementation_fingerprint"
            ),
            input_manifest_checksum=_row_text(row, "input_manifest_checksum"),
            lineage_checksum=_row_text(row, "lineage_checksum"),
            source_kind=_row_text(row, "source_kind"),
            source_snapshot_version=_row_text(row, "source_snapshot_version"),
        )
        if _row_text(row, "record_checksum") != record.record_checksum:
            raise FeatureHistoryIntegrityError(
                "persisted record_checksum does not match the decoded record"
            )
        return record
    except FeatureHistoryIntegrityError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureHistoryIntegrityError(
            "ClickHouse returned an invalid historical feature row"
        ) from exc


def _row_text(row: Mapping[str, object], name: str) -> str:
    value = row[name]
    if type(value) is not str or not value:
        raise FeatureHistoryIntegrityError(f"ClickHouse column {name!r} is invalid")
    return value


def _row_datetime(row: Mapping[str, object], name: str) -> datetime:
    value = row[name]
    if type(value) is not datetime:
        raise FeatureHistoryIntegrityError(f"ClickHouse column {name!r} is invalid")
    return value
