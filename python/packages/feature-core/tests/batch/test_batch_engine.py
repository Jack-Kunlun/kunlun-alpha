from __future__ import annotations

from datetime import UTC, datetime

import pytest
from feature_core.batch import (
    BatchCalculator,
    BatchCheckpoint,
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
    ExecutionDisposition,
    FutureDataLeakageError,
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
    FeatureEntity,
    FeatureFrequency,
    FeatureRegistry,
    FeatureSpec,
    FeatureValueType,
    SourceContract,
)

T0 = datetime(2026, 8, 24, tzinfo=UTC)


def _partition() -> BatchPartition:
    return BatchPartition(
        key="trade_date=2026-08-24",
        start=T0,
        end=datetime(2026, 8, 25, tzinfo=UTC),
        decision_time=datetime(2026, 8, 25, 2, tzinfo=UTC),
    )


def _spec(
    *,
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.MAX_INPUT_AVAILABLE_TIME,
) -> RegisteredFeature:
    spec = FeatureSpec(
        name="market.daily_return",
        version="v1",
        entity=FeatureEntity.INSTRUMENT,
        frequency=FeatureFrequency.DAILY,
        value_type=FeatureValueType.DECIMAL,
        owner="quant-research",
        description="Daily close return",
        algorithm_version="v1",
        calculation_definition="(close_t / close_t_minus_1) - 1",
        window_definition="TRADING_SESSIONS:1",
        filter_policy_version="v1",
        pit_policy_version="v1",
        event_time_field="event_time",
        available_time_field="available_time",
        availability_policy=availability_policy,
        source_contracts=(SourceContract(name="market.daily_bar", version="v1"),),
    )
    genesis = FeatureRegistry.empty(namespace_id="tests.batch")
    registry = genesis.evolve(
        (spec,),
        expected_parent_fingerprint=genesis.head_fingerprint,
    )
    return RegisteredFeature.from_registry(registry, spec.name)


def _row(
    row_id: str,
    *,
    event_time: datetime | None = None,
    available_time: datetime | None = None,
    contract_version: str = "v1",
    close: str = "10.20",
) -> BatchInputRow:
    return BatchInputRow(
        row_id=row_id,
        entity_id="600519.SH",
        event_time=event_time or datetime(2026, 8, 24, 7, tzinfo=UTC),
        available_time=available_time or datetime(2026, 8, 24, 8, tzinfo=UTC),
        lineage=BatchInputLineage(
            reference=BatchInputReference(
                origin=InputOrigin.SOURCE_CONTRACT,
                name="market.daily_bar",
                version=contract_version,
            ),
            source_revision=f"source-{row_id}",
        ),
        payload={"close": close},
    )


class _Source:
    def __init__(self, batch: BatchInputBatch) -> None:
        self.batch = batch
        self.requests: list[object] = []

    def read_partition(self, request: object) -> BatchInputBatch:
        self.requests.append(request)
        return self.batch


def _batch(
    *rows: BatchInputRow,
    source_kind: SourceKind = SourceKind.CLICKHOUSE,
    snapshot_version: str = "bars-snapshot-v1",
) -> BatchInputBatch:
    return BatchInputBatch(
        source_kind=source_kind,
        snapshot_version=snapshot_version,
        rows=rows,
        manifest=PartitionInputManifest.from_rows(rows),
    )


def _identified[CalculatorT: BatchCalculator](calculator: CalculatorT) -> CalculatorT:
    vars(calculator)["identity"] = CalculatorIdentity(
        algorithm_version="v1",
        implementation_fingerprint=canonical_checksum(
            {
                "test_calculator_artifact": str(
                    getattr(calculator, "__qualname__", type(calculator).__qualname__)
                )
            }
        ),
    )
    return calculator


@_identified
def _calculator(
    _spec: FeatureSpec,
    _partition: BatchPartition,
    rows: tuple[BatchInputRow, ...],
) -> tuple[CalculatedFeature, ...]:
    return (
        CalculatedFeature(
            entity_id="600519.SH",
            event_time=datetime(2026, 8, 24, 9, tzinfo=UTC),
            value="0.0200",
            input_row_ids=tuple(row.row_id for row in rows),
        ),
    )


def _engine(
    source: _Source,
    *,
    output_store: InMemoryFeaturePartitionStore | None = None,
    checkpoint_store: InMemoryBatchCheckpointStore | None = None,
) -> tuple[BatchFeatureEngine, InMemoryFeaturePartitionStore, InMemoryBatchCheckpointStore]:
    outputs = output_store or InMemoryFeaturePartitionStore()
    checkpoints = checkpoint_store or InMemoryBatchCheckpointStore()
    return (
        BatchFeatureEngine(
            source=source,
            output_store=outputs,
            checkpoint_store=checkpoints,
        ),
        outputs,
        checkpoints,
    )


@pytest.mark.parametrize("source_kind", [SourceKind.CLICKHOUSE, SourceKind.PARQUET])
def test_same_input_and_version_are_deterministic_and_idempotent(
    source_kind: SourceKind,
) -> None:
    source = _Source(_batch(_row("row-b"), _row("row-a"), source_kind=source_kind))
    engine, outputs, checkpoints = _engine(source)

    first = engine.run(_spec(), _partition(), _calculator)
    second = engine.run(_spec(), _partition(), _calculator)

    assert first.disposition is ExecutionDisposition.COMMITTED
    assert second.disposition is ExecutionDisposition.REPLAYED
    assert first.result == second.result
    assert first.result.metadata.output_checksum == second.result.metadata.output_checksum
    assert first.result.metadata.input_checksum == second.result.metadata.input_checksum
    assert first.result.rows[0].input_row_ids == ("row-a", "row-b")
    assert len(outputs.results) == 1
    assert len(checkpoints.checkpoints) == 1


def test_source_row_order_does_not_change_run_or_checksums() -> None:
    rows = (_row("row-b"), _row("row-a"))
    first_engine, _, _ = _engine(_Source(_batch(*rows)))
    second_engine, _, _ = _engine(_Source(_batch(*reversed(rows))))

    first = first_engine.run(_spec(), _partition(), _calculator).result
    second = second_engine.run(_spec(), _partition(), _calculator).result

    assert first.metadata.run_id == second.metadata.run_id
    assert first.metadata.input_checksum == second.metadata.input_checksum
    assert first.metadata.output_checksum == second.metadata.output_checksum


@pytest.mark.parametrize(
    "row",
    [
        _row("at-end", event_time=datetime(2026, 8, 25, tzinfo=UTC)),
        _row("future-event", event_time=datetime(2026, 8, 26, tzinfo=UTC)),
        _row("future-available", available_time=datetime(2026, 8, 25, 3, tzinfo=UTC)),
    ],
)
def test_future_or_out_of_partition_input_fails_closed(row: BatchInputRow) -> None:
    engine, _, _ = _engine(_Source(_batch(row)))

    with pytest.raises(FutureDataLeakageError):
        engine.run(_spec(), _partition(), _calculator)


def test_exact_decision_time_is_visible() -> None:
    row = _row("boundary", available_time=_partition().decision_time)
    engine, _, _ = _engine(_Source(_batch(row)))

    result = engine.run(_spec(), _partition(), _calculator).result

    assert result.rows[0].available_time == _partition().decision_time


def test_source_contract_version_mismatch_fails_closed() -> None:
    engine, _, _ = _engine(_Source(_batch(_row("wrong", contract_version="v2"))))

    with pytest.raises(BatchValidationError, match="contract"):
        engine.run(_spec(), _partition(), _calculator)


def test_calculator_cannot_reference_unknown_or_future_input() -> None:
    row = _row("known", event_time=datetime(2026, 8, 24, 10, tzinfo=UTC))
    engine, _, _ = _engine(_Source(_batch(row)))

    @_identified
    def unknown_reference(
        _feature_spec: FeatureSpec,
        _batch_partition: BatchPartition,
        _rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        return (
            CalculatedFeature(
                entity_id="600519.SH",
                event_time=datetime(2026, 8, 24, 11, tzinfo=UTC),
                value="0.01",
                input_row_ids=("missing",),
            ),
        )

    with pytest.raises(BatchIntegrityError, match="unknown input"):
        engine.run(_spec(), _partition(), unknown_reference)

    @_identified
    def future_reference(
        _feature_spec: FeatureSpec,
        _batch_partition: BatchPartition,
        _rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        return (
            CalculatedFeature(
                entity_id="600519.SH",
                event_time=datetime(2026, 8, 24, 9, tzinfo=UTC),
                value="0.01",
                input_row_ids=("known",),
            ),
        )

    with pytest.raises(FutureDataLeakageError, match="output event_time"):
        engine.run(_spec(), _partition(), future_reference)


def test_duplicate_input_and_output_identities_fail_closed() -> None:
    duplicate = _row("duplicate")
    engine, _, _ = _engine(_Source(_batch(duplicate, duplicate)))
    with pytest.raises(BatchIntegrityError, match="duplicate input row_id"):
        engine.run(_spec(), _partition(), _calculator)

    engine, _, _ = _engine(_Source(_batch(_row("one"))))

    @_identified
    def duplicate_outputs(
        spec: FeatureSpec,
        partition: BatchPartition,
        rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        first = _calculator(spec, partition, rows)[0]
        return first, first

    with pytest.raises(BatchIntegrityError, match="duplicate output identity"):
        engine.run(_spec(), _partition(), duplicate_outputs)


class _FailOnceCheckpointStore(InMemoryBatchCheckpointStore):
    def __init__(self) -> None:
        super().__init__()
        self._fail = True

    def commit(self, checkpoint: BatchCheckpoint) -> CommitResult[BatchCheckpoint]:
        if self._fail:
            self._fail = False
            raise RuntimeError("simulated checkpoint outage")
        return super().commit(checkpoint)


def test_output_commit_survives_checkpoint_failure_and_recovers_idempotently() -> None:
    source = _Source(_batch(_row("one")))
    outputs = InMemoryFeaturePartitionStore()
    checkpoints = _FailOnceCheckpointStore()
    engine, _, _ = _engine(source, output_store=outputs, checkpoint_store=checkpoints)

    with pytest.raises(RuntimeError, match="checkpoint outage"):
        engine.run(_spec(), _partition(), _calculator)
    assert len(outputs.results) == 1
    assert checkpoints.checkpoints == ()

    recovered = engine.run(_spec(), _partition(), _calculator)
    assert recovered.disposition is ExecutionDisposition.RECOVERED
    assert len(outputs.results) == 1
    assert len(checkpoints.checkpoints) == 1


def test_checkpoint_without_matching_output_fails_closed() -> None:
    source = _Source(_batch(_row("one")))
    first_engine, _, _ = _engine(source)
    completed = first_engine.run(_spec(), _partition(), _calculator).result

    orphaned_checkpoints = InMemoryBatchCheckpointStore()
    orphaned_checkpoints.commit(completed.checkpoint)
    engine, _, _ = _engine(
        source,
        output_store=InMemoryFeaturePartitionStore(),
        checkpoint_store=orphaned_checkpoints,
    )

    with pytest.raises(BatchIntegrityError, match="checkpoint.*output"):
        engine.run(_spec(), _partition(), _calculator)


def test_input_revision_creates_new_immutable_run() -> None:
    source = _Source(_batch(_row("one", close="10.20")))
    engine, outputs, _ = _engine(source)
    first = engine.run(_spec(), _partition(), _calculator)

    source.batch = _batch(_row("one", close="10.30"), snapshot_version="bars-snapshot-v2")
    second = engine.run(_spec(), _partition(), _calculator)

    assert first.result.metadata.run_id != second.result.metadata.run_id
    assert first.result.metadata.input_checksum != second.result.metadata.input_checksum
    assert len(outputs.results) == 2


def test_materialization_time_policy_and_float_values_are_rejected() -> None:
    engine, _, _ = _engine(_Source(_batch(_row("one"))))
    with pytest.raises(BatchValidationError, match="MATERIALIZATION_TIME"):
        engine.run(
            _spec(availability_policy=AvailabilityPolicy.MATERIALIZATION_TIME),
            _partition(),
            _calculator,
        )

    @_identified
    def float_output(
        _feature_spec: FeatureSpec,
        _batch_partition: BatchPartition,
        _rows: tuple[BatchInputRow, ...],
    ) -> tuple[CalculatedFeature, ...]:
        return (
            CalculatedFeature(
                entity_id="600519.SH",
                event_time=datetime(2026, 8, 24, 9, tzinfo=UTC),
                value=0.02,
                input_row_ids=("one",),
            ),
        )

    with pytest.raises(BatchValidationError, match="float"):
        engine.run(_spec(), _partition(), float_output)
