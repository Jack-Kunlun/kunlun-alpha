from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from types import MappingProxyType
from typing import cast

from feature_core.registry import FeatureRegistry, FeatureSpec


class BatchValidationError(ValueError):
    pass


class BatchIntegrityError(RuntimeError):
    pass


class BatchConflictError(BatchIntegrityError):
    pass


class FutureDataLeakageError(BatchIntegrityError):
    pass


class SourceKind(StrEnum):
    CLICKHOUSE = "CLICKHOUSE"
    PARQUET = "PARQUET"


class ExecutionDisposition(StrEnum):
    COMMITTED = "COMMITTED"
    REPLAYED = "REPLAYED"
    RECOVERED = "RECOVERED"


class InputOrigin(StrEnum):
    SOURCE_CONTRACT = "SOURCE_CONTRACT"
    FEATURE_DEPENDENCY = "FEATURE_DEPENDENCY"


class CompletenessStatus(StrEnum):
    COMPLETE = "COMPLETE"
    COMPLETE_EMPTY = "COMPLETE_EMPTY"


class CommitStatus(StrEnum):
    CREATED = "CREATED"
    EXISTING_SAME = "EXISTING_SAME"
    CONFLICT = "CONFLICT"


type JsonValue = None | bool | int | str | tuple[JsonValue, ...] | Mapping[str, JsonValue]

_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise BatchValidationError(f"{field} must be a non-empty string")
    return value


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise BatchValidationError(f"{field} must be timezone-aware")
    return value


def _require_fingerprint(value: object, field: str) -> str:
    if type(value) is not str or _FINGERPRINT.fullmatch(value) is None:
        raise BatchValidationError(f"{field} must be a sha256 fingerprint")
    return value


def freeze_json_value(value: object) -> JsonValue:
    if value is None or type(value) in (bool, int, str):
        return cast(JsonValue, value)
    if type(value) is float:
        raise BatchValidationError("floating-point values are not canonical JSON inputs")
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        frozen: dict[str, JsonValue] = {}
        for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0])):
            if type(key) is not str:
                raise BatchValidationError("canonical JSON object keys must be strings")
            frozen[key] = freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return tuple(freeze_json_value(item) for item in sequence)
    raise BatchValidationError(f"unsupported canonical JSON value: {type(value).__name__}")


def _canonical_data(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        raise BatchValidationError("floating-point values are not canonical")
    if isinstance(value, datetime):
        _require_aware(value, "datetime")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        result: dict[str, object] = {}
        for key, item in sorted(mapping.items(), key=lambda pair: str(pair[0])):
            if type(key) is not str:
                raise BatchValidationError("canonical mapping keys must be strings")
            result[key] = _canonical_data(item)
        return result
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        return [_canonical_data(item) for item in sequence]
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _canonical_data(getattr(value, field.name)) for field in fields(value)}
    raise BatchValidationError(f"unsupported canonical value: {type(value).__name__}")


def canonical_checksum(value: object) -> str:
    payload = json.dumps(
        _canonical_data(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_decimal_string(value: object) -> str:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise BatchValidationError("DECIMAL feature value must be a decimal string")
    negative = value.startswith("-")
    raw = value[1:] if negative else value
    integer, _, fraction = raw.partition(".")
    fraction = fraction.rstrip("0")
    if integer == "0" and not fraction:
        return "0"
    normalized = integer if not fraction else f"{integer}.{fraction}"
    return f"-{normalized}" if negative else normalized


def is_canonical_decimal(value: object) -> bool:
    try:
        return canonical_decimal_string(value) == value
    except BatchValidationError:
        return False


@dataclass(frozen=True, slots=True)
class BatchPartition:
    key: str
    start: datetime
    end: datetime
    decision_time: datetime

    def __post_init__(self) -> None:
        _require_text(self.key, "partition key")
        _require_aware(self.start, "partition start")
        _require_aware(self.end, "partition end")
        _require_aware(self.decision_time, "decision_time")
        if self.start >= self.end:
            raise BatchValidationError("partition must use a non-empty [start, end) interval")
        if self.end > self.decision_time:
            raise FutureDataLeakageError("partition end cannot exceed decision_time")


@dataclass(frozen=True, slots=True, order=True)
class BatchInputReference:
    origin: InputOrigin
    name: str
    version: str

    def __post_init__(self) -> None:
        if type(cast(object, self.origin)) is not InputOrigin:
            raise BatchValidationError("input origin must be an InputOrigin enum member")
        _require_text(self.name, "input reference name")
        _require_text(self.version, "input reference version")


@dataclass(frozen=True, slots=True)
class BatchInputLineage:
    reference: BatchInputReference
    source_revision: str | None = None
    upstream_run_id: str | None = None
    upstream_feature_fingerprint: str | None = None
    upstream_output_checksum: str | None = None

    def __post_init__(self) -> None:
        if type(cast(object, self.reference)) is not BatchInputReference:
            raise BatchValidationError("input lineage reference type is invalid")
        if self.reference.origin is InputOrigin.SOURCE_CONTRACT:
            _require_text(self.source_revision, "source_revision")
            if any(
                value is not None
                for value in (
                    self.upstream_run_id,
                    self.upstream_feature_fingerprint,
                    self.upstream_output_checksum,
                )
            ):
                raise BatchValidationError("source input cannot carry upstream feature lineage")
            return
        if self.source_revision is not None:
            raise BatchValidationError("feature dependency cannot carry source_revision")
        _require_fingerprint(self.upstream_run_id, "upstream_run_id")
        _require_fingerprint(
            self.upstream_feature_fingerprint,
            "upstream_feature_fingerprint",
        )
        _require_fingerprint(self.upstream_output_checksum, "upstream_output_checksum")


@dataclass(frozen=True, slots=True)
class RegistrySnapshotRef:
    namespace_id: str
    head_fingerprint: str
    feature_name: str
    feature_version: str
    feature_fingerprint: str
    algorithm_version: str

    def __post_init__(self) -> None:
        _require_text(self.namespace_id, "registry namespace_id")
        _require_fingerprint(self.head_fingerprint, "registry head_fingerprint")
        _require_text(self.feature_name, "feature name")
        _require_text(self.feature_version, "feature version")
        _require_fingerprint(self.feature_fingerprint, "feature fingerprint")
        _require_text(self.algorithm_version, "algorithm version")


@dataclass(frozen=True, slots=True)
class RegisteredFeature:
    registry: FeatureRegistry
    name: str

    def __post_init__(self) -> None:
        if type(cast(object, self.registry)) is not FeatureRegistry:
            raise BatchValidationError("registered feature requires an exact FeatureRegistry")
        _require_text(self.name, "registered feature name")
        try:
            self.registry.get(self.name)
        except KeyError as error:
            raise BatchValidationError("feature is not present in the trusted registry") from error

    @classmethod
    def from_registry(cls, registry: FeatureRegistry, name: str) -> RegisteredFeature:
        return cls(registry=registry, name=name)

    @property
    def spec(self) -> FeatureSpec:
        return self.registry.get(self.name)

    @property
    def snapshot_ref(self) -> RegistrySnapshotRef:
        spec = self.spec
        return RegistrySnapshotRef(
            namespace_id=self.registry.namespace_id,
            head_fingerprint=self.registry.head_fingerprint,
            feature_name=spec.name,
            feature_version=spec.version,
            feature_fingerprint=spec.semantic_fingerprint,
            algorithm_version=spec.algorithm_version,
        )


@dataclass(frozen=True, slots=True)
class PartitionReadRequest:
    registry_ref: RegistrySnapshotRef
    partition: BatchPartition
    required_source_contracts: tuple[BatchInputReference, ...]
    required_feature_dependencies: tuple[BatchInputReference, ...]

    @property
    def feature_name(self) -> str:
        return self.registry_ref.feature_name

    @property
    def feature_version(self) -> str:
        return self.registry_ref.feature_version

    @property
    def feature_fingerprint(self) -> str:
        return self.registry_ref.feature_fingerprint

    @property
    def allowed_contracts(self) -> tuple[tuple[str, str], ...]:
        references = (*self.required_source_contracts, *self.required_feature_dependencies)
        return tuple((reference.name, reference.version) for reference in references)


@dataclass(frozen=True, slots=True)
class BatchInputRow:
    row_id: str
    entity_id: str
    event_time: datetime
    available_time: datetime
    lineage: BatchInputLineage
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.row_id, "row_id")
        _require_text(self.entity_id, "entity_id")
        _require_aware(self.event_time, "input event_time")
        _require_aware(self.available_time, "input available_time")
        if type(cast(object, self.lineage)) is not BatchInputLineage:
            raise BatchValidationError("input lineage type is invalid")
        frozen = freeze_json_value(self.payload)
        if not isinstance(frozen, Mapping):
            raise BatchValidationError("input payload must remain an object")
        object.__setattr__(self, "payload", frozen)

    @property
    def contract_name(self) -> str:
        return self.lineage.reference.name

    @property
    def contract_version(self) -> str:
        return self.lineage.reference.version

    @property
    def source_revision(self) -> str | None:
        return self.lineage.source_revision


def rows_checksum(rows: tuple[BatchInputRow, ...]) -> str:
    ordered = tuple(sorted(rows, key=lambda row: (row.event_time, row.available_time, row.row_id)))
    return canonical_checksum(ordered)


@dataclass(frozen=True, slots=True)
class InputCompleteness:
    reference: BatchInputReference
    status: CompletenessStatus
    row_count: int
    rows_checksum: str

    def __post_init__(self) -> None:
        if type(cast(object, self.reference)) is not BatchInputReference:
            raise BatchValidationError("manifest reference type is invalid")
        if type(cast(object, self.status)) is not CompletenessStatus:
            raise BatchValidationError("manifest status type is invalid")
        if type(self.row_count) is not int or self.row_count < 0:
            raise BatchValidationError("manifest row_count must be a non-negative integer")
        _require_fingerprint(self.rows_checksum, "manifest rows_checksum")
        if self.status is CompletenessStatus.COMPLETE_EMPTY and self.row_count != 0:
            raise BatchValidationError("COMPLETE_EMPTY manifest entries must have zero rows")
        if self.status is CompletenessStatus.COMPLETE and self.row_count == 0:
            raise BatchValidationError("COMPLETE manifest entries must have at least one row")


@dataclass(frozen=True, slots=True)
class PartitionInputManifest:
    entries: tuple[InputCompleteness, ...]

    def __post_init__(self) -> None:
        if any(type(cast(object, entry)) is not InputCompleteness for entry in self.entries):
            raise BatchValidationError("manifest entry type is invalid")
        entries = tuple(sorted(self.entries, key=lambda entry: entry.reference))
        references = [entry.reference for entry in entries]
        if len(references) != len(set(references)):
            raise BatchValidationError("manifest references must be unique")
        object.__setattr__(self, "entries", entries)

    @classmethod
    def from_rows(
        cls,
        rows: tuple[BatchInputRow, ...],
        *,
        empty_references: tuple[BatchInputReference, ...] = (),
    ) -> PartitionInputManifest:
        grouped: dict[BatchInputReference, list[BatchInputRow]] = {}
        for row in rows:
            grouped.setdefault(row.lineage.reference, []).append(row)
        overlap = set(grouped).intersection(empty_references)
        if overlap:
            raise BatchValidationError("a manifest reference cannot be both populated and empty")
        entries = [
            InputCompleteness(
                reference=reference,
                status=CompletenessStatus.COMPLETE,
                row_count=len(group),
                rows_checksum=rows_checksum(tuple(group)),
            )
            for reference, group in grouped.items()
        ]
        entries.extend(
            InputCompleteness(
                reference=reference,
                status=CompletenessStatus.COMPLETE_EMPTY,
                row_count=0,
                rows_checksum=rows_checksum(()),
            )
            for reference in empty_references
        )
        return cls(entries=tuple(entries))


@dataclass(frozen=True, slots=True)
class BatchInputBatch:
    source_kind: SourceKind
    snapshot_version: str
    rows: tuple[BatchInputRow, ...]
    manifest: PartitionInputManifest

    def __post_init__(self) -> None:
        if type(cast(object, self.source_kind)) is not SourceKind:
            raise BatchValidationError("source_kind type is invalid")
        _require_text(self.snapshot_version, "snapshot_version")
        if any(type(cast(object, row)) is not BatchInputRow for row in self.rows):
            raise BatchValidationError("input row type is invalid")
        object.__setattr__(self, "rows", tuple(self.rows))
        if type(cast(object, self.manifest)) is not PartitionInputManifest:
            raise BatchValidationError("input manifest type is invalid")


@dataclass(frozen=True, slots=True)
class CalculatorIdentity:
    algorithm_version: str
    implementation_fingerprint: str

    def __post_init__(self) -> None:
        _require_text(self.algorithm_version, "calculator algorithm_version")
        _require_fingerprint(
            self.implementation_fingerprint,
            "calculator implementation_fingerprint",
        )


@dataclass(frozen=True, slots=True)
class CalculatedFeature:
    entity_id: str
    event_time: datetime
    value: object
    input_row_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.entity_id, "calculated entity_id")
        _require_aware(self.event_time, "calculated event_time")
        object.__setattr__(self, "input_row_ids", tuple(self.input_row_ids))


@dataclass(frozen=True, slots=True)
class MaterializedFeatureRow:
    feature_name: str
    feature_version: str
    feature_fingerprint: str
    algorithm_version: str
    partition_key: str
    entity_id: str
    event_time: datetime
    available_time: datetime
    decision_time: datetime
    value: JsonValue
    input_row_ids: tuple[str, ...]
    input_lineage: tuple[BatchInputLineage, ...]
    input_checksum: str
    source_kind: SourceKind
    source_snapshot_version: str


@dataclass(frozen=True, slots=True)
class BatchRunMetadata:
    run_id: str
    partition_key: str
    partition_start: datetime
    partition_end: datetime
    registry_ref: RegistrySnapshotRef
    source_kind: SourceKind
    source_snapshot_version: str
    decision_time: datetime
    data_cutoff_time: datetime | None
    calculator_implementation_fingerprint: str
    determinism_verified: bool
    input_manifest_checksum: str
    input_count: int
    output_count: int
    input_checksum: str
    output_checksum: str

    @property
    def feature_name(self) -> str:
        return self.registry_ref.feature_name

    @property
    def feature_version(self) -> str:
        return self.registry_ref.feature_version

    @property
    def feature_fingerprint(self) -> str:
        return self.registry_ref.feature_fingerprint

    @property
    def algorithm_version(self) -> str:
        return self.registry_ref.algorithm_version


@dataclass(frozen=True, slots=True)
class BatchCheckpoint:
    run_id: str
    partition_key: str
    feature_fingerprint: str
    input_checksum: str
    output_checksum: str
    result_checksum: str


@dataclass(frozen=True, slots=True)
class BatchPartitionResult:
    metadata: BatchRunMetadata
    rows: tuple[MaterializedFeatureRow, ...]
    input_manifest: PartitionInputManifest

    @property
    def result_checksum(self) -> str:
        return canonical_checksum(
            {
                "metadata": self.metadata,
                "input_manifest": self.input_manifest,
                "rows": self.rows,
            },
        )

    @property
    def checkpoint(self) -> BatchCheckpoint:
        return BatchCheckpoint(
            run_id=self.metadata.run_id,
            partition_key=self.metadata.partition_key,
            feature_fingerprint=self.metadata.feature_fingerprint,
            input_checksum=self.metadata.input_checksum,
            output_checksum=self.metadata.output_checksum,
            result_checksum=self.result_checksum,
        )


@dataclass(frozen=True, slots=True)
class BatchExecution:
    disposition: ExecutionDisposition
    result: BatchPartitionResult


@dataclass(frozen=True, slots=True)
class CommitResult[T]:
    status: CommitStatus
    persisted: T

    def __post_init__(self) -> None:
        if type(cast(object, self.status)) is not CommitStatus:
            raise BatchIntegrityError("commit result status must be an exact CommitStatus")
        if self.persisted is None:
            raise BatchIntegrityError("commit result must carry the persisted entity")
