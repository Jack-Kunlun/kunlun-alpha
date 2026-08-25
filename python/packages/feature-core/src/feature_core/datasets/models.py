from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import cast

from feature_core.batch.models import canonical_checksum
from feature_core.storage.models import FeatureAsOfQuery

DATASET_MANIFEST_SCHEMA_VERSION = "1.0.0"

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")
_REBUILD_COMMAND_PREFIX = (
    "uv",
    "run",
    "--package",
    "feature-core",
    "python",
    "research/datasets/rebuild.py",
    "--manifest",
    "dataset-manifest.json",
    "--output",
)


class DatasetValidationError(ValueError):
    pass


class DatasetIntegrityError(RuntimeError):
    pass


class DatasetConflictError(DatasetIntegrityError):
    pass


class DatasetPartitionRole(StrEnum):
    TRAIN = "TRAIN"
    EVALUATION = "EVALUATION"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise DatasetValidationError(f"{field} must be a non-empty string")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise DatasetValidationError(f"duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _fingerprint(value: object, field: str) -> str:
    if type(value) is not str or _FINGERPRINT.fullmatch(value) is None:
        raise DatasetValidationError(f"{field} must be a sha256 fingerprint")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise DatasetValidationError(f"{field} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class DatasetSourceSpec:
    namespace_id: str
    feature_name: str
    feature_version: str
    feature_fingerprint: str
    entity_ids: tuple[str, ...]
    event_start: datetime
    event_end: datetime
    as_of: datetime
    max_rows: int = 100_000

    def __post_init__(self) -> None:
        query = FeatureAsOfQuery(
            namespace_id=self.namespace_id,
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            feature_fingerprint=self.feature_fingerprint,
            entity_ids=self.entity_ids,
            event_start=self.event_start,
            event_end=self.event_end,
            as_of=self.as_of,
            max_rows=self.max_rows,
        )
        _fingerprint(query.feature_fingerprint, "feature_fingerprint")
        object.__setattr__(self, "entity_ids", query.entity_ids)

    @classmethod
    def from_query(cls, query: FeatureAsOfQuery) -> DatasetSourceSpec:
        return cls(
            namespace_id=query.namespace_id,
            feature_name=query.feature_name,
            feature_version=query.feature_version,
            feature_fingerprint=query.feature_fingerprint,
            entity_ids=query.entity_ids,
            event_start=query.event_start,
            event_end=query.event_end,
            as_of=query.as_of,
            max_rows=query.max_rows,
        )

    def to_query(self) -> FeatureAsOfQuery:
        return FeatureAsOfQuery(
            namespace_id=self.namespace_id,
            feature_name=self.feature_name,
            feature_version=self.feature_version,
            feature_fingerprint=self.feature_fingerprint,
            entity_ids=self.entity_ids,
            event_start=self.event_start,
            event_end=self.event_end,
            as_of=self.as_of,
            max_rows=self.max_rows,
        )

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.namespace_id,
            self.feature_name,
            self.feature_version,
            self.feature_fingerprint,
        )

    @property
    def source_checksum(self) -> str:
        return canonical_checksum(self)

    @property
    def decision_time(self) -> datetime:
        """Point-in-time cutoff applied to every sample returned by this source."""
        return self.as_of


def _sources_overlap(left: DatasetSourceSpec, right: DatasetSourceSpec) -> bool:
    return left.identity == right.identity and _sample_windows_overlap(left, right)


def _sample_windows_overlap(left: DatasetSourceSpec, right: DatasetSourceSpec) -> bool:
    return (
        not set(left.entity_ids).isdisjoint(right.entity_ids)
        and left.event_start < right.event_end
        and right.event_start < left.event_end
    )


@dataclass(frozen=True, slots=True)
class DatasetPartitionSpec:
    partition_id: str
    role: DatasetPartitionRole
    sources: tuple[DatasetSourceSpec, ...]

    def __post_init__(self) -> None:
        if type(self.partition_id) is not str or _IDENTIFIER.fullmatch(self.partition_id) is None:
            raise DatasetValidationError(
                "partition_id must use lowercase letters, digits, and hyphens"
            )
        if type(cast(object, self.role)) is not DatasetPartitionRole:
            raise DatasetValidationError("partition role is invalid")
        sources = tuple(self.sources)
        if not sources:
            raise DatasetValidationError("dataset partition requires at least one source")
        for source in sources:
            if type(cast(object, source)) is not DatasetSourceSpec:
                raise DatasetValidationError("dataset partition source type is invalid")
        if len({source.source_checksum for source in sources}) != len(sources):
            raise DatasetValidationError("dataset partition contains duplicate sources")
        for index, left in enumerate(sources):
            for right in sources[index + 1 :]:
                if _sources_overlap(left, right):
                    raise DatasetValidationError(
                        "dataset partition sources overlap for the same feature and entities"
                    )
        object.__setattr__(
            self,
            "sources",
            tuple(sorted(sources, key=lambda source: source.source_checksum)),
        )


@dataclass(frozen=True, slots=True)
class DatasetExportRequest:
    dataset_name: str
    dataset_version: str
    created_at: datetime
    partitions: tuple[DatasetPartitionSpec, ...]
    rebuild_command: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.dataset_name) is not str or _IDENTIFIER.fullmatch(self.dataset_name) is None:
            raise DatasetValidationError(
                "dataset_name must use lowercase letters, digits, and hyphens"
            )
        if (
            type(self.dataset_version) is not str
            or _VERSION.fullmatch(self.dataset_version) is None
        ):
            raise DatasetValidationError("dataset_version must be semantic x.y.z")
        _aware(self.created_at, "created_at")
        partitions = tuple(self.partitions)
        if not partitions:
            raise DatasetValidationError("dataset requires partitions")
        if len({partition.partition_id for partition in partitions}) != len(partitions):
            raise DatasetValidationError("dataset partition IDs must be unique")
        roles = {partition.role for partition in partitions}
        if roles != {DatasetPartitionRole.TRAIN, DatasetPartitionRole.EVALUATION}:
            raise DatasetValidationError(
                "dataset requires distinct TRAIN and EVALUATION partitions"
            )
        for index, left in enumerate(partitions):
            for right in partitions[index + 1 :]:
                for left_source in left.sources:
                    for right_source in right.sources:
                        if left.role is not right.role:
                            overlaps = _sample_windows_overlap(left_source, right_source)
                            message = "TRAIN and EVALUATION partitions contain the same samples"
                        else:
                            overlaps = _sources_overlap(left_source, right_source)
                            message = "dataset partitions overlap for the same feature and entities"
                        if overlaps:
                            raise DatasetValidationError(message)
        if any(
            source.as_of > self.created_at
            for partition in partitions
            for source in partition.sources
        ):
            raise DatasetValidationError("dataset created_at cannot precede source as_of")
        command = tuple(self.rebuild_command)
        if (
            len(command) != 12
            or command[: len(_REBUILD_COMMAND_PREFIX)] != _REBUILD_COMMAND_PREFIX
            or command[10] != "--repository-profile"
        ):
            raise DatasetValidationError(
                "rebuild_command must use the structured dataset rebuild contract"
            )
        for argument in command:
            _text(argument, "rebuild_command argument")
            if "\n" in argument or "\r" in argument:
                raise DatasetValidationError("rebuild_command arguments must not contain newlines")
        output_path = PurePosixPath(command[9])
        if (
            output_path.is_absolute()
            or output_path.as_posix() != command[9]
            or not output_path.parts
            or any(_IDENTIFIER.fullmatch(part) is None for part in output_path.parts)
        ):
            raise DatasetValidationError("rebuild_command output must be a canonical relative path")
        if _IDENTIFIER.fullmatch(command[11]) is None:
            raise DatasetValidationError(
                "rebuild_command repository profile must be a non-executable identifier"
            )
        object.__setattr__(
            self,
            "partitions",
            tuple(sorted(partitions, key=lambda partition: partition.partition_id)),
        )
        object.__setattr__(self, "rebuild_command", command)

    @property
    def build_spec_checksum(self) -> str:
        return canonical_checksum(self)


@dataclass(frozen=True, slots=True)
class DatasetPartitionArtifact:
    partition: DatasetPartitionSpec
    relative_path: str
    row_count: int
    content_checksum: str
    file_checksum: str
    schema_fingerprint: str
    source_lineage_checksums: tuple[str, ...]
    source_snapshot_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(cast(object, self.partition)) is not DatasetPartitionSpec:
            raise DatasetValidationError("partition artifact spec type is invalid")
        path = PurePosixPath(self.relative_path)
        expected = PurePosixPath(
            "partitions",
            self.partition.role.value.lower(),
            f"{self.partition.partition_id}.parquet",
        )
        if path != expected or path.is_absolute() or ".." in path.parts:
            raise DatasetValidationError("partition artifact path is not canonical")
        if type(self.row_count) is not int or self.row_count <= 0:
            raise DatasetValidationError("partition artifact row_count must be positive")
        for field, value in (
            ("content_checksum", self.content_checksum),
            ("file_checksum", self.file_checksum),
            ("schema_fingerprint", self.schema_fingerprint),
        ):
            _fingerprint(value, field)
        lineages = tuple(sorted(set(self.source_lineage_checksums)))
        if not lineages:
            raise DatasetValidationError("partition must retain source lineage checksums")
        for lineage in lineages:
            _fingerprint(lineage, "source_lineage_checksum")
        snapshots = tuple(sorted(set(self.source_snapshot_versions)))
        if not snapshots:
            raise DatasetValidationError("partition must retain source snapshot versions")
        for snapshot in snapshots:
            _text(snapshot, "source_snapshot_version")
        object.__setattr__(self, "source_lineage_checksums", lineages)
        object.__setattr__(self, "source_snapshot_versions", snapshots)


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_name: str
    dataset_version: str
    created_at: datetime
    partitions: tuple[DatasetPartitionArtifact, ...]
    rebuild_command: tuple[str, ...]
    build_spec_checksum: str
    writer_name: str
    writer_version: str
    schema_version: str = DATASET_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DATASET_MANIFEST_SCHEMA_VERSION:
            raise DatasetValidationError("dataset manifest schema version is unsupported")
        artifacts = tuple(self.partitions)
        request = DatasetExportRequest(
            dataset_name=self.dataset_name,
            dataset_version=self.dataset_version,
            created_at=self.created_at,
            partitions=tuple(artifact.partition for artifact in artifacts),
            rebuild_command=self.rebuild_command,
        )
        if request.build_spec_checksum != self.build_spec_checksum:
            raise DatasetIntegrityError("manifest build_spec_checksum does not match its request")
        if len({artifact.partition.partition_id for artifact in artifacts}) != len(artifacts):
            raise DatasetValidationError("manifest partition artifacts must be unique")
        _text(self.writer_name, "writer_name")
        _text(self.writer_version, "writer_version")
        object.__setattr__(
            self,
            "partitions",
            tuple(sorted(artifacts, key=lambda artifact: artifact.partition.partition_id)),
        )
        object.__setattr__(self, "rebuild_command", request.rebuild_command)

    @property
    def request(self) -> DatasetExportRequest:
        return DatasetExportRequest(
            dataset_name=self.dataset_name,
            dataset_version=self.dataset_version,
            created_at=self.created_at,
            partitions=tuple(artifact.partition for artifact in self.partitions),
            rebuild_command=self.rebuild_command,
        )

    @property
    def manifest_checksum(self) -> str:
        return canonical_checksum(self)

    def to_json(self) -> str:
        payload = _manifest_to_data(self)
        payload["manifest_checksum"] = self.manifest_checksum
        return (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @classmethod
    def from_json(cls, text: str) -> DatasetManifest:
        try:
            payload = _mapping(
                cast(object, json.loads(text, object_pairs_hook=_reject_duplicate_pairs)),
                "manifest",
            )
            _exact_keys(
                payload,
                {
                    "schema_version",
                    "dataset_name",
                    "dataset_version",
                    "created_at",
                    "partitions",
                    "rebuild_command",
                    "build_spec_checksum",
                    "writer_name",
                    "writer_version",
                    "manifest_checksum",
                },
                "manifest",
            )
            artifacts = tuple(
                _artifact_from_data(item)
                for item in _sequence(payload.get("partitions"), "partitions")
            )
            manifest = cls(
                dataset_name=_string(payload.get("dataset_name"), "dataset_name"),
                dataset_version=_string(payload.get("dataset_version"), "dataset_version"),
                created_at=_datetime(payload.get("created_at"), "created_at"),
                partitions=artifacts,
                rebuild_command=tuple(
                    _string(item, "rebuild_command")
                    for item in _sequence(payload.get("rebuild_command"), "rebuild_command")
                ),
                build_spec_checksum=_string(
                    payload.get("build_spec_checksum"), "build_spec_checksum"
                ),
                writer_name=_string(payload.get("writer_name"), "writer_name"),
                writer_version=_string(payload.get("writer_version"), "writer_version"),
                schema_version=_string(payload.get("schema_version"), "schema_version"),
            )
            expected = _string(payload.get("manifest_checksum"), "manifest_checksum")
        except (DatasetValidationError, DatasetIntegrityError):
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DatasetValidationError("dataset manifest JSON is invalid") from exc
        if expected != manifest.manifest_checksum:
            raise DatasetIntegrityError("dataset manifest checksum is invalid")
        return manifest


def _source_to_data(source: DatasetSourceSpec) -> dict[str, object]:
    return {
        "namespace_id": source.namespace_id,
        "feature_name": source.feature_name,
        "feature_version": source.feature_version,
        "feature_fingerprint": source.feature_fingerprint,
        "entity_ids": list(source.entity_ids),
        "event_start": _utc_text(source.event_start),
        "event_end": _utc_text(source.event_end),
        "as_of": _utc_text(source.as_of),
        "max_rows": source.max_rows,
        "source_checksum": source.source_checksum,
    }


def _partition_to_data(partition: DatasetPartitionSpec) -> dict[str, object]:
    return {
        "partition_id": partition.partition_id,
        "role": partition.role.value,
        "sources": [_source_to_data(source) for source in partition.sources],
    }


def _artifact_to_data(artifact: DatasetPartitionArtifact) -> dict[str, object]:
    return {
        "partition": _partition_to_data(artifact.partition),
        "relative_path": artifact.relative_path,
        "row_count": artifact.row_count,
        "content_checksum": artifact.content_checksum,
        "file_checksum": artifact.file_checksum,
        "schema_fingerprint": artifact.schema_fingerprint,
        "source_lineage_checksums": list(artifact.source_lineage_checksums),
        "source_snapshot_versions": list(artifact.source_snapshot_versions),
    }


def _manifest_to_data(manifest: DatasetManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "dataset_name": manifest.dataset_name,
        "dataset_version": manifest.dataset_version,
        "created_at": _utc_text(manifest.created_at),
        "partitions": [_artifact_to_data(artifact) for artifact in manifest.partitions],
        "rebuild_command": list(manifest.rebuild_command),
        "build_spec_checksum": manifest.build_spec_checksum,
        "writer_name": manifest.writer_name,
        "writer_version": manifest.writer_version,
    }


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DatasetValidationError(f"{field} must be an object")
    mapping = cast(Mapping[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise DatasetValidationError(f"{field} keys must be strings")
    return cast(Mapping[str, object], mapping)


def _exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        raise DatasetValidationError(
            f"{field} keys differ: expected {sorted(expected)}, got {sorted(actual)}"
        )


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise DatasetValidationError(f"{field} must be an array")
    return tuple(cast(list[object], value))


def _string(value: object, field: str) -> str:
    return _text(value, field)


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise DatasetValidationError(f"{field} must be an integer")
    return value


def _datetime(value: object, field: str) -> datetime:
    text = _string(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DatasetValidationError(f"{field} must be an ISO datetime") from exc
    return _aware(parsed, field)


def _source_from_data(value: object) -> DatasetSourceSpec:
    data = _mapping(value, "source")
    _exact_keys(
        data,
        {
            "namespace_id",
            "feature_name",
            "feature_version",
            "feature_fingerprint",
            "entity_ids",
            "event_start",
            "event_end",
            "as_of",
            "max_rows",
            "source_checksum",
        },
        "source",
    )
    source = DatasetSourceSpec(
        namespace_id=_string(data.get("namespace_id"), "namespace_id"),
        feature_name=_string(data.get("feature_name"), "feature_name"),
        feature_version=_string(data.get("feature_version"), "feature_version"),
        feature_fingerprint=_string(data.get("feature_fingerprint"), "feature_fingerprint"),
        entity_ids=tuple(
            _string(item, "entity_id") for item in _sequence(data.get("entity_ids"), "entity_ids")
        ),
        event_start=_datetime(data.get("event_start"), "event_start"),
        event_end=_datetime(data.get("event_end"), "event_end"),
        as_of=_datetime(data.get("as_of"), "as_of"),
        max_rows=_integer(data.get("max_rows"), "max_rows"),
    )
    expected = _string(data.get("source_checksum"), "source_checksum")
    if expected != source.source_checksum:
        raise DatasetIntegrityError("dataset source checksum is invalid")
    return source


def _partition_from_data(value: object) -> DatasetPartitionSpec:
    data = _mapping(value, "partition")
    _exact_keys(data, {"partition_id", "role", "sources"}, "partition")
    try:
        role = DatasetPartitionRole(_string(data.get("role"), "role"))
    except ValueError as exc:
        raise DatasetValidationError("partition role is invalid") from exc
    return DatasetPartitionSpec(
        partition_id=_string(data.get("partition_id"), "partition_id"),
        role=role,
        sources=tuple(
            _source_from_data(item) for item in _sequence(data.get("sources"), "sources")
        ),
    )


def _artifact_from_data(value: object) -> DatasetPartitionArtifact:
    data = _mapping(value, "partition artifact")
    _exact_keys(
        data,
        {
            "partition",
            "relative_path",
            "row_count",
            "content_checksum",
            "file_checksum",
            "schema_fingerprint",
            "source_lineage_checksums",
            "source_snapshot_versions",
        },
        "partition artifact",
    )
    return DatasetPartitionArtifact(
        partition=_partition_from_data(data.get("partition")),
        relative_path=_string(data.get("relative_path"), "relative_path"),
        row_count=_integer(data.get("row_count"), "row_count"),
        content_checksum=_string(data.get("content_checksum"), "content_checksum"),
        file_checksum=_string(data.get("file_checksum"), "file_checksum"),
        schema_fingerprint=_string(data.get("schema_fingerprint"), "schema_fingerprint"),
        source_lineage_checksums=tuple(
            _string(item, "source_lineage_checksum")
            for item in _sequence(data.get("source_lineage_checksums"), "source_lineage_checksums")
        ),
        source_snapshot_versions=tuple(
            _string(item, "source_snapshot_version")
            for item in _sequence(data.get("source_snapshot_versions"), "source_snapshot_versions")
        ),
    )
