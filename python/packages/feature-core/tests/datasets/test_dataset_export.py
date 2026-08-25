from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from feature_core import (
    BatchRunMetadata,
    DatasetExporter,
    DatasetExportRequest,
    DatasetIntegrityError,
    DatasetManifest,
    DatasetPartitionRole,
    DatasetPartitionSpec,
    DatasetSourceSpec,
    DatasetValidationError,
    FeatureHistoryRecord,
    FeatureHistoryRepository,
    FeatureValueType,
    InMemoryFeatureHistoryBackend,
    MaterializedFeatureRow,
    RegistrySnapshotRef,
    SourceKind,
)
from feature_core.batch.models import canonical_checksum
from feature_core.storage.models import FeatureAsOfQuery, FeatureHistoryPage

BASE = datetime(2026, 1, 1, tzinfo=UTC)
FINGERPRINT = "sha256:" + "a" * 64
HEAD_FINGERPRINT = "sha256:" + "b" * 64
INPUT_CHECKSUM = "sha256:" + "c" * 64
CALCULATOR_FINGERPRINT = "sha256:" + "d" * 64
MANIFEST_CHECKSUM = "sha256:" + "e" * 64
OUTPUT_CHECKSUM = "sha256:" + "f" * 64


def _record(
    *,
    event_time: datetime,
    available_time: datetime,
    value: str,
    nonce: str,
    source_snapshot_version: str,
) -> FeatureHistoryRecord:
    ref = RegistrySnapshotRef(
        namespace_id="cn_equity",
        head_fingerprint=HEAD_FINGERPRINT,
        feature_name="close_return_1d",
        feature_version="1.0.0",
        feature_fingerprint=FINGERPRINT,
        algorithm_version="close-return-v1",
    )
    row = MaterializedFeatureRow(
        feature_name=ref.feature_name,
        feature_version=ref.feature_version,
        feature_fingerprint=ref.feature_fingerprint,
        algorithm_version=ref.algorithm_version,
        partition_key=event_time.date().isoformat(),
        entity_id="600519.SH",
        event_time=event_time,
        available_time=available_time,
        decision_time=available_time,
        value=value,
        input_row_ids=(f"bar-{nonce}",),
        input_lineage=(),
        input_checksum=INPUT_CHECKSUM,
        source_kind=SourceKind.CLICKHOUSE,
        source_snapshot_version=source_snapshot_version,
    )
    run = BatchRunMetadata(
        run_id=f"run-{nonce}",
        partition_key=row.partition_key,
        partition_start=event_time,
        partition_end=event_time + timedelta(days=1),
        registry_ref=ref,
        source_kind=row.source_kind,
        source_snapshot_version=row.source_snapshot_version,
        decision_time=row.decision_time,
        data_cutoff_time=available_time,
        calculator_implementation_fingerprint=CALCULATOR_FINGERPRINT,
        determinism_verified=True,
        input_manifest_checksum=MANIFEST_CHECKSUM,
        input_count=1,
        output_count=1,
        input_checksum=INPUT_CHECKSUM,
        output_checksum=OUTPUT_CHECKSUM,
    )
    return FeatureHistoryRecord.from_batch_materialization(
        row=row,
        run=run,
        processing_time=available_time + timedelta(seconds=1),
        value_type=FeatureValueType.DECIMAL,
        revision_nonce=nonce,
    )


def _source(
    start: datetime,
    end: datetime,
    *,
    as_of: datetime,
    feature_version: str = "1.0.0",
    feature_fingerprint: str = FINGERPRINT,
    max_rows: int = 100_000,
) -> DatasetSourceSpec:
    return DatasetSourceSpec(
        namespace_id="cn_equity",
        feature_name="close_return_1d",
        feature_version=feature_version,
        feature_fingerprint=feature_fingerprint,
        entity_ids=("600519.SH",),
        event_start=start,
        event_end=end,
        as_of=as_of,
        max_rows=max_rows,
    )


def _request() -> DatasetExportRequest:
    return DatasetExportRequest(
        dataset_name="factor-research",
        dataset_version="1.0.0",
        created_at=BASE + timedelta(days=90),
        partitions=(
            DatasetPartitionSpec(
                partition_id="train-2026-01",
                role=DatasetPartitionRole.TRAIN,
                sources=(
                    _source(BASE, BASE + timedelta(days=31), as_of=BASE + timedelta(days=90)),
                ),
            ),
            DatasetPartitionSpec(
                partition_id="evaluation-2026-02",
                role=DatasetPartitionRole.EVALUATION,
                sources=(
                    _source(
                        BASE + timedelta(days=31),
                        BASE + timedelta(days=60),
                        as_of=BASE + timedelta(days=90),
                    ),
                ),
            ),
        ),
        rebuild_command=(
            "uv",
            "run",
            "--package",
            "feature-core",
            "python",
            "research/datasets/rebuild.py",
            "--manifest",
            "dataset-manifest.json",
            "--output",
            "research/datasets/rebuilt",
            "--repository-profile",
            "feature-history",
        ),
    )


def _repository(*records: FeatureHistoryRecord) -> FeatureHistoryRepository:
    backend = InMemoryFeatureHistoryBackend()
    FeatureHistoryRepository(backend).append(tuple(records))
    return FeatureHistoryRepository(backend)


class _ConflictingRepository(FeatureHistoryRepository):
    def __init__(
        self,
        train_records: tuple[FeatureHistoryRecord, ...],
        evaluation_records: tuple[FeatureHistoryRecord, ...],
    ) -> None:
        self._train_records = train_records
        self._evaluation_records = evaluation_records

    def query_as_of(self, query: FeatureAsOfQuery) -> FeatureHistoryPage:
        records = (
            self._train_records
            if query.event_start < BASE + timedelta(days=31)
            else self._evaluation_records
        )
        return FeatureHistoryPage(
            records=records,
            truncated=False,
            query_checksum=canonical_checksum(query),
        )


@pytest.fixture
def records() -> tuple[FeatureHistoryRecord, FeatureHistoryRecord]:
    return (
        _record(
            event_time=BASE + timedelta(days=10),
            available_time=BASE + timedelta(days=10, minutes=5),
            value="0.01",
            nonce="train",
            source_snapshot_version="bars-train-v1",
        ),
        _record(
            event_time=BASE + timedelta(days=40),
            available_time=BASE + timedelta(days=40, minutes=5),
            value="0.02",
            nonce="evaluation",
            source_snapshot_version="bars-evaluation-v1",
        ),
    )


def test_export_writes_real_parquet_manifest_and_rebuild_command(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    exporter = DatasetExporter(_repository(*records))
    manifest = exporter.export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"

    persisted = DatasetManifest.from_json(
        (root / "dataset-manifest.json").read_text(encoding="utf-8")
    )
    command = json.loads((root / "rebuild-command.json").read_text(encoding="utf-8"))
    train = pq.read_table(root / "partitions/train/train-2026-01.parquet")
    evaluation = pq.read_table(root / "partitions/evaluation/evaluation-2026-02.parquet")

    assert persisted.manifest_checksum == manifest.manifest_checksum
    assert command["argv"] == list(manifest.rebuild_command)
    assert train.column("partition_role").to_pylist() == ["TRAIN"]
    assert evaluation.column("partition_role").to_pylist() == ["EVALUATION"]
    assert train.column("decision_time").to_pylist() == [BASE + timedelta(days=90)]
    assert evaluation.column("decision_time").to_pylist() == [BASE + timedelta(days=90)]
    assert train.column("value_json").to_pylist() == ['"0.01"']
    assert evaluation.column("value_json").to_pylist() == ['"0.02"']
    assert {artifact.row_count for artifact in manifest.partitions} == {1}


def test_rebuild_is_byte_identical_and_verifies_hashes(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    exporter = DatasetExporter(_repository(*records))
    manifest = exporter.export(_request(), tmp_path / "original")
    rebuilt = exporter.rebuild(manifest, tmp_path / "rebuilt")
    rebuilt_root = tmp_path / "rebuilt" / "factor-research" / "1.0.0"

    exporter.verify(rebuilt, rebuilt_root)

    assert rebuilt.manifest_checksum == manifest.manifest_checksum
    assert [artifact.file_checksum for artifact in rebuilt.partitions] == [
        artifact.file_checksum for artifact in manifest.partitions
    ]


def test_verify_rejects_tampered_parquet(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    exporter = DatasetExporter(_repository(*records))
    manifest = exporter.export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    partition = root / manifest.partitions[0].relative_path
    partition.write_bytes(partition.read_bytes() + b"tampered")

    with pytest.raises(DatasetIntegrityError):
        exporter.verify(manifest, root)


def test_rebuild_fails_and_cleans_output_when_source_drifted(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    manifest = DatasetExporter(_repository(*records)).export(_request(), tmp_path / "original")
    drifted = _record(
        event_time=records[0].event_time,
        available_time=records[0].available_time,
        value="0.99",
        nonce="drifted",
        source_snapshot_version="bars-train-v2",
    )
    exporter = DatasetExporter(_repository(drifted, records[1]))

    with pytest.raises(DatasetIntegrityError, match="manifest checksum"):
        exporter.rebuild(manifest, tmp_path / "rebuilt")

    assert not (tmp_path / "rebuilt" / "factor-research" / "1.0.0").exists()


def test_point_in_time_export_excludes_future_revision(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    event_time = BASE + timedelta(days=10)
    old = _record(
        event_time=event_time,
        available_time=event_time + timedelta(minutes=5),
        value="0.01",
        nonce="old",
        source_snapshot_version="bars-v1",
    )
    future = _record(
        event_time=event_time,
        available_time=BASE + timedelta(days=95),
        value="0.50",
        nonce="future",
        source_snapshot_version="bars-v2",
    )
    request = _request()
    exporter = DatasetExporter(_repository(old, future, records[1]))
    manifest = exporter.export(request, tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    train_artifact = next(
        artifact
        for artifact in manifest.partitions
        if artifact.partition.role is DatasetPartitionRole.TRAIN
    )
    table = pq.read_table(root / train_artifact.relative_path)

    assert table.column("value_json").to_pylist() == ['"0.01"']


def test_train_and_evaluation_sources_must_not_overlap() -> None:
    overlapping = _source(BASE, BASE + timedelta(days=40), as_of=BASE + timedelta(days=90))

    with pytest.raises(DatasetValidationError, match="same samples"):
        DatasetExportRequest(
            dataset_name="factor-research",
            dataset_version="1.0.0",
            created_at=BASE + timedelta(days=90),
            partitions=(
                DatasetPartitionSpec(
                    partition_id="train",
                    role=DatasetPartitionRole.TRAIN,
                    sources=(overlapping,),
                ),
                DatasetPartitionSpec(
                    partition_id="evaluation",
                    role=DatasetPartitionRole.EVALUATION,
                    sources=(overlapping,),
                ),
            ),
            rebuild_command=("uv", "run"),
        )


def test_train_and_evaluation_reject_same_samples_across_feature_versions() -> None:
    request = _request()
    evaluation = replace(
        request.partitions[0],
        partition_id="evaluation-overlap",
        role=DatasetPartitionRole.EVALUATION,
        sources=(
            _source(
                BASE,
                BASE + timedelta(days=31),
                as_of=BASE + timedelta(days=90),
                feature_version="2.0.0",
                feature_fingerprint="sha256:" + "9" * 64,
            ),
        ),
    )

    with pytest.raises(DatasetValidationError, match="same samples"):
        replace(request, partitions=(request.partitions[1], evaluation))


def test_manifest_checksum_detects_source_or_command_tampering(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    DatasetExporter(_repository(*records)).export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    data = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    data["rebuild_command"][11] = "tampered-profile"

    with pytest.raises(
        DatasetIntegrityError,
        match="build_spec_checksum|manifest checksum",
    ):
        DatasetManifest.from_json(json.dumps(data))


@pytest.mark.parametrize(
    "command",
    [
        ("python", "rebuild.py", "--dsn", "postgresql://user:pass@example"),
        (*_request().rebuild_command, "--api-key", "secret-value"),
    ],
)
def test_rebuild_command_allows_only_structured_contract(command: tuple[str, ...]) -> None:
    request = _request()

    with pytest.raises(DatasetValidationError, match="structured dataset rebuild contract"):
        replace(request, rebuild_command=command)


def test_rebuild_command_rejects_executable_repository_factory() -> None:
    request = _request()
    command = list(request.rebuild_command)
    command[11] = "os:abort"

    with pytest.raises(DatasetValidationError, match="repository profile"):
        replace(request, rebuild_command=tuple(command))


def test_manifest_rejects_unknown_unhashed_fields(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    DatasetExporter(_repository(*records)).export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    data = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    data["rogue"] = "not-covered-by-the-original-checksum"

    with pytest.raises(DatasetValidationError, match="manifest keys differ"):
        DatasetManifest.from_json(json.dumps(data))


def test_manifest_rejects_unknown_nested_fields(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    DatasetExporter(_repository(*records)).export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    data = json.loads((root / "dataset-manifest.json").read_text(encoding="utf-8"))
    data["partitions"][0]["partition"]["sources"][0]["rogue"] = "unhashed"

    with pytest.raises(DatasetValidationError, match="source keys differ"):
        DatasetManifest.from_json(json.dumps(data))


def test_manifest_rejects_duplicate_json_keys(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    DatasetExporter(_repository(*records)).export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    text = (root / "dataset-manifest.json").read_text(encoding="utf-8")
    duplicate = text.replace("{", '{"dataset_name":"rogue",', 1)

    with pytest.raises(DatasetValidationError, match="duplicate JSON key"):
        DatasetManifest.from_json(duplicate)


@pytest.mark.parametrize("mutation", ["tampered", "missing", "extra"])
def test_verify_rejects_command_or_artifact_tree_changes(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
    mutation: str,
) -> None:
    exporter = DatasetExporter(_repository(*records))
    manifest = exporter.export(_request(), tmp_path)
    root = tmp_path / "factor-research" / "1.0.0"
    command_path = root / "rebuild-command.json"
    if mutation == "tampered":
        command_path.write_text("tampered\n", encoding="utf-8")
    elif mutation == "missing":
        command_path.unlink()
    else:
        (root / "rogue.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="rebuild command|artifact tree"):
        exporter.verify(manifest, root)


def test_export_rejects_truncated_or_empty_partitions(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    second_train = _record(
        event_time=BASE + timedelta(days=11),
        available_time=BASE + timedelta(days=11, minutes=5),
        value="0.03",
        nonce="train-second",
        source_snapshot_version="bars-train-v1",
    )
    request = _request()
    train_partition = next(
        partition
        for partition in request.partitions
        if partition.role is DatasetPartitionRole.TRAIN
    )
    evaluation_partition = next(
        partition
        for partition in request.partitions
        if partition.role is DatasetPartitionRole.EVALUATION
    )
    limited_train = replace(
        train_partition,
        sources=(replace(train_partition.sources[0], max_rows=1),),
    )

    with pytest.raises(DatasetIntegrityError, match="truncated"):
        DatasetExporter(_repository(records[0], second_train, records[1])).export(
            replace(request, partitions=(limited_train, evaluation_partition)),
            tmp_path / "truncated",
        )
    with pytest.raises(DatasetIntegrityError, match="empty"):
        DatasetExporter(_repository(records[0])).export(request, tmp_path / "empty")

    assert not (tmp_path / "truncated" / "factor-research" / "1.0.0").exists()
    assert not (tmp_path / "empty" / "factor-research" / "1.0.0").exists()


def test_export_rejects_conflicting_revision_ids(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    conflicting = _record(
        event_time=records[0].event_time,
        available_time=records[0].available_time,
        value="0.99",
        nonce="conflict",
        source_snapshot_version="bars-train-v2",
    )
    object.__setattr__(conflicting, "revision_id", records[0].revision_id)
    repository = _ConflictingRepository(
        (records[0], conflicting),
        (records[1],),
    )

    with pytest.raises(DatasetIntegrityError, match="conflicting revision_id"):
        DatasetExporter(repository).export(_request(), tmp_path)


def test_export_revalidates_source_boundary_and_decision_cutoff(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    processed_after_cutoff = _record(
        event_time=BASE + timedelta(days=10),
        available_time=BASE + timedelta(days=90),
        value="0.04",
        nonce="processed-after-cutoff",
        source_snapshot_version="bars-late-processing-v1",
    )
    cases = (
        ("outside", records[1], "outside its boundary"),
        ("future-processing", processed_after_cutoff, "decision cutoff"),
    )

    for case, candidate, message in cases:
        repository = _ConflictingRepository((candidate,), (records[1],))
        with pytest.raises(DatasetIntegrityError, match=message):
            DatasetExporter(repository).export(_request(), tmp_path / case)


def test_verify_rejects_dataset_root_symlink(
    tmp_path: Path,
    records: tuple[FeatureHistoryRecord, FeatureHistoryRecord],
) -> None:
    exporter = DatasetExporter(_repository(*records))
    manifest = exporter.export(_request(), tmp_path / "original")
    root = tmp_path / "original" / "factor-research" / "1.0.0"
    link = tmp_path / "linked-dataset"
    try:
        link.symlink_to(root, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable on this platform")

    with pytest.raises(DatasetIntegrityError, match="root must not be a symlink"):
        exporter.verify(manifest, link)


def test_request_rejects_pre_as_of_creation_and_absolute_commands() -> None:
    request = _request()

    with pytest.raises(DatasetValidationError, match="created_at"):
        DatasetExportRequest(
            dataset_name=request.dataset_name,
            dataset_version=request.dataset_version,
            created_at=BASE + timedelta(days=89),
            partitions=request.partitions,
            rebuild_command=request.rebuild_command,
        )
    absolute_command = list(request.rebuild_command)
    absolute_command[9] = "/Users/example/rebuilt"
    with pytest.raises(DatasetValidationError, match="canonical relative path"):
        replace(request, rebuild_command=tuple(absolute_command))
