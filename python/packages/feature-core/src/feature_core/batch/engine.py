from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from feature_core.registry import AvailabilityPolicy, FeatureSpec, FeatureValueType

from .models import (
    BatchCheckpoint,
    BatchConflictError,
    BatchExecution,
    BatchInputBatch,
    BatchInputReference,
    BatchInputRow,
    BatchIntegrityError,
    BatchPartition,
    BatchPartitionResult,
    BatchRunMetadata,
    BatchValidationError,
    CalculatedFeature,
    CalculatorIdentity,
    CommitResult,
    CommitStatus,
    CompletenessStatus,
    ExecutionDisposition,
    FutureDataLeakageError,
    InputOrigin,
    JsonValue,
    MaterializedFeatureRow,
    PartitionReadRequest,
    RegisteredFeature,
    RegistrySnapshotRef,
    canonical_checksum,
    canonical_decimal_string,
    freeze_json_value,
    rows_checksum,
)
from .ports import (
    BatchCalculator,
    BatchCheckpointStore,
    BatchPartitionSource,
    FeatureDependencyResolver,
    FeaturePartitionStore,
)


def _required_references(
    spec: FeatureSpec,
) -> tuple[tuple[BatchInputReference, ...], tuple[BatchInputReference, ...]]:
    sources = tuple(
        sorted(
            BatchInputReference(InputOrigin.SOURCE_CONTRACT, item.name, item.version)
            for item in spec.source_contracts
        ),
    )
    dependencies = tuple(
        sorted(
            BatchInputReference(InputOrigin.FEATURE_DEPENDENCY, item.name, item.version)
            for item in spec.dependencies
        ),
    )
    return sources, dependencies


def _calculator_identity(calculator: BatchCalculator, spec: FeatureSpec) -> CalculatorIdentity:
    declared = getattr(calculator, "identity", None)
    if type(declared) is not CalculatorIdentity:
        raise BatchValidationError(
            "calculator must declare a stable CalculatorIdentity artifact digest"
        )
    identity = declared
    if identity.algorithm_version != spec.algorithm_version:
        raise BatchValidationError("calculator algorithm_version does not match FeatureSpec")
    return identity


def _validate_batch(
    batch: BatchInputBatch,
    request: PartitionReadRequest,
    feature: RegisteredFeature,
    dependency_resolver: FeatureDependencyResolver | None,
) -> tuple[BatchInputRow, ...]:
    required = {
        *request.required_source_contracts,
        *request.required_feature_dependencies,
    }
    rows = tuple(
        sorted(
            batch.rows,
            key=lambda row: (row.event_time, row.available_time, row.row_id),
        ),
    )
    row_ids: set[str] = set()
    grouped: dict[BatchInputReference, list[BatchInputRow]] = {}
    for row in rows:
        if row.row_id in row_ids:
            raise BatchIntegrityError(f"duplicate input row_id: {row.row_id}")
        row_ids.add(row.row_id)
        if not request.partition.start <= row.event_time < request.partition.end:
            raise FutureDataLeakageError("source returned an input outside the requested partition")
        if row.available_time > request.partition.decision_time:
            raise FutureDataLeakageError("source returned input unavailable at decision_time")
        reference = row.lineage.reference
        if type(cast(object, reference.origin)) is not InputOrigin:
            raise BatchIntegrityError("input origin is not an exact InputOrigin")
        if reference not in required:
            raise BatchValidationError(
                "source returned an undeclared contract or feature dependency"
            )
        if reference.origin is InputOrigin.FEATURE_DEPENDENCY:
            if dependency_resolver is None:
                raise BatchIntegrityError(
                    "feature dependency requires a trusted provenance resolver"
                )
            dependency = feature.registry.get(reference.name)
            if dependency.version != reference.version:
                raise BatchIntegrityError("upstream feature version does not match registry")
            if row.lineage.upstream_feature_fingerprint != dependency.semantic_fingerprint:
                raise BatchIntegrityError("upstream feature fingerprint does not match registry")
            upstream_run_id = row.lineage.upstream_run_id
            if upstream_run_id is None:
                raise BatchIntegrityError("feature dependency is missing upstream run_id")
            upstream = dependency_resolver.resolve(upstream_run_id)
            if type(upstream) is not BatchPartitionResult:
                raise BatchIntegrityError("feature dependency provenance could not be resolved")
            if (
                upstream.metadata.run_id != upstream_run_id
                or upstream.metadata.feature_name != dependency.name
                or upstream.metadata.feature_version != dependency.version
                or upstream.metadata.feature_fingerprint != dependency.semantic_fingerprint
                or upstream.metadata.output_checksum != canonical_checksum(upstream.rows)
                or upstream.metadata.output_checksum != row.lineage.upstream_output_checksum
                or upstream.checkpoint.result_checksum != upstream.result_checksum
            ):
                raise BatchIntegrityError(
                    "feature dependency provenance does not match the upstream result"
                )
        grouped.setdefault(reference, []).append(row)

    entries = {entry.reference: entry for entry in batch.manifest.entries}
    if set(entries) != required:
        raise BatchIntegrityError("input completeness manifest mismatch")
    for reference in required:
        entry = entries[reference]
        group = tuple(grouped.get(reference, ()))
        expected_status = (
            CompletenessStatus.COMPLETE if group else CompletenessStatus.COMPLETE_EMPTY
        )
        if entry.status is not expected_status:
            raise BatchIntegrityError("manifest completeness status does not match returned rows")
        if entry.row_count != len(group) or entry.rows_checksum != rows_checksum(group):
            raise BatchIntegrityError("manifest row count or checksum does not match returned rows")
    return rows


def _input_checksum(batch: BatchInputBatch, rows: tuple[BatchInputRow, ...]) -> str:
    return canonical_checksum(
        {
            "source_kind": batch.source_kind,
            "snapshot_version": batch.snapshot_version,
            "manifest": batch.manifest,
            "rows": rows,
        },
    )


def _run_id(
    registry_ref: RegistrySnapshotRef,
    partition: BatchPartition,
    batch: BatchInputBatch,
    input_checksum: str,
    calculator_identity: CalculatorIdentity,
) -> str:
    return canonical_checksum(
        {
            "registry_ref": registry_ref,
            "partition": partition,
            "source_kind": batch.source_kind,
            "source_snapshot_version": batch.snapshot_version,
            "input_manifest_checksum": canonical_checksum(batch.manifest),
            "input_checksum": input_checksum,
            "calculator_identity": calculator_identity,
            "determinism_verified": True,
        },
    )


def _normalize_feature_value(spec: FeatureSpec, value: object) -> JsonValue:
    kind = spec.value_type.name
    if kind == FeatureValueType.DECIMAL.name:
        if type(value) is float:
            raise BatchValidationError("float values are not valid DECIMAL feature values")
        return canonical_decimal_string(value)
    if kind in {"INTEGER", "INT"}:
        if type(value) is not int:
            raise BatchValidationError("INTEGER feature value must be an integer")
        return value
    if kind in {"BOOLEAN", "BOOL"}:
        if type(value) is not bool:
            raise BatchValidationError("BOOLEAN feature value must be a boolean")
        return value
    if kind in {"STRING", "TEXT"}:
        if type(value) is not str:
            raise BatchValidationError("STRING feature value must be a string")
        return value
    return freeze_json_value(value)


def _materialize_rows(
    spec: FeatureSpec,
    partition: BatchPartition,
    batch: BatchInputBatch,
    inputs: tuple[BatchInputRow, ...],
    calculated: Iterable[CalculatedFeature],
) -> tuple[MaterializedFeatureRow, ...]:
    input_by_id = {row.row_id: row for row in inputs}
    materialized: list[MaterializedFeatureRow] = []
    identities: set[tuple[str, object]] = set()
    for item in calculated:
        identity = (item.entity_id, item.event_time)
        if identity in identities:
            raise BatchIntegrityError("calculator returned a duplicate output identity")
        identities.add(identity)
        input_ids = tuple(sorted(item.input_row_ids))
        if not input_ids or len(input_ids) != len(set(input_ids)):
            raise BatchIntegrityError("calculated feature must reference unique current inputs")
        try:
            referenced = tuple(input_by_id[row_id] for row_id in input_ids)
        except KeyError as error:
            raise BatchIntegrityError("calculator referenced an unknown input row") from error
        if item.event_time < max(row.event_time for row in referenced):
            raise FutureDataLeakageError("output event_time precedes a referenced input event")
        if not partition.start <= item.event_time < partition.end:
            raise FutureDataLeakageError("feature event_time is outside the requested partition")
        if spec.availability_policy is AvailabilityPolicy.MATERIALIZATION_TIME:
            raise BatchValidationError("MATERIALIZATION_TIME is nondeterministic in batch mode")
        if spec.availability_policy is AvailabilityPolicy.SOURCE_AVAILABLE_TIME:
            if len(referenced) != 1:
                raise BatchValidationError(
                    "SOURCE_AVAILABLE_TIME requires exactly one referenced input",
                )
            available_time = referenced[0].available_time
        else:
            available_time = max(row.available_time for row in referenced)
        if available_time > partition.decision_time:
            raise FutureDataLeakageError("materialized feature is unavailable at decision_time")
        materialized.append(
            MaterializedFeatureRow(
                feature_name=spec.name,
                feature_version=spec.version,
                feature_fingerprint=spec.semantic_fingerprint,
                algorithm_version=spec.algorithm_version,
                partition_key=partition.key,
                entity_id=item.entity_id,
                event_time=item.event_time,
                available_time=available_time,
                decision_time=partition.decision_time,
                value=_normalize_feature_value(spec, item.value),
                input_row_ids=input_ids,
                input_lineage=tuple(row.lineage for row in referenced),
                input_checksum=rows_checksum(referenced),
                source_kind=batch.source_kind,
                source_snapshot_version=batch.snapshot_version,
            ),
        )
    return tuple(
        sorted(
            materialized,
            key=lambda row: (row.event_time, row.entity_id, row.input_row_ids),
        ),
    )


def _calculate_deterministically(
    calculator: BatchCalculator,
    spec: FeatureSpec,
    partition: BatchPartition,
    batch: BatchInputBatch,
    inputs: tuple[BatchInputRow, ...],
) -> tuple[MaterializedFeatureRow, ...]:
    first = _materialize_rows(spec, partition, batch, inputs, calculator(spec, partition, inputs))
    second = _materialize_rows(spec, partition, batch, inputs, calculator(spec, partition, inputs))
    if canonical_checksum(first) != canonical_checksum(second):
        raise BatchIntegrityError("calculator is non-deterministic for identical input")
    return first


def _build_candidate(
    *,
    run_id: str,
    feature: RegisteredFeature,
    partition: BatchPartition,
    batch: BatchInputBatch,
    inputs: tuple[BatchInputRow, ...],
    input_checksum: str,
    calculator: BatchCalculator,
    calculator_identity: CalculatorIdentity,
) -> BatchPartitionResult:
    rows = _calculate_deterministically(
        calculator,
        feature.spec,
        partition,
        batch,
        inputs,
    )
    metadata = BatchRunMetadata(
        run_id=run_id,
        partition_key=partition.key,
        partition_start=partition.start,
        partition_end=partition.end,
        registry_ref=feature.snapshot_ref,
        source_kind=batch.source_kind,
        source_snapshot_version=batch.snapshot_version,
        decision_time=partition.decision_time,
        data_cutoff_time=max((row.available_time for row in inputs), default=None),
        calculator_implementation_fingerprint=(calculator_identity.implementation_fingerprint),
        determinism_verified=True,
        input_manifest_checksum=canonical_checksum(batch.manifest),
        input_count=len(inputs),
        output_count=len(rows),
        input_checksum=input_checksum,
        output_checksum=canonical_checksum(rows),
    )
    return BatchPartitionResult(
        metadata=metadata,
        rows=rows,
        input_manifest=batch.manifest,
    )


def _require_input_batch(value: object) -> BatchInputBatch:
    if type(value) is not BatchInputBatch:
        raise BatchIntegrityError("partition source returned an invalid input batch")
    return value


def _revalidate_persisted_result(
    result: object,
    *,
    expected_run_id: str,
    feature: RegisteredFeature,
    partition: BatchPartition,
    batch: BatchInputBatch,
    inputs: tuple[BatchInputRow, ...],
    input_checksum: str,
    calculator_identity: CalculatorIdentity,
) -> BatchPartitionResult:
    if type(result) is not BatchPartitionResult:
        raise BatchIntegrityError("output store returned an invalid result")
    if (
        type(cast(object, result.metadata)) is not BatchRunMetadata
        or type(cast(object, result.input_manifest)) is not type(batch.manifest)
        or any(type(cast(object, row)) is not MaterializedFeatureRow for row in result.rows)
    ):
        raise BatchIntegrityError("persisted output contains an invalid entity type")
    metadata = result.metadata
    expected = {
        "run_id": expected_run_id,
        "partition_key": partition.key,
        "partition_start": partition.start,
        "partition_end": partition.end,
        "registry_ref": feature.snapshot_ref,
        "source_kind": batch.source_kind,
        "source_snapshot_version": batch.snapshot_version,
        "decision_time": partition.decision_time,
        "data_cutoff_time": max((row.available_time for row in inputs), default=None),
        "calculator_implementation_fingerprint": calculator_identity.implementation_fingerprint,
        "determinism_verified": True,
        "input_manifest_checksum": canonical_checksum(batch.manifest),
        "input_count": len(inputs),
        "input_checksum": input_checksum,
    }
    for field, value in expected.items():
        if getattr(metadata, field) != value:
            raise BatchIntegrityError(f"persisted result metadata mismatch: {field}")
    if result.input_manifest != batch.manifest:
        raise BatchIntegrityError("persisted result manifest differs from current input manifest")
    if metadata.output_count != len(result.rows):
        raise BatchIntegrityError("persisted result output_count is invalid")
    if metadata.output_checksum != canonical_checksum(result.rows):
        raise BatchIntegrityError("persisted output checksum does not match persisted rows")

    input_by_id = {row.row_id: row for row in inputs}
    identities: set[tuple[str, object]] = set()
    for row in result.rows:
        identity = (row.entity_id, row.event_time)
        if identity in identities:
            raise BatchIntegrityError("persisted output contains duplicate feature identities")
        identities.add(identity)
        if (
            row.feature_name != feature.spec.name
            or row.feature_version != feature.spec.version
            or row.feature_fingerprint != feature.spec.semantic_fingerprint
            or row.algorithm_version != feature.spec.algorithm_version
            or row.partition_key != partition.key
            or row.decision_time != partition.decision_time
            or row.source_kind is not batch.source_kind
            or row.source_snapshot_version != batch.snapshot_version
        ):
            raise BatchIntegrityError("persisted feature row context is invalid")
        if not partition.start <= row.event_time < partition.end:
            raise BatchIntegrityError("persisted feature row is outside the partition")
        try:
            normalized_value = _normalize_feature_value(feature.spec, row.value)
        except BatchValidationError as error:
            raise BatchIntegrityError("persisted feature row value is not canonical") from error
        if normalized_value != row.value:
            raise BatchIntegrityError("persisted feature row value is not canonical")
        try:
            referenced = tuple(input_by_id[row_id] for row_id in row.input_row_ids)
        except KeyError as error:
            raise BatchIntegrityError("persisted row references an unknown input") from error
        if not referenced:
            raise BatchIntegrityError("persisted row must reference current inputs")
        if tuple(item.lineage for item in referenced) != row.input_lineage:
            raise BatchIntegrityError("persisted row lineage does not match current inputs")
        if row.input_checksum != rows_checksum(referenced):
            raise BatchIntegrityError("persisted row input checksum is invalid")
        expected_available = (
            referenced[0].available_time
            if feature.spec.availability_policy is AvailabilityPolicy.SOURCE_AVAILABLE_TIME
            else max(item.available_time for item in referenced)
        )
        if row.available_time != expected_available or row.available_time > partition.decision_time:
            raise BatchIntegrityError("persisted row availability is invalid")
    return result


def _revalidate_checkpoint(
    checkpoint: object,
    result: BatchPartitionResult,
) -> None:
    if type(checkpoint) is not BatchCheckpoint or checkpoint != result.checkpoint:
        raise BatchIntegrityError("checkpoint does not match the revalidated output result")


def _require_commit_result(value: object, entity: str) -> CommitResult[object]:
    if type(value) is not CommitResult:
        raise BatchIntegrityError(f"{entity} store returned an invalid commit result")
    result = cast(CommitResult[object], value)
    if type(cast(object, result.status)) is not CommitStatus:
        raise BatchIntegrityError(f"{entity} store returned an invalid commit status")
    if result.status not in (
        CommitStatus.CREATED,
        CommitStatus.EXISTING_SAME,
        CommitStatus.CONFLICT,
    ):
        raise BatchIntegrityError(f"{entity} store returned an unknown commit status")
    return result


class BatchFeatureEngine:
    def __init__(
        self,
        *,
        source: BatchPartitionSource,
        output_store: FeaturePartitionStore,
        checkpoint_store: BatchCheckpointStore,
        dependency_resolver: FeatureDependencyResolver | None = None,
    ) -> None:
        self._source = source
        self._output_store = output_store
        self._checkpoint_store = checkpoint_store
        self._dependency_resolver = dependency_resolver

    def run(
        self,
        feature: object,
        partition: BatchPartition,
        calculator: BatchCalculator,
    ) -> BatchExecution:
        if type(feature) is not RegisteredFeature:
            raise BatchValidationError("batch execution requires a trusted RegisteredFeature")
        spec = feature.spec
        sources, dependencies = _required_references(spec)
        request = PartitionReadRequest(
            registry_ref=feature.snapshot_ref,
            partition=partition,
            required_source_contracts=sources,
            required_feature_dependencies=dependencies,
        )
        batch = _require_input_batch(self._source.read_partition(request))
        inputs = _validate_batch(
            batch,
            request,
            feature,
            self._dependency_resolver,
        )
        input_checksum = _input_checksum(batch, inputs)
        calculator_identity = _calculator_identity(calculator, spec)
        run_id = _run_id(
            feature.snapshot_ref,
            partition,
            batch,
            input_checksum,
            calculator_identity,
        )

        checkpoint = self._checkpoint_store.get(run_id)
        if checkpoint is not None:
            persisted = self._output_store.get(run_id)
            if persisted is None:
                raise BatchIntegrityError("checkpoint exists without a persisted output")
            persisted = _revalidate_persisted_result(
                persisted,
                expected_run_id=run_id,
                feature=feature,
                partition=partition,
                batch=batch,
                inputs=inputs,
                input_checksum=input_checksum,
                calculator_identity=calculator_identity,
            )
            _revalidate_checkpoint(checkpoint, persisted)
            expected = _build_candidate(
                run_id=run_id,
                feature=feature,
                partition=partition,
                batch=batch,
                inputs=inputs,
                input_checksum=input_checksum,
                calculator=calculator,
                calculator_identity=calculator_identity,
            )
            if persisted != expected or persisted.result_checksum != expected.result_checksum:
                raise BatchIntegrityError(
                    "persisted replay output differs from current deterministic calculation"
                )
            return BatchExecution(ExecutionDisposition.REPLAYED, persisted)

        candidate = _build_candidate(
            run_id=run_id,
            feature=feature,
            partition=partition,
            batch=batch,
            inputs=inputs,
            input_checksum=input_checksum,
            calculator=calculator,
            calculator_identity=calculator_identity,
        )
        _revalidate_persisted_result(
            candidate,
            expected_run_id=run_id,
            feature=feature,
            partition=partition,
            batch=batch,
            inputs=inputs,
            input_checksum=input_checksum,
            calculator_identity=calculator_identity,
        )

        output_commit = _require_commit_result(self._output_store.commit(candidate), "output")
        if output_commit.status is CommitStatus.CONFLICT:
            raise BatchConflictError("run_id identifies conflicting persisted output")
        declared_output = _revalidate_persisted_result(
            output_commit.persisted,
            expected_run_id=run_id,
            feature=feature,
            partition=partition,
            batch=batch,
            inputs=inputs,
            input_checksum=input_checksum,
            calculator_identity=calculator_identity,
        )
        read_back_output = self._output_store.get(run_id)
        persisted = _revalidate_persisted_result(
            read_back_output,
            expected_run_id=run_id,
            feature=feature,
            partition=partition,
            batch=batch,
            inputs=inputs,
            input_checksum=input_checksum,
            calculator_identity=calculator_identity,
        )
        if (
            declared_output != persisted
            or persisted != candidate
            or persisted.result_checksum != candidate.result_checksum
        ):
            raise BatchConflictError("persisted output differs from the calculated candidate")

        checkpoint_commit = _require_commit_result(
            self._checkpoint_store.commit(persisted.checkpoint),
            "checkpoint",
        )
        if checkpoint_commit.status is CommitStatus.CONFLICT:
            raise BatchConflictError("run_id identifies a conflicting checkpoint")
        _revalidate_checkpoint(checkpoint_commit.persisted, persisted)
        read_back_checkpoint = self._checkpoint_store.get(run_id)
        _revalidate_checkpoint(read_back_checkpoint, persisted)
        if checkpoint_commit.persisted != read_back_checkpoint:
            raise BatchIntegrityError("checkpoint commit result differs from durable read-back")

        disposition = (
            ExecutionDisposition.COMMITTED
            if output_commit.status is CommitStatus.CREATED
            and checkpoint_commit.status is CommitStatus.CREATED
            else ExecutionDisposition.RECOVERED
        )
        return BatchExecution(disposition, persisted)
