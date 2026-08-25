from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from feature_core import (
    FEATURE_HISTORY_COLUMNS,
    FEATURE_HISTORY_TABLE,
    FETCH_CANDIDATES_SQL,
    BatchRunMetadata,
    ClickHouseFeatureHistoryBackend,
    FeatureAsOfQuery,
    FeatureHistoryAppendResult,
    FeatureHistoryConflictError,
    FeatureHistoryIntegrityError,
    FeatureHistoryRecord,
    FeatureHistoryRepository,
    FeatureHistoryValidationError,
    FeatureValueType,
    InMemoryFeatureHistoryBackend,
    MaterializedFeatureRow,
    RegistrySnapshotRef,
    SourceKind,
)

BASE = datetime(2026, 1, 5, 1, tzinfo=UTC)
FINGERPRINT = "sha256:" + "a" * 64
HEAD_FINGERPRINT = "sha256:" + "b" * 64
CALCULATOR_FINGERPRINT = "sha256:" + "d" * 64
MANIFEST_CHECKSUM = "sha256:" + "e" * 64


def _registry_ref(*, fingerprint: str = FINGERPRINT) -> RegistrySnapshotRef:
    return RegistrySnapshotRef(
        namespace_id="cn_equity",
        head_fingerprint=HEAD_FINGERPRINT,
        feature_name="close_return_1d",
        feature_version="1.0.0",
        feature_fingerprint=fingerprint,
        algorithm_version="close-return-v1",
    )


def _record(
    *,
    entity_id: str = "600519.SH",
    event_time: datetime = BASE,
    available_time: datetime | None = None,
    processing_time: datetime | None = None,
    value: object = "0.0123",
    revision_salt: str = "r1",
    fingerprint: str = FINGERPRINT,
    value_type: FeatureValueType = FeatureValueType.DECIMAL,
    calculator_fingerprint: str = CALCULATOR_FINGERPRINT,
    run_source_snapshot_version: str = "bars-v7",
) -> FeatureHistoryRecord:
    visible_at = available_time or event_time + timedelta(minutes=5)
    processed_at = processing_time or visible_at + timedelta(seconds=1)
    registry_ref = _registry_ref(fingerprint=fingerprint)
    input_checksum = "sha256:" + "c" * 64
    row = MaterializedFeatureRow(
        feature_name=registry_ref.feature_name,
        feature_version=registry_ref.feature_version,
        feature_fingerprint=registry_ref.feature_fingerprint,
        algorithm_version=registry_ref.algorithm_version,
        partition_key="2026-01-05",
        entity_id=entity_id,
        event_time=event_time,
        available_time=visible_at,
        decision_time=visible_at,
        value=value,
        input_row_ids=("bar-20260105",),
        input_lineage=(),
        input_checksum=input_checksum,
        source_kind=SourceKind.CLICKHOUSE,
        source_snapshot_version="bars-v7",
    )
    run = BatchRunMetadata(
        run_id="materialization-20260105",
        partition_key=row.partition_key,
        partition_start=event_time,
        partition_end=event_time + timedelta(days=1),
        registry_ref=registry_ref,
        source_kind=SourceKind.CLICKHOUSE,
        source_snapshot_version=run_source_snapshot_version,
        decision_time=visible_at,
        data_cutoff_time=visible_at,
        calculator_implementation_fingerprint=calculator_fingerprint,
        input_manifest_checksum=MANIFEST_CHECKSUM,
        determinism_verified=True,
        input_count=1,
        output_count=1,
        input_checksum=input_checksum,
        output_checksum="sha256:" + "f" * 64,
    )
    return FeatureHistoryRecord.from_batch_materialization(
        row=row,
        run=run,
        processing_time=processed_at,
        value_type=value_type,
        revision_nonce=revision_salt,
    )


def _query(
    *,
    as_of: datetime,
    entity_ids: tuple[str, ...] = ("600519.SH",),
    event_start: datetime = BASE - timedelta(minutes=1),
    event_end: datetime = BASE + timedelta(days=1),
    fingerprint: str = FINGERPRINT,
    max_rows: int = 10_000,
) -> FeatureAsOfQuery:
    return FeatureAsOfQuery(
        namespace_id="cn_equity",
        feature_name="close_return_1d",
        feature_version="1.0.0",
        feature_fingerprint=fingerprint,
        entity_ids=entity_ids,
        event_start=event_start,
        event_end=event_end,
        as_of=as_of,
        max_rows=max_rows,
    )


def test_as_of_query_selects_latest_visible_revision_without_future_leakage() -> None:
    old = _record(value="0.0100", revision_salt="old")
    revised = _record(
        available_time=BASE + timedelta(hours=3),
        processing_time=BASE + timedelta(hours=3, seconds=1),
        value="0.0123",
        revision_salt="revised",
    )
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append((old, revised))

    before_revision = repository.query_as_of(_query(as_of=BASE + timedelta(hours=2)))
    after_revision = repository.query_as_of(_query(as_of=BASE + timedelta(hours=4)))

    assert before_revision.records == (old,)
    assert after_revision.records == (revised,)


def test_processing_time_controls_point_in_time_visibility() -> None:
    record = _record()
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append((record,))

    before_processing = repository.query_as_of(_query(as_of=record.available_time))
    at_processing = repository.query_as_of(_query(as_of=record.processing_time))

    assert before_processing.records == ()
    assert at_processing.records == (record,)


def test_event_range_is_half_open_and_batch_results_are_sorted() -> None:
    first = _record(entity_id="000001.SZ", revision_salt="first")
    at_end = _record(
        entity_id="600519.SH",
        event_time=BASE + timedelta(days=1),
        revision_salt="end",
    )
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append((at_end, first))

    result = repository.query_as_of(
        _query(
            as_of=BASE + timedelta(days=2),
            entity_ids=("600519.SH", "000001.SZ"),
        )
    )

    assert result.records == (first,)


def test_query_requires_exact_feature_fingerprint() -> None:
    other_fingerprint = "sha256:" + "d" * 64
    expected = _record(revision_salt="expected")
    other = _record(
        fingerprint=other_fingerprint,
        value="99",
        revision_salt="other",
    )
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append((expected, other))

    result = repository.query_as_of(_query(as_of=BASE + timedelta(hours=1)))

    assert result.records == (expected,)


def test_append_is_idempotent() -> None:
    record = _record()
    backend = InMemoryFeatureHistoryBackend()
    repository = FeatureHistoryRepository(backend)

    first = repository.append((record,))
    second = repository.append((record,))
    assert (first.inserted_count, first.existing_count) == (1, 0)
    assert (second.inserted_count, second.existing_count) == (0, 1)


def test_ambiguous_latest_revision_fails_closed() -> None:
    first = _record(value="1", revision_salt="first")
    second = _record(value="2", revision_salt="second")
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append((first, second))

    with pytest.raises(FeatureHistoryConflictError, match="ambiguous"):
        repository.query_as_of(_query(as_of=BASE + timedelta(hours=1)))


class _LeakingBackend:
    def __init__(self, leaked: FeatureHistoryRecord) -> None:
        self._leaked = leaked

    def append(
        self, records: tuple[FeatureHistoryRecord, ...]
    ) -> FeatureHistoryAppendResult:  # pragma: no cover - query-only test double
        raise AssertionError(records)

    def fetch_candidates(self, query: FeatureAsOfQuery) -> tuple[FeatureHistoryRecord, ...]:
        return (self._leaked,)


def test_repository_rejects_backend_future_data() -> None:
    future = _record(available_time=BASE + timedelta(hours=2))
    repository = FeatureHistoryRepository(_LeakingBackend(future))

    with pytest.raises(FeatureHistoryIntegrityError, match="future-visible"):
        repository.query_as_of(_query(as_of=BASE + timedelta(hours=1)))

    future_processed = _record(
        available_time=BASE + timedelta(minutes=30),
        processing_time=BASE + timedelta(hours=2),
        revision_salt="future-processed",
    )
    processing_repository = FeatureHistoryRepository(_LeakingBackend(future_processed))
    with pytest.raises(FeatureHistoryIntegrityError, match="future-processed"):
        processing_repository.query_as_of(_query(as_of=BASE + timedelta(hours=1)))


class _FakeClickHouseClient:
    def __init__(self) -> None:
        self.query_results: list[tuple[Mapping[str, object], ...]] = []
        self.queries: list[tuple[str, Mapping[str, object]]] = []
        self.inserts: list[tuple[str, tuple[Sequence[object], ...], tuple[str, ...]]] = []

    def insert(
        self,
        table: str,
        rows: Sequence[Sequence[object]],
        *,
        column_names: Sequence[str],
    ) -> None:
        self.inserts.append((table, tuple(rows), tuple(column_names)))

    def query(
        self,
        sql: str,
        *,
        parameters: Mapping[str, object],
    ) -> Iterable[Mapping[str, object]]:
        self.queries.append((sql, parameters))
        if self.query_results:
            return self.query_results.pop(0)
        return ()


def _inserted_row(client: _FakeClickHouseClient) -> Mapping[str, object]:
    _, rows, columns = client.inserts[-1]
    return dict(zip(columns, rows[0], strict=True))


def test_clickhouse_adapter_uses_bound_as_of_and_entity_parameters() -> None:
    client = _FakeClickHouseClient()
    backend = ClickHouseFeatureHistoryBackend(client)
    query = _query(as_of=BASE + timedelta(hours=1))

    assert backend.fetch_candidates(query) == ()

    sql, parameters = client.queries[-1]
    assert sql == FETCH_CANDIDATES_SQL
    assert "available_time <= {as_of:" in sql
    assert "processing_time <= {as_of:" in sql
    assert "600519.SH" not in sql
    assert parameters["entity_ids"] == ("600519.SH",)
    assert parameters["as_of"] == query.as_of
    assert parameters["candidate_limit"] == query.candidate_limit


def test_clickhouse_adapter_round_trips_and_checks_persisted_checksum() -> None:
    record = _record()
    client = _FakeClickHouseClient()
    backend = ClickHouseFeatureHistoryBackend(client)

    result = backend.append((record,))
    persisted_row = _inserted_row(client)
    client.query_results.append((persisted_row,))
    fetched = backend.fetch_candidates(_query(as_of=record.available_time + timedelta(seconds=1)))

    assert (result.inserted_count, result.existing_count) == (1, 0)
    assert client.inserts[0][0] == FEATURE_HISTORY_TABLE
    assert client.inserts[0][2] == FEATURE_HISTORY_COLUMNS
    assert fetched == (record,)

    tampered = dict(persisted_row)
    tampered["record_checksum"] = "sha256:" + "0" * 64
    client.query_results.append((tampered,))
    with pytest.raises(FeatureHistoryIntegrityError, match="record_checksum"):
        backend.fetch_candidates(_query(as_of=record.available_time + timedelta(seconds=1)))


def test_candidate_limit_fails_closed_before_partial_selection() -> None:
    records = tuple(
        _record(
            event_time=BASE + timedelta(minutes=index),
            revision_salt=f"candidate-{index}",
        )
        for index in range(17)
    )
    repository = FeatureHistoryRepository(InMemoryFeatureHistoryBackend())
    repository.append(records)

    with pytest.raises(FeatureHistoryIntegrityError, match="candidate limit"):
        repository.query_as_of(_query(as_of=BASE + timedelta(days=1), max_rows=1))


def test_clickhouse_physical_duplicate_is_idempotent_on_read() -> None:
    record = _record()
    writer = _FakeClickHouseClient()
    ClickHouseFeatureHistoryBackend(writer).append((record,))
    persisted = _inserted_row(writer)
    reader = _FakeClickHouseClient()
    reader.query_results.append((persisted, persisted))
    repository = FeatureHistoryRepository(ClickHouseFeatureHistoryBackend(reader))

    result = repository.query_as_of(_query(as_of=record.available_time + timedelta(seconds=1)))

    assert result.records == (record,)


def test_clickhouse_forged_physical_revision_fails_closed() -> None:
    first = _record(value="0.01", revision_salt="first")
    second = _record(value="0.02", revision_salt="second")
    first_writer = _FakeClickHouseClient()
    second_writer = _FakeClickHouseClient()
    ClickHouseFeatureHistoryBackend(first_writer).append((first,))
    ClickHouseFeatureHistoryBackend(second_writer).append((second,))
    forged = dict(_inserted_row(second_writer))
    forged["revision_id"] = first.revision_id
    reader = _FakeClickHouseClient()
    reader.query_results.append((_inserted_row(first_writer), forged))

    with pytest.raises(FeatureHistoryIntegrityError, match="invalid historical"):
        ClickHouseFeatureHistoryBackend(reader).fetch_candidates(
            _query(as_of=first.available_time + timedelta(seconds=1))
        )


def test_clickhouse_out_of_boundary_and_naive_time_rows_fail_closed() -> None:
    future = _record(available_time=BASE + timedelta(hours=2))
    writer = _FakeClickHouseClient()
    ClickHouseFeatureHistoryBackend(writer).append((future,))
    persisted = _inserted_row(writer)

    future_reader = _FakeClickHouseClient()
    future_reader.query_results.append((persisted,))
    repository = FeatureHistoryRepository(ClickHouseFeatureHistoryBackend(future_reader))
    with pytest.raises(FeatureHistoryIntegrityError, match="future-visible"):
        repository.query_as_of(_query(as_of=BASE + timedelta(hours=1)))

    naive = dict(persisted)
    naive["event_time"] = future.event_time.replace(tzinfo=None)
    naive_reader = _FakeClickHouseClient()
    naive_reader.query_results.append((naive,))
    with pytest.raises(FeatureHistoryIntegrityError, match="invalid historical"):
        ClickHouseFeatureHistoryBackend(naive_reader).fetch_candidates(
            _query(as_of=BASE + timedelta(hours=3))
        )


def test_value_type_and_lineage_are_canonical_and_tamper_evident() -> None:
    decimal = _record(value="1.2300")
    vector = _record(
        value={"weights": ["0.25", "0.75"]},
        value_type=FeatureValueType.VECTOR,
        revision_salt="vector",
    )

    assert decimal.value == "1.23"
    assert vector.value == {"weights": ("0.25", "0.75")}
    with pytest.raises(FeatureHistoryValidationError, match="decimal string"):
        _record(value=1.23)
    with pytest.raises(FeatureHistoryValidationError, match="sha256 fingerprint"):
        _record(calculator_fingerprint="not-a-fingerprint")
    with pytest.raises(FeatureHistoryValidationError, match="source provenance"):
        _record(run_source_snapshot_version="tampered")

    writer = _FakeClickHouseClient()
    ClickHouseFeatureHistoryBackend(writer).append((decimal,))
    tampered = dict(_inserted_row(writer))
    tampered["source_snapshot_version"] = "tampered"
    reader = _FakeClickHouseClient()
    reader.query_results.append((tampered,))
    with pytest.raises(FeatureHistoryIntegrityError, match="invalid historical"):
        ClickHouseFeatureHistoryBackend(reader).fetch_candidates(
            _query(as_of=decimal.available_time + timedelta(seconds=1))
        )
