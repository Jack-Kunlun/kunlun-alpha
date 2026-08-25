from __future__ import annotations

import json
import os
import shlex
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from feature_core.batch.models import canonical_checksum
from feature_core.storage.models import FeatureHistoryPage, FeatureHistoryRecord
from feature_core.storage.repository import FeatureHistoryRepository

from .models import (
    DatasetConflictError,
    DatasetExportRequest,
    DatasetIntegrityError,
    DatasetManifest,
    DatasetPartitionArtifact,
    DatasetPartitionSpec,
    DatasetSourceSpec,
)
from .parquet import (
    PARQUET_WRITER_NAME,
    PARQUET_WRITER_VERSION,
    ParquetArtifact,
    PyArrowParquetCodec,
)

DATASET_MANIFEST_FILENAME = "dataset-manifest.json"
DATASET_REBUILD_COMMAND_FILENAME = "rebuild-command.json"


def _record_order(record: FeatureHistoryRecord) -> tuple[object, ...]:
    ref = record.registry_ref
    return (
        ref.namespace_id,
        ref.feature_name,
        ref.feature_version,
        ref.feature_fingerprint,
        record.entity_id,
        record.event_time,
        record.available_time,
        record.processing_time,
        record.revision_id,
    )


def _partition_path(partition: DatasetPartitionSpec) -> str:
    return f"partitions/{partition.role.value.lower()}/{partition.partition_id}.parquet"


def _validate_source_record(
    source: DatasetSourceSpec,
    candidate: object,
) -> FeatureHistoryRecord:
    if type(candidate) is not FeatureHistoryRecord:
        raise DatasetIntegrityError("dataset source returned an invalid record type")
    record = candidate
    ref = record.registry_ref
    if (
        (
            ref.namespace_id,
            ref.feature_name,
            ref.feature_version,
            ref.feature_fingerprint,
        )
        != source.identity
        or record.entity_id not in source.entity_ids
        or not source.event_start <= record.event_time < source.event_end
    ):
        raise DatasetIntegrityError("dataset source returned a record outside its boundary")
    if (
        record.available_time > source.decision_time
        or record.processing_time > source.decision_time
    ):
        raise DatasetIntegrityError("dataset source returned a record after its decision cutoff")
    try:
        record.__post_init__()
    except (TypeError, ValueError) as exc:
        raise DatasetIntegrityError("dataset source returned an invalid historical record") from exc
    return record


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _rebuild_command_text(command: tuple[str, ...]) -> str:
    return (
        json.dumps(
            {
                "argv": list(command),
                "display": shlex.join(command),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


class DatasetExporter:
    def __init__(
        self,
        repository: FeatureHistoryRepository,
        codec: PyArrowParquetCodec | None = None,
    ) -> None:
        self._repository = repository
        self._codec = codec or PyArrowParquetCodec()

    def export(
        self,
        request: DatasetExportRequest,
        output_root: Path,
    ) -> DatasetManifest:
        root = Path(output_root)
        target = root / request.dataset_name / request.dataset_version
        if target.exists():
            raise DatasetConflictError(f"dataset target already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        stage.mkdir()
        try:
            artifacts = tuple(
                self._export_partition(partition, stage) for partition in request.partitions
            )
            manifest = DatasetManifest(
                dataset_name=request.dataset_name,
                dataset_version=request.dataset_version,
                created_at=request.created_at,
                partitions=artifacts,
                rebuild_command=request.rebuild_command,
                build_spec_checksum=request.build_spec_checksum,
                writer_name=PARQUET_WRITER_NAME,
                writer_version=PARQUET_WRITER_VERSION,
            )
            _write_text(stage / DATASET_MANIFEST_FILENAME, manifest.to_json())
            _write_text(
                stage / DATASET_REBUILD_COMMAND_FILENAME,
                _rebuild_command_text(request.rebuild_command),
            )
            os.replace(stage, target)
            return manifest
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def rebuild(
        self,
        manifest: DatasetManifest,
        output_root: Path,
    ) -> DatasetManifest:
        target = Path(output_root) / manifest.dataset_name / manifest.dataset_version
        generated = self.export(manifest.request, output_root)
        try:
            if generated.manifest_checksum != manifest.manifest_checksum:
                raise DatasetIntegrityError(
                    "rebuilt dataset does not match the expected manifest checksum"
                )
            self.verify(generated, target)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return generated

    def verify(
        self,
        manifest: DatasetManifest,
        dataset_root: Path,
    ) -> None:
        root = Path(dataset_root)
        if root.is_symlink():
            raise DatasetIntegrityError("dataset root must not be a symlink")
        manifest_path = root / DATASET_MANIFEST_FILENAME
        try:
            persisted = DatasetManifest.from_json(manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DatasetIntegrityError("dataset manifest file is unavailable") from exc
        if persisted != manifest:
            raise DatasetIntegrityError("persisted dataset manifest does not match")

        command_path = root / DATASET_REBUILD_COMMAND_FILENAME
        try:
            command_text = command_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DatasetIntegrityError("dataset rebuild command file is unavailable") from exc
        if command_text != _rebuild_command_text(manifest.rebuild_command):
            raise DatasetIntegrityError("persisted dataset rebuild command does not match")

        expected_files = {
            DATASET_MANIFEST_FILENAME,
            DATASET_REBUILD_COMMAND_FILENAME,
            *(artifact.relative_path for artifact in manifest.partitions),
        }
        expected_entries = set(expected_files)
        for relative_path in expected_files:
            expected_entries.update(
                parent.as_posix()
                for parent in PurePosixPath(relative_path).parents
                if parent.as_posix() != "."
            )
        actual_entries: set[str] = set()
        for path in root.rglob("*"):
            if path.is_symlink():
                raise DatasetIntegrityError("dataset artifact tree contains a symlink")
            actual_entries.add(path.relative_to(root).as_posix())
        if actual_entries != expected_entries:
            raise DatasetIntegrityError("dataset artifact tree does not match the manifest")

        for expected in manifest.partitions:
            actual = self._codec.inspect(root / expected.relative_path, expected.partition)
            self._verify_artifact(expected, actual)

    def _export_partition(
        self,
        partition: DatasetPartitionSpec,
        stage: Path,
    ) -> DatasetPartitionArtifact:
        revisions: dict[str, tuple[FeatureHistoryRecord, datetime]] = {}
        for source in partition.sources:
            query = source.to_query()
            page = self._repository.query_as_of(query)
            if type(page) is not FeatureHistoryPage:
                raise DatasetIntegrityError("dataset source returned an invalid page type")
            if page.query_checksum != canonical_checksum(query):
                raise DatasetIntegrityError("dataset source query checksum does not match")
            if page.truncated:
                raise DatasetIntegrityError(
                    f"source query truncated partition {partition.partition_id}"
                )
            for candidate in page.records:
                if type(candidate) is not FeatureHistoryRecord:
                    raise DatasetIntegrityError("dataset source returned an invalid record type")
                prior = revisions.get(candidate.revision_id)
                if prior is not None and prior[0] != candidate:
                    raise DatasetIntegrityError("dataset source returned a conflicting revision_id")
                record = _validate_source_record(source, candidate)
                if prior is not None and prior[1] != source.decision_time:
                    raise DatasetIntegrityError(
                        "dataset source returned one revision with conflicting decision cutoffs"
                    )
                revisions[record.revision_id] = (record, source.decision_time)
        samples = tuple(sorted(revisions.values(), key=lambda item: _record_order(item[0])))
        records = tuple(record for record, _ in samples)
        if not records:
            raise DatasetIntegrityError(f"dataset partition {partition.partition_id} is empty")
        relative_path = _partition_path(partition)
        artifact = self._codec.write(
            stage / relative_path,
            partition,
            records,
            {record.revision_id: decision_time for record, decision_time in samples},
        )
        return DatasetPartitionArtifact(
            partition=partition,
            relative_path=relative_path,
            row_count=artifact.row_count,
            content_checksum=artifact.content_checksum,
            file_checksum=artifact.file_checksum,
            schema_fingerprint=artifact.schema_fingerprint,
            source_lineage_checksums=tuple(record.lineage_checksum for record in records),
            source_snapshot_versions=tuple(record.source_snapshot_version for record in records),
        )

    @staticmethod
    def _verify_artifact(
        expected: DatasetPartitionArtifact,
        actual: ParquetArtifact,
    ) -> None:
        if (
            expected.row_count != actual.row_count
            or expected.content_checksum != actual.content_checksum
            or expected.file_checksum != actual.file_checksum
            or expected.schema_fingerprint != actual.schema_fingerprint
        ):
            raise DatasetIntegrityError(
                f"dataset partition {expected.partition.partition_id} failed hash verification"
            )
