from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest
from feature_core.batch import (
    BatchCheckpoint,
    BatchConflictError,
    BatchFeatureEngine,
    BatchInputBatch,
    BatchInputLineage,
    BatchInputReference,
    BatchInputRow,
    BatchIntegrityError,
    BatchPartition,
    BatchValidationError,
    CalculatedFeature,
    CalculatorIdentity,
    CommitResult,
    CommitStatus,
    InMemoryBatchCheckpointStore,
    InMemoryFeaturePartitionStore,
    InputOrigin,
    PartitionInputManifest,
    RegisteredFeature,
    SourceKind,
    canonical_checksum,
)
from feature_core.registry import (
    AvailabilityPolicy,
    FeatureDependency,
    FeatureEntity,
    FeatureFrequency,
    FeatureRegistry,
    FeatureSpec,
    FeatureValueType,
    SourceContract,
)

T0 = datetime(2026, 8, 24, tzinfo=UTC)


def _feature() -> RegisteredFeature:
    spec = FeatureSpec(
        name="market.daily_return",
        version="v1",
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.DAILY,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research",
        description="Daily return",
        algorithm_version="v1",
        calculation_definition="(close_t / close_t_minus_1) - 1",
        window_definition="TRADING_SESSIONS:1",
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
        source_contracts=(SourceContract(name="market.daily_bar", version="v1"),),
    )
    genesis = FeatureRegistry.empty(namespace_id="tests.batch.integrity")
    registry = genesis.evolve((spec,), expected_parent_fingerprint=genesis.head_fingerprint)
    return RegisteredFeature.from_registry(registry, spec.name)


def _partition() -> BatchPartition:
    return BatchPartition(
        key="trade_date=2026-08-24",
        start=T0,
        end=datetime(2026, 8, 25, tzinfo=UTC),
        decision_time=datetime(2026, 8, 25, 2, tzinfo=UTC),
    )


def _reference() -> BatchInputReference:
    return BatchInputReference(InputOrigin.SOURCE_CONTRACT, "market.daily_bar", "v1")


def _row() -> BatchInputRow:
    return BatchInputRow(
        row_id="bar-1",
        entity_id="600519.SH",
        event_time=datetime(2026, 8, 24, 7, tzinfo=UTC),
        available_time=datetime(2026, 8, 24, 8, tzinfo=UTC),
        lineage=BatchInputLineage(reference=_reference(), source_revision="source-bar-1"),
        payload={"close": "10.20"},
    )


def _batch(
    *rows: BatchInputRow,
    manifest: PartitionInputManifest | None = None,
) -> BatchInputBatch:
    return BatchInputBatch(
        source_kind=SourceKind.CLICKHOUSE,
        snapshot_version="bars-snapshot-v1",
        rows=rows,
        manifest=manifest or PartitionInputManifest.from_rows(rows),
    )


class _Source:
    def __init__(self, batch: BatchInputBatch) -> None:
        self.batch = batch

    def read_partition(self, _request: object) -> BatchInputBatch:
        return self.batch


class _Calculator:
    def __init__(self, value: str = "0.0200") -> None:
        self.value = value
        self.identity = CalculatorIdentity(
            algorithm_version="v1",
            implementation_fingerprint=canonical_checksum(
                {"calculator": "tests.daily-return", "revision": "v1"},
            ),
        )

    def __call__(
        self,
        _spec: object,
        _partition: object,
        rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        return (
            CalculatedFeature(
                entity_id="600519.SH",
                event_time=datetime(2026, 8, 24, 9, tzinfo=UTC),
                value=self.value,
                input_row_ids=tuple(row.row_id for row in rows),
            ),
        )


def _engine(
    batch: BatchInputBatch,
    *,
    outputs: object | None = None,
    checkpoints: object | None = None,
) -> tuple[BatchFeatureEngine, object, object]:
    output_store = outputs or InMemoryFeaturePartitionStore()
    checkpoint_store = checkpoints or InMemoryBatchCheckpointStore()
    return (
        BatchFeatureEngine(
            source=_Source(batch),
            output_store=output_store,
            checkpoint_store=checkpoint_store,
        ),
        output_store,
        checkpoint_store,
    )


def test_decimal_output_is_normalized_before_checksum() -> None:
    engine, _, _ = _engine(_batch(_row()))
    execution = engine.run(_feature(), _partition(), _Calculator("-0.000"))
    assert execution.result.rows[0].value == "0"


def test_missing_required_manifest_entry_fails_closed() -> None:
    engine, outputs, checkpoints = _engine(
        _batch(_row(), manifest=PartitionInputManifest(entries=())),
    )
    with pytest.raises(BatchIntegrityError, match="manifest mismatch"):
        engine.run(_feature(), _partition(), _Calculator())
    assert isinstance(outputs, InMemoryFeaturePartitionStore)
    assert isinstance(checkpoints, InMemoryBatchCheckpointStore)
    assert outputs.results == ()
    assert checkpoints.checkpoints == ()


def test_nondeterministic_calculator_fails_before_commit() -> None:
    class CounterCalculator(_Calculator):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def __call__(
            self,
            _spec: object,
            _partition: object,
            rows: tuple[BatchInputRow, ...],
        ) -> tuple[CalculatedFeature, ...]:
            self.calls += 1
            self.value = f"0.0{self.calls}"
            return super().__call__(_spec, _partition, rows)

    engine, outputs, checkpoints = _engine(_batch(_row()))
    with pytest.raises(BatchIntegrityError, match="non-deterministic"):
        engine.run(_feature(), _partition(), CounterCalculator())
    assert isinstance(outputs, InMemoryFeaturePartitionStore)
    assert isinstance(checkpoints, InMemoryBatchCheckpointStore)
    assert outputs.results == ()
    assert checkpoints.checkpoints == ()


def test_replay_revalidates_persisted_rows() -> None:
    class TamperingStore(InMemoryFeaturePartitionStore):
        tampered = False

        def get(self, run_id: str):
            result = super().get(run_id)
            if result is None or not self.tampered:
                return result
            changed = replace(result.rows[0], value="999")
            return replace(result, rows=(changed,))

    outputs = TamperingStore()
    checkpoints = InMemoryBatchCheckpointStore()
    engine, _, _ = _engine(_batch(_row()), outputs=outputs, checkpoints=checkpoints)
    engine.run(_feature(), _partition(), _Calculator())
    outputs.tampered = True
    with pytest.raises(BatchIntegrityError, match="output checksum"):
        engine.run(_feature(), _partition(), _Calculator())


def test_output_commit_conflict_never_creates_checkpoint() -> None:
    class ConflictStore:
        def get(self, _run_id: str):
            return None

        def commit(self, result):
            return CommitResult(CommitStatus.CONFLICT, result)

    checkpoints = InMemoryBatchCheckpointStore()
    engine, _, _ = _engine(
        _batch(_row()),
        outputs=ConflictStore(),
        checkpoints=checkpoints,
    )
    with pytest.raises(BatchConflictError, match="conflicting persisted output"):
        engine.run(_feature(), _partition(), _Calculator())
    assert checkpoints.checkpoints == ()


def test_checkpoint_commit_conflict_is_not_reported_as_success() -> None:
    class ConflictCheckpointStore:
        def get(self, _run_id: str):
            return None

        def commit(self, checkpoint: BatchCheckpoint):
            different = replace(
                checkpoint,
                output_checksum=canonical_checksum("different"),
            )
            return CommitResult(CommitStatus.CONFLICT, different)

    engine, outputs, _ = _engine(
        _batch(_row()),
        checkpoints=ConflictCheckpointStore(),
    )
    with pytest.raises(BatchConflictError, match="conflicting checkpoint"):
        engine.run(_feature(), _partition(), _Calculator())
    assert isinstance(outputs, InMemoryFeaturePartitionStore)
    assert len(outputs.results) == 1


def test_registry_and_manifest_are_bound_to_run_metadata() -> None:
    feature = _feature()
    engine, _, _ = _engine(_batch(_row()))
    result = engine.run(feature, _partition(), _Calculator()).result
    assert result.metadata.registry_ref.namespace_id == feature.registry.namespace_id
    assert result.metadata.registry_ref.head_fingerprint == feature.registry.head_fingerprint
    assert result.metadata.input_manifest_checksum == canonical_checksum(result.input_manifest)
    assert result.checkpoint.result_checksum == result.result_checksum


def test_in_memory_output_commit_is_linearizable() -> None:
    engine, _, _ = _engine(_batch(_row()))
    result = engine.run(_feature(), _partition(), _Calculator()).result
    store = InMemoryFeaturePartitionStore()
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = tuple(pool.map(lambda _: store.commit(result).status, range(8)))
    assert statuses.count(CommitStatus.CREATED) == 1
    assert statuses.count(CommitStatus.EXISTING_SAME) == 7


def test_output_commit_requires_durable_read_back() -> None:
    class PhantomOutputStore:
        def get(self, _run_id: str):
            return None

        def commit(self, result):
            return CommitResult(CommitStatus.CREATED, result)

    engine, _, _ = _engine(_batch(_row()), outputs=PhantomOutputStore())
    with pytest.raises(BatchIntegrityError, match="invalid result"):
        engine.run(_feature(), _partition(), _Calculator())


def test_checkpoint_commit_requires_durable_read_back() -> None:
    class PhantomCheckpointStore:
        def get(self, _run_id: str):
            return None

        def commit(self, checkpoint: BatchCheckpoint):
            return CommitResult(CommitStatus.CREATED, checkpoint)

    engine, _, _ = _engine(
        _batch(_row()),
        checkpoints=PhantomCheckpointStore(),
    )
    with pytest.raises(BatchIntegrityError, match="checkpoint"):
        engine.run(_feature(), _partition(), _Calculator())


def test_unknown_commit_status_fails_closed() -> None:
    class UnknownStatusStore:
        def get(self, _run_id: str):
            return None

        def commit(self, result):
            forged = object.__new__(CommitResult)
            object.__setattr__(forged, "status", "UNKNOWN")
            object.__setattr__(forged, "persisted", result)
            return forged

    engine, _, _ = _engine(_batch(_row()), outputs=UnknownStatusStore())
    with pytest.raises(BatchIntegrityError, match="commit status"):
        engine.run(_feature(), _partition(), _Calculator())


def test_coordinated_output_and_checkpoint_tampering_is_not_replayed() -> None:
    class SwitchingOutputStore(InMemoryFeaturePartitionStore):
        override = None

        def get(self, run_id: str):
            return self.override or super().get(run_id)

    class SwitchingCheckpointStore(InMemoryBatchCheckpointStore):
        override = None

        def get(self, run_id: str):
            return self.override or super().get(run_id)

    outputs = SwitchingOutputStore()
    checkpoints = SwitchingCheckpointStore()
    engine, _, _ = _engine(
        _batch(_row()),
        outputs=outputs,
        checkpoints=checkpoints,
    )
    result = engine.run(_feature(), _partition(), _Calculator()).result
    changed_row = replace(result.rows[0], value="0.03")
    changed_metadata = replace(
        result.metadata,
        output_checksum=canonical_checksum((changed_row,)),
    )
    changed_result = replace(
        result,
        metadata=changed_metadata,
        rows=(changed_row,),
    )
    outputs.override = changed_result
    checkpoints.override = changed_result.checkpoint

    with pytest.raises(BatchIntegrityError, match="current deterministic calculation"):
        engine.run(_feature(), _partition(), _Calculator())


def test_changed_calculator_behavior_cannot_replay_under_old_identity() -> None:
    calculator = _Calculator("0.02")
    engine, _, _ = _engine(_batch(_row()))
    engine.run(_feature(), _partition(), calculator)
    calculator.value = "0.03"

    with pytest.raises(BatchIntegrityError, match="current deterministic calculation"):
        engine.run(_feature(), _partition(), calculator)


def test_string_input_origin_is_rejected() -> None:
    with pytest.raises(BatchValidationError, match="InputOrigin"):
        BatchInputReference(
            cast(InputOrigin, "FEATURE_DEPENDENCY"),
            "market.daily_bar",
            "v1",
        )


def test_feature_dependency_requires_trusted_provenance_resolver() -> None:
    upstream = FeatureSpec(
        name="market.base_return",
        version="v1",
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.DAILY,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research",
        description="Base return",
        algorithm_version="v1",
        calculation_definition="close_t / close_t_minus_1 - 1",
        window_definition="TRADING_SESSIONS:1",
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
        source_contracts=(SourceContract(name="market.daily_bar", version="v1"),),
    )
    target = FeatureSpec(
        name="market.derived_return",
        version="v1",
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.DAILY,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research",
        description="Derived return",
        algorithm_version="v1",
        calculation_definition="market.base_return",
        window_definition="TRADING_SESSIONS:1",
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
        dependencies=(FeatureDependency(name=upstream.name, version=upstream.version),),
    )
    genesis = FeatureRegistry.empty(namespace_id="tests.batch.dependencies")
    registry = genesis.evolve(
        (upstream, target),
        expected_parent_fingerprint=genesis.head_fingerprint,
    )
    feature = RegisteredFeature.from_registry(registry, target.name)
    reference = BatchInputReference(
        InputOrigin.FEATURE_DEPENDENCY,
        upstream.name,
        upstream.version,
    )
    row = BatchInputRow(
        row_id="upstream-row-1",
        entity_id="600519.SH",
        event_time=datetime(2026, 8, 24, 7, tzinfo=UTC),
        available_time=datetime(2026, 8, 24, 8, tzinfo=UTC),
        lineage=BatchInputLineage(
            reference=reference,
            upstream_run_id=canonical_checksum("upstream-run"),
            upstream_feature_fingerprint=upstream.semantic_fingerprint,
            upstream_output_checksum=canonical_checksum("upstream-output"),
        ),
        payload={"value": "0.02"},
    )
    engine, _, _ = _engine(_batch(row))

    with pytest.raises(BatchIntegrityError, match="provenance resolver"):
        engine.run(feature, _partition(), _Calculator())
