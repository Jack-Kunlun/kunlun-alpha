from __future__ import annotations

# PyArrow 25.0.1 has no PEP 561 stubs. Keep the exception inside this runtime
# adapter; domain models and exporter orchestration remain strict-typed.
# pyright: reportMissingTypeStubs=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from feature_core.batch.models import canonical_checksum
from feature_core.storage.models import FeatureHistoryRecord, canonical_json_text

from .models import (
    DATASET_MANIFEST_SCHEMA_VERSION,
    DatasetIntegrityError,
    DatasetPartitionSpec,
)

PARQUET_DATASET_SCHEMA_VERSION = "1.1.0"
PARQUET_WRITER_NAME = "pyarrow"
PARQUET_WRITER_VERSION = f"{pa.__version__}-kunlun-v2"

_PARQUET_SCHEMA = pa.schema(
    [
        pa.field("partition_id", pa.string(), nullable=False),
        pa.field("partition_role", pa.string(), nullable=False),
        pa.field("registry_namespace_id", pa.string(), nullable=False),
        pa.field("registry_head_fingerprint", pa.string(), nullable=False),
        pa.field("feature_name", pa.string(), nullable=False),
        pa.field("feature_version", pa.string(), nullable=False),
        pa.field("feature_fingerprint", pa.string(), nullable=False),
        pa.field("algorithm_version", pa.string(), nullable=False),
        pa.field("entity_id", pa.string(), nullable=False),
        pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("decision_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("available_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("processing_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("value_type", pa.string(), nullable=False),
        pa.field("value_json", pa.string(), nullable=False),
        pa.field("value_checksum", pa.string(), nullable=False),
        pa.field("materialization_id", pa.string(), nullable=False),
        pa.field("revision_nonce", pa.string(), nullable=False),
        pa.field("revision_id", pa.string(), nullable=False),
        pa.field("input_checksum", pa.string(), nullable=False),
        pa.field("calculator_implementation_fingerprint", pa.string(), nullable=False),
        pa.field("input_manifest_checksum", pa.string(), nullable=False),
        pa.field("lineage_checksum", pa.string(), nullable=False),
        pa.field("source_kind", pa.string(), nullable=False),
        pa.field("source_snapshot_version", pa.string(), nullable=False),
        pa.field("record_checksum", pa.string(), nullable=False),
    ]
)


def _schema_fingerprint(schema: pa.Schema) -> str:
    return canonical_checksum(
        {
            "schema_version": PARQUET_DATASET_SCHEMA_VERSION,
            "fields": tuple((field.name, str(field.type), field.nullable) for field in schema),
        }
    )


PARQUET_SCHEMA_FINGERPRINT = _schema_fingerprint(_PARQUET_SCHEMA)


@dataclass(frozen=True, slots=True)
class ParquetArtifact:
    row_count: int
    content_checksum: str
    file_checksum: str
    schema_fingerprint: str


def _file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _content_checksum(
    partition: DatasetPartitionSpec,
    sample_checksums: tuple[tuple[str, datetime], ...],
) -> str:
    return canonical_checksum(
        {
            "partition_id": partition.partition_id,
            "partition_role": partition.role,
            "sample_checksums": sample_checksums,
        }
    )


def _row(
    partition: DatasetPartitionSpec,
    record: FeatureHistoryRecord,
    decision_time: datetime,
) -> dict[str, object]:
    ref = record.registry_ref
    return {
        "partition_id": partition.partition_id,
        "partition_role": partition.role.value,
        "registry_namespace_id": ref.namespace_id,
        "registry_head_fingerprint": ref.head_fingerprint,
        "feature_name": ref.feature_name,
        "feature_version": ref.feature_version,
        "feature_fingerprint": ref.feature_fingerprint,
        "algorithm_version": ref.algorithm_version,
        "entity_id": record.entity_id,
        "event_time": record.event_time,
        "decision_time": decision_time,
        "available_time": record.available_time,
        "processing_time": record.processing_time,
        "value_type": record.value_type.value,
        "value_json": canonical_json_text(record.value),
        "value_checksum": record.value_checksum,
        "materialization_id": record.materialization_id,
        "revision_nonce": record.revision_nonce,
        "revision_id": record.revision_id,
        "input_checksum": record.input_checksum,
        "calculator_implementation_fingerprint": record.calculator_implementation_fingerprint,
        "input_manifest_checksum": record.input_manifest_checksum,
        "lineage_checksum": record.lineage_checksum,
        "source_kind": record.source_kind,
        "source_snapshot_version": record.source_snapshot_version,
        "record_checksum": record.record_checksum,
    }


class PyArrowParquetCodec:
    def write(
        self,
        path: Path,
        partition: DatasetPartitionSpec,
        records: tuple[FeatureHistoryRecord, ...],
        decision_times: Mapping[str, datetime],
    ) -> ParquetArtifact:
        if not records:
            raise DatasetIntegrityError("cannot write an empty dataset partition")
        revision_ids = tuple(record.revision_id for record in records)
        if len(revision_ids) != len(set(revision_ids)) or set(decision_times) != set(revision_ids):
            raise DatasetIntegrityError("dataset decision cutoffs do not match its records")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        metadata = {
            b"kunlun.dataset_manifest_schema_version": DATASET_MANIFEST_SCHEMA_VERSION.encode(),
            b"kunlun.parquet_schema_version": PARQUET_DATASET_SCHEMA_VERSION.encode(),
            b"kunlun.partition_id": partition.partition_id.encode(),
            b"kunlun.partition_role": partition.role.value.encode(),
            b"kunlun.schema_fingerprint": PARQUET_SCHEMA_FINGERPRINT.encode(),
        }
        table = pa.Table.from_pylist(
            [_row(partition, record, decision_times[record.revision_id]) for record in records],
            schema=_PARQUET_SCHEMA,
        ).replace_schema_metadata(metadata)
        try:
            pq.write_table(
                table,
                temporary,
                compression="zstd",
                compression_level=9,
                use_dictionary=True,
                write_statistics=True,
                version="2.6",
                data_page_version="2.0",
                coerce_timestamps="us",
                allow_truncated_timestamps=False,
                row_group_size=65_536,
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        checksums = tuple(
            (record.record_checksum, decision_times[record.revision_id]) for record in records
        )
        return ParquetArtifact(
            row_count=len(records),
            content_checksum=_content_checksum(partition, checksums),
            file_checksum=_file_checksum(path),
            schema_fingerprint=PARQUET_SCHEMA_FINGERPRINT,
        )

    def inspect(
        self,
        path: Path,
        partition: DatasetPartitionSpec,
    ) -> ParquetArtifact:
        try:
            table = pq.read_table(path)
        except Exception as exc:
            raise DatasetIntegrityError(f"cannot read Parquet artifact {path.name}") from exc
        schema = table.schema
        metadata = schema.metadata or {}
        expected_metadata = {
            b"kunlun.partition_id": partition.partition_id.encode(),
            b"kunlun.partition_role": partition.role.value.encode(),
            b"kunlun.schema_fingerprint": PARQUET_SCHEMA_FINGERPRINT.encode(),
        }
        for key, expected in expected_metadata.items():
            if metadata.get(key) != expected:
                raise DatasetIntegrityError(
                    f"Parquet metadata {key.decode()} does not match the manifest"
                )
        if _schema_fingerprint(schema.remove_metadata()) != PARQUET_SCHEMA_FINGERPRINT:
            raise DatasetIntegrityError("Parquet schema fingerprint is invalid")
        rows = cast(
            list[dict[str, object]],
            table.select(
                [
                    "partition_id",
                    "partition_role",
                    "record_checksum",
                    "decision_time",
                ]
            ).to_pylist(),
        )
        checksums: list[tuple[str, datetime]] = []
        for row in rows:
            if (
                row.get("partition_id") != partition.partition_id
                or row.get("partition_role") != partition.role.value
            ):
                raise DatasetIntegrityError(
                    "Parquet row partition identity does not match the manifest"
                )
            checksum = row.get("record_checksum")
            if type(checksum) is not str:
                raise DatasetIntegrityError("Parquet row record_checksum is invalid")
            decision_time = row.get("decision_time")
            if type(decision_time) is not datetime or decision_time.tzinfo is None:
                raise DatasetIntegrityError("Parquet row decision_time is invalid")
            checksums.append((checksum, decision_time))
        return ParquetArtifact(
            row_count=len(rows),
            content_checksum=_content_checksum(partition, tuple(checksums)),
            file_checksum=_file_checksum(path),
            schema_fingerprint=PARQUET_SCHEMA_FINGERPRINT,
        )
