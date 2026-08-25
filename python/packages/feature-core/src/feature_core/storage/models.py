from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Self, cast

from feature_core.batch.models import (
    BatchRunMetadata,
    BatchValidationError,
    JsonValue,
    MaterializedFeatureRow,
    RegisteredFeature,
    RegistrySnapshotRef,
    canonical_checksum,
    canonical_decimal_string,
    freeze_json_value,
)
from feature_core.registry import FeatureValueType

_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


class FeatureHistoryValidationError(ValueError):
    pass


class FeatureHistoryIntegrityError(RuntimeError):
    pass


class FeatureHistoryConflictError(FeatureHistoryIntegrityError):
    pass


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise FeatureHistoryValidationError(f"{field} must be a non-empty string")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise FeatureHistoryValidationError(f"{field} must be timezone-aware")
    return value


def _fingerprint(value: object, field: str) -> str:
    if type(value) is not str or _FINGERPRINT.fullmatch(value) is None:
        raise FeatureHistoryValidationError(f"{field} must be a sha256 fingerprint")
    return value


def _normalize_feature_value(
    value_type: FeatureValueType,
    value: object,
) -> JsonValue:
    if type(cast(object, value_type)) is not FeatureValueType:
        raise FeatureHistoryValidationError("value_type is invalid")
    try:
        if value_type is FeatureValueType.DECIMAL:
            return canonical_decimal_string(value)
        if value_type is FeatureValueType.INTEGER:
            if type(value) is not int:
                raise FeatureHistoryValidationError("INTEGER feature value must be an integer")
            return value
        if value_type is FeatureValueType.BOOLEAN:
            if type(value) is not bool:
                raise FeatureHistoryValidationError("BOOLEAN feature value must be a boolean")
            return value
        if value_type is FeatureValueType.STRING:
            if type(value) is not str:
                raise FeatureHistoryValidationError("STRING feature value must be a string")
            return value
        return freeze_json_value(value)
    except BatchValidationError as exc:
        raise FeatureHistoryValidationError(str(exc)) from exc


def _lineage_checksum(
    *,
    registry_ref: RegistrySnapshotRef,
    materialization_id: str,
    input_checksum: str,
    calculator_implementation_fingerprint: str,
    input_manifest_checksum: str,
    source_kind: str,
    source_snapshot_version: str,
) -> str:
    return canonical_checksum(
        {
            "registry_ref": registry_ref,
            "materialization_id": materialization_id,
            "input_checksum": input_checksum,
            "calculator_implementation_fingerprint": calculator_implementation_fingerprint,
            "input_manifest_checksum": input_manifest_checksum,
            "source_kind": source_kind,
            "source_snapshot_version": source_snapshot_version,
        }
    )


def _revision_id(
    *,
    registry_ref: RegistrySnapshotRef,
    entity_id: str,
    event_time: datetime,
    available_time: datetime,
    processing_time: datetime,
    value_type: FeatureValueType,
    value_checksum: str,
    materialization_id: str,
    lineage_checksum: str,
    revision_nonce: str,
) -> str:
    return canonical_checksum(
        {
            "registry_ref": registry_ref,
            "entity_id": entity_id,
            "event_time": event_time,
            "available_time": available_time,
            "processing_time": processing_time,
            "value_type": value_type,
            "value_checksum": value_checksum,
            "materialization_id": materialization_id,
            "lineage_checksum": lineage_checksum,
            "revision_nonce": revision_nonce,
        }
    )


def _json_data(value: JsonValue) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if isinstance(value, tuple):
        return [_json_data(item) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _json_data(item) for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    raise FeatureHistoryValidationError("feature value is not canonical JSON")


def canonical_json_text(value: JsonValue) -> str:
    return json.dumps(
        _json_data(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True, init=False)
class FeatureHistoryRecord:
    registry_ref: RegistrySnapshotRef
    entity_id: str
    event_time: datetime
    available_time: datetime
    processing_time: datetime
    value_type: FeatureValueType
    value: JsonValue
    value_checksum: str
    materialization_id: str
    revision_nonce: str
    revision_id: str
    input_checksum: str
    calculator_implementation_fingerprint: str
    input_manifest_checksum: str
    lineage_checksum: str
    source_kind: str
    source_snapshot_version: str

    def __post_init__(self) -> None:
        if type(cast(object, self.registry_ref)) is not RegistrySnapshotRef:
            raise FeatureHistoryValidationError("registry_ref type is invalid")
        _text(self.entity_id, "entity_id")
        _aware(self.event_time, "event_time")
        _aware(self.available_time, "available_time")
        _aware(self.processing_time, "processing_time")
        if self.available_time < self.event_time:
            raise FeatureHistoryValidationError("available_time cannot precede event_time")
        if self.processing_time < self.available_time:
            raise FeatureHistoryValidationError("processing_time cannot precede available_time")
        frozen = _normalize_feature_value(self.value_type, self.value)
        object.__setattr__(self, "value", frozen)
        _fingerprint(self.value_checksum, "value_checksum")
        if self.value_checksum != canonical_checksum(frozen):
            raise FeatureHistoryValidationError("value_checksum does not match value")
        for field, value in (
            ("materialization_id", self.materialization_id),
            ("revision_nonce", self.revision_nonce),
            ("source_kind", self.source_kind),
            ("source_snapshot_version", self.source_snapshot_version),
        ):
            _text(value, field)
        for field, value in (
            ("revision_id", self.revision_id),
            ("input_checksum", self.input_checksum),
            (
                "calculator_implementation_fingerprint",
                self.calculator_implementation_fingerprint,
            ),
            ("input_manifest_checksum", self.input_manifest_checksum),
            ("lineage_checksum", self.lineage_checksum),
        ):
            _fingerprint(value, field)
        expected_lineage = _lineage_checksum(
            registry_ref=self.registry_ref,
            materialization_id=self.materialization_id,
            input_checksum=self.input_checksum,
            calculator_implementation_fingerprint=self.calculator_implementation_fingerprint,
            input_manifest_checksum=self.input_manifest_checksum,
            source_kind=self.source_kind,
            source_snapshot_version=self.source_snapshot_version,
        )
        if self.lineage_checksum != expected_lineage:
            raise FeatureHistoryValidationError(
                "lineage_checksum does not match materialization provenance"
            )
        expected_revision = _revision_id(
            registry_ref=self.registry_ref,
            entity_id=self.entity_id,
            event_time=self.event_time,
            available_time=self.available_time,
            processing_time=self.processing_time,
            value_type=self.value_type,
            value_checksum=self.value_checksum,
            materialization_id=self.materialization_id,
            lineage_checksum=self.lineage_checksum,
            revision_nonce=self.revision_nonce,
        )
        if self.revision_id != expected_revision:
            raise FeatureHistoryValidationError(
                "revision_id does not match the historical feature payload"
            )

    @classmethod
    def _restore(
        cls,
        *,
        registry_ref: RegistrySnapshotRef,
        entity_id: str,
        event_time: datetime,
        available_time: datetime,
        processing_time: datetime,
        value_type: FeatureValueType,
        value: object,
        value_checksum: str,
        materialization_id: str,
        revision_nonce: str,
        revision_id: str,
        input_checksum: str,
        calculator_implementation_fingerprint: str,
        input_manifest_checksum: str,
        lineage_checksum: str,
        source_kind: str,
        source_snapshot_version: str,
    ) -> Self:
        record = object.__new__(cls)
        for field, field_value in (
            ("registry_ref", registry_ref),
            ("entity_id", entity_id),
            ("event_time", event_time),
            ("available_time", available_time),
            ("processing_time", processing_time),
            ("value_type", value_type),
            ("value", value),
            ("value_checksum", value_checksum),
            ("materialization_id", materialization_id),
            ("revision_nonce", revision_nonce),
            ("revision_id", revision_id),
            ("input_checksum", input_checksum),
            (
                "calculator_implementation_fingerprint",
                calculator_implementation_fingerprint,
            ),
            ("input_manifest_checksum", input_manifest_checksum),
            ("lineage_checksum", lineage_checksum),
            ("source_kind", source_kind),
            ("source_snapshot_version", source_snapshot_version),
        ):
            object.__setattr__(record, field, field_value)
        record.__post_init__()
        return record

    @classmethod
    def from_batch_materialization(
        cls,
        *,
        row: MaterializedFeatureRow,
        run: BatchRunMetadata,
        processing_time: datetime,
        value_type: FeatureValueType,
        revision_nonce: str,
    ) -> Self:
        if type(cast(object, row)) is not MaterializedFeatureRow:
            raise FeatureHistoryValidationError(
                "batch provenance requires a MaterializedFeatureRow"
            )
        if type(cast(object, run)) is not BatchRunMetadata:
            raise FeatureHistoryValidationError("batch provenance requires BatchRunMetadata")
        ref = run.registry_ref
        if (
            row.feature_name != ref.feature_name
            or row.feature_version != ref.feature_version
            or row.feature_fingerprint != ref.feature_fingerprint
            or row.algorithm_version != ref.algorithm_version
            or row.partition_key != run.partition_key
        ):
            raise FeatureHistoryValidationError(
                "materialized row does not match its batch run registry identity"
            )
        if (
            row.source_kind != run.source_kind
            or row.source_snapshot_version != run.source_snapshot_version
            or row.decision_time != run.decision_time
        ):
            raise FeatureHistoryValidationError(
                "materialized row does not match its batch run source provenance"
            )
        if not run.determinism_verified:
            raise FeatureHistoryValidationError(
                "batch run must verify determinism before historical storage"
            )
        if row.available_time > run.decision_time:
            raise FeatureHistoryValidationError(
                "batch row was not available at the run decision time"
            )
        frozen = _normalize_feature_value(value_type, row.value)
        value_checksum = canonical_checksum(frozen)
        lineage_checksum = _lineage_checksum(
            registry_ref=ref,
            materialization_id=run.run_id,
            input_checksum=row.input_checksum,
            calculator_implementation_fingerprint=run.calculator_implementation_fingerprint,
            input_manifest_checksum=run.input_manifest_checksum,
            source_kind=row.source_kind.value,
            source_snapshot_version=row.source_snapshot_version,
        )
        revision_id = _revision_id(
            registry_ref=ref,
            entity_id=row.entity_id,
            event_time=row.event_time,
            available_time=row.available_time,
            processing_time=processing_time,
            value_type=value_type,
            value_checksum=value_checksum,
            materialization_id=run.run_id,
            lineage_checksum=lineage_checksum,
            revision_nonce=revision_nonce,
        )
        return cls._restore(
            registry_ref=ref,
            entity_id=row.entity_id,
            event_time=row.event_time,
            available_time=row.available_time,
            processing_time=processing_time,
            value_type=value_type,
            value=frozen,
            value_checksum=value_checksum,
            materialization_id=run.run_id,
            revision_nonce=revision_nonce,
            revision_id=revision_id,
            input_checksum=row.input_checksum,
            calculator_implementation_fingerprint=run.calculator_implementation_fingerprint,
            input_manifest_checksum=run.input_manifest_checksum,
            lineage_checksum=lineage_checksum,
            source_kind=row.source_kind.value,
            source_snapshot_version=row.source_snapshot_version,
        )

    @property
    def logical_key(self) -> tuple[str, str, str, str, str, datetime]:
        ref = self.registry_ref
        return (
            ref.namespace_id,
            ref.feature_name,
            ref.feature_version,
            ref.feature_fingerprint,
            self.entity_id,
            self.event_time,
        )

    @property
    def visibility_order(self) -> tuple[datetime, datetime, str]:
        return self.available_time, self.processing_time, self.revision_id

    @property
    def record_checksum(self) -> str:
        return canonical_checksum(self)


@dataclass(frozen=True, slots=True)
class FeatureAsOfQuery:
    namespace_id: str
    feature_name: str
    feature_version: str
    feature_fingerprint: str
    entity_ids: tuple[str, ...]
    event_start: datetime
    event_end: datetime
    as_of: datetime
    max_rows: int = 10_000

    def __post_init__(self) -> None:
        for field, value in (
            ("namespace_id", self.namespace_id),
            ("feature_name", self.feature_name),
            ("feature_version", self.feature_version),
            ("feature_fingerprint", self.feature_fingerprint),
        ):
            _text(value, field)
        entity_ids = tuple(self.entity_ids)
        if not entity_ids or len(entity_ids) > 500:
            raise FeatureHistoryValidationError("entity_ids must contain between 1 and 500 items")
        if len(entity_ids) != len(set(entity_ids)):
            raise FeatureHistoryValidationError("entity_ids must be unique")
        for entity_id in entity_ids:
            _text(entity_id, "entity_id")
        object.__setattr__(self, "entity_ids", tuple(sorted(entity_ids)))
        _aware(self.event_start, "event_start")
        _aware(self.event_end, "event_end")
        _aware(self.as_of, "as_of")
        if self.event_start >= self.event_end:
            raise FeatureHistoryValidationError(
                "event range must use a non-empty [start, end) interval"
            )
        if type(self.max_rows) is not int or not 1 <= self.max_rows <= 100_000:
            raise FeatureHistoryValidationError("max_rows must be between 1 and 100000")

    @classmethod
    def for_feature(
        cls,
        feature: RegisteredFeature,
        *,
        entity_ids: tuple[str, ...],
        event_start: datetime,
        event_end: datetime,
        as_of: datetime,
        max_rows: int = 10_000,
    ) -> FeatureAsOfQuery:
        ref = feature.snapshot_ref
        return cls(
            namespace_id=ref.namespace_id,
            feature_name=ref.feature_name,
            feature_version=ref.feature_version,
            feature_fingerprint=ref.feature_fingerprint,
            entity_ids=entity_ids,
            event_start=event_start,
            event_end=event_end,
            as_of=as_of,
            max_rows=max_rows,
        )

    @property
    def candidate_limit(self) -> int:
        return self.max_rows * 16 + 1


@dataclass(frozen=True, slots=True)
class FeatureHistoryAppendResult:
    inserted_count: int
    existing_count: int


@dataclass(frozen=True, slots=True)
class FeatureHistoryPage:
    records: tuple[FeatureHistoryRecord, ...]
    truncated: bool
    query_checksum: str
