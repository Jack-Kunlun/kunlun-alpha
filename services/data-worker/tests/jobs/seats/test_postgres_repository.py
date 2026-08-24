from __future__ import annotations

import os
from collections.abc import Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from data_worker.jobs.seats import (
    BatchConflictError,
    NormalizedSeatTrade,
    PostgresSeatRepository,
    RawSeatListRecord,
    RejectedSeatRecord,
    RevisionConflictError,
    SeatBatchResult,
    SeatProviderBatch,
)
from data_worker.storage import migrations as worker_migrations
from seat_core import Currency, Trade
from seat_core.resolution import ResolutionStatus


class _RollbackCursor:
    def __init__(self, fail_after_begin: bool = False) -> None:
        self.statements: list[str] = []
        self.parameters: list[Sequence[object] | None] = []
        self.closed = False
        self.fail_after_begin = fail_after_begin

    def execute(self, query: str, params: Sequence[object] | None = None) -> object:
        self.statements.append(query)
        self.parameters.append(params)
        if self.fail_after_begin and query != "BEGIN":
            raise RuntimeError("write failed")
        return None

    def fetchone(self) -> tuple[object, ...] | None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return []

    def close(self) -> None:
        self.closed = True


class _RollbackConnection:
    def __init__(self, fail_after_begin: bool = False) -> None:
        self.cursor_instance = _RollbackCursor(fail_after_begin)
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self) -> _RollbackCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def _create_worker_base_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          attempts INTEGER NOT NULL,
          max_attempts INTEGER NOT NULL,
          lease_token TEXT,
          lease_expires_at TIMESTAMPTZ,
          next_run_at TIMESTAMPTZ,
          last_error_category TEXT,
          last_error_detail JSONB,
          dead_letter_detail JSONB,
          created_at TIMESTAMPTZ NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE checkpoints (
          task_id TEXT PRIMARY KEY,
          cursor TEXT,
          state JSONB,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE quality_events (
          id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          unified_code TEXT,
          date DATE,
          detail TEXT
        );
        """
    )


@pytest.fixture()
def isolated_postgres() -> Generator[tuple[str, str, Any], None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")

    schema = f"seat_p4n03_{uuid4().hex}"
    connection: Any = None
    try:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
        connection = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with connection.transaction(), connection.cursor() as cursor:
            _create_worker_base_schema(cursor)
        yield dsn, schema, psycopg
    finally:
        if connection is not None:
            connection.close()
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def _pg_connection(context: tuple[str, str, Any]) -> Any:
    dsn, schema, psycopg = context
    return psycopg.connect(dsn, options=f'-c search_path="{schema}"')


def _pg_raw(
    revision_id: str,
    *,
    previous_revision_id: str | None = None,
    payload: bytes = b"pg-test",
    buy_amount: str = "100.00",
    raw_seat_name: str = "PG Test Securities营业部",
) -> RawSeatListRecord:
    return RawSeatListRecord.from_provider(
        source="pg-provider",
        source_version="v1",
        trade_date=date(2026, 8, 21),
        event_time=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        publish_time=datetime(2026, 8, 21, 8, 0, tzinfo=UTC),
        ingest_time=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 21, 9, 0, tzinfo=UTC),
        raw_seat_name=raw_seat_name,
        listing_reason="integration-test",
        raw_instrument_id="SH.600519",
        buy_amount=buy_amount,
        sell_amount="40.00",
        vendor_net_amount="60.00",
        raw_payload=payload,
        revision_id=revision_id,
        previous_revision_id=previous_revision_id,
    )


def _pg_rejected(raw: RawSeatListRecord, reason: str = "integration_test") -> RejectedSeatRecord:
    return RejectedSeatRecord(
        raw_record_id=raw.raw_record_id,
        revision_id=raw.revision_id,
        reason=reason,
        detail="durable integration proof",
        resolution_status=ResolutionStatus.REJECT,
        candidate_seat_ids=(),
        candidate_evidence_ids=(),
    )


def _pg_normalized(raw: RawSeatListRecord) -> NormalizedSeatTrade:
    trade = Trade(
        trade_id=f"pg-trade-{raw.revision_id}",
        revision_id=raw.revision_id,
        previous_revision_id=raw.previous_revision_id,
        seat_id=f"seat-{'0' * 64}",
        raw_seat_name=raw.raw_seat_name,
        instrument_id="600519.SH",
        trade_date=raw.trade_date,
        currency=Currency.CNY,
        buy_amount=raw.buy_amount,
        sell_amount=raw.sell_amount,
        net_amount=raw.buy_amount - raw.sell_amount,
        source=raw.source,
        source_version=raw.source_version,
        raw_record_id=raw.raw_record_id,
        evidence_id=raw.evidence_id,
        available_time=raw.available_time,
        schema_version="seat-trade-v1",
    )
    return NormalizedSeatTrade(
        trade=trade,
        listing_reason=raw.listing_reason,
        provider_evidence_id=raw.evidence_id,
        seat_evidence_ids=("seat-evidence-pg",),
        resolution_status=ResolutionStatus.AUTO,
        resolution_fingerprint=f"resolution-{raw.revision_id}",
    )


def _pg_result(
    batch_id: str,
    route_key: str,
    records: tuple[RawSeatListRecord, ...],
    *,
    checkpoint_token: str | None,
    expected_previous_checkpoint: str | None = None,
    normalized_trades: tuple[NormalizedSeatTrade, ...] = (),
    rejected_records: tuple[RejectedSeatRecord, ...] = (),
) -> SeatBatchResult:
    provider_batch = SeatProviderBatch(
        batch_id=batch_id,
        source=records[0].source,
        source_version=records[0].source_version,
        records=records,
        checkpoint_token=checkpoint_token,
    )
    return SeatBatchResult(
        batch_id=batch_id,
        route_key=route_key,
        request_fingerprint=f"request-{batch_id}",
        batch_fingerprint=provider_batch.batch_fingerprint,
        raw_records=records,
        normalized_trades=normalized_trades,
        rejected_records=rejected_records,
        checkpoint_token=checkpoint_token,
        expected_previous_checkpoint=expected_previous_checkpoint,
    )


def test_postgres_commit_rolls_back_and_closes_cursor_on_failure() -> None:
    connection = _RollbackConnection(fail_after_begin=True)
    repository = PostgresSeatRepository(connection)
    result = SeatBatchResult(
        batch_id="rollback-batch",
        route_key="rollback-route",
        request_fingerprint="rollback-request",
        batch_fingerprint="rollback-provider",
        raw_records=(),
        normalized_trades=(),
        rejected_records=(),
        checkpoint_token=None,
    )

    with pytest.raises(RuntimeError, match="write failed"):
        repository.commit(result)

    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert connection.cursor_instance.statements[0] == "BEGIN"
    assert len(connection.cursor_instance.statements) == 2
    assert connection.cursor_instance.closed is True


def test_postgres_commit_locks_route_then_sorted_resources() -> None:
    connection = _RollbackConnection()
    raw_a = _pg_raw("lock-a", payload=b"lock-a")
    raw_b = _pg_raw("lock-b", payload=b"lock-b")

    PostgresSeatRepository(connection).commit(
        _pg_result(
            "lock-batch",
            "lock-route",
            (raw_b, raw_a),
            checkpoint_token=None,
            rejected_records=(_pg_rejected(raw_a, "missing_previous_revision"),),
        )
    )

    locks = [
        str(params[0])
        for query, params in zip(
            connection.cursor_instance.statements,
            connection.cursor_instance.parameters,
            strict=True,
        )
        if "pg_advisory_xact_lock" in query and params is not None
    ]
    assert locks[0] == "seat-route:lock-route"
    assert locks[1:] == sorted(locks[1:])


def test_repository_initialize_delegates_to_registered_data_worker_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _RollbackConnection()
    calls: list[object] = []

    def migrate(received: object) -> None:
        calls.append(received)

    monkeypatch.setattr(worker_migrations, "apply_data_worker_migrations", migrate)
    PostgresSeatRepository(connection).initialize()

    assert calls == [connection]


def test_legacy_migration_entry_applies_all_registered_migrations() -> None:
    assert worker_migrations.run_migration is worker_migrations.apply_data_worker_migrations


def test_postgres_repository_restart_reads_committed_batch_and_checkpoint(
    isolated_postgres: tuple[str, str, Any],
) -> None:
    connection = _pg_connection(isolated_postgres)
    repository = PostgresSeatRepository(connection)
    repository.initialize()
    repository.initialize()

    raw = _pg_raw("restart-revision")
    result = _pg_result(
        "restart-batch",
        "restart-route",
        (raw,),
        checkpoint_token="checkpoint-1",
        rejected_records=(_pg_rejected(raw),),
    )
    repository.commit(result)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT version, name FROM data_worker_schema_migrations ORDER BY version")
        assert cursor.fetchall() == [
            (1, "precious_metals_migration"),
            (2, "seat_collection_migration"),
        ]

    restarted_connection = _pg_connection(isolated_postgres)
    restarted = PostgresSeatRepository(restarted_connection)
    assert restarted.get_batch("restart-route", "restart-batch") == result
    assert restarted.checkpoint("restart-route") == "checkpoint-1"
    restarted_connection.close()
    connection.close()


def test_postgres_migration_rejects_same_named_non_unique_latest_index(
    isolated_postgres: tuple[str, str, Any],
) -> None:
    connection = _pg_connection(isolated_postgres)
    worker_migrations.apply_data_worker_migrations(connection)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM data_worker_schema_migrations WHERE version = %s",
            (worker_migrations.SEAT_MIGRATION_VERSION,),
        )
        cursor.execute("DROP INDEX uq_seat_collection_raw_latest")
        cursor.execute(
            "CREATE INDEX uq_seat_collection_raw_latest "
            "ON seat_collection_raw_records (revision_key)"
        )

    with pytest.raises(ValueError, match="uq_seat_collection_raw_latest definition mismatch"):
        worker_migrations.apply_seat_collection_migration(connection)

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM data_worker_schema_migrations WHERE version = %s",
            (worker_migrations.SEAT_MIGRATION_VERSION,),
        )
        assert cursor.fetchone() == (0,)
    connection.close()


class _FailingCursor:
    def __init__(self, cursor: Any, fail_fragment: str) -> None:
        self._cursor = cursor
        self._fail_fragment = fail_fragment

    def execute(self, query: str, params: Sequence[object] | None = None) -> object:
        if self._fail_fragment in query:
            raise RuntimeError("injected batch write failure")
        return self._cursor.execute(query, params)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._cursor.fetchone()

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._cursor.fetchall()

    def close(self) -> None:
        self._cursor.close()


class _FailingConnection:
    def __init__(self, connection: Any, fail_fragment: str) -> None:
        self._connection = connection
        self._fail_fragment = fail_fragment

    def cursor(self) -> _FailingCursor:
        return _FailingCursor(self._connection.cursor(), self._fail_fragment)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


def test_postgres_commit_rollback_removes_all_partial_rows(
    isolated_postgres: tuple[str, str, Any],
) -> None:
    connection = _pg_connection(isolated_postgres)
    repository = PostgresSeatRepository(connection)
    repository.initialize()
    normalized_raw = _pg_raw("rollback-normalized", payload=b"normalized")
    rejected_raw = _pg_raw(
        "rollback-rejected",
        payload=b"rejected",
        raw_seat_name="PG Rejected Securities营业部",
    )
    normalized = _pg_normalized(normalized_raw)
    rejected = _pg_rejected(rejected_raw)
    result = _pg_result(
        "rollback-batch",
        "rollback-route",
        (normalized_raw, rejected_raw),
        checkpoint_token="rollback-checkpoint",
        normalized_trades=(normalized,),
        rejected_records=(rejected,),
    )

    with pytest.raises(RuntimeError, match="injected batch write failure"):
        PostgresSeatRepository(
            _FailingConnection(connection, "INSERT INTO seat_collection_batches")
        ).commit(result)

    verification = _pg_connection(isolated_postgres)
    with verification.transaction(), verification.cursor() as cursor:
        for table in (
            "seat_collection_raw_records",
            "seat_collection_normalized",
            "seat_collection_rejected",
            "seat_collection_batches",
            "seat_collection_checkpoints",
        ):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            assert cursor.fetchone() == (0,)
    verification.close()
    connection.close()


def test_postgres_concurrent_successors_have_one_latest(
    isolated_postgres: tuple[str, str, Any],
) -> None:
    setup = _pg_connection(isolated_postgres)
    setup_repository = PostgresSeatRepository(setup)
    setup_repository.initialize()
    predecessor = _pg_raw("concurrent-predecessor")
    setup_repository.commit(
        _pg_result(
            "concurrent-base-batch",
            "concurrent-route",
            (predecessor,),
            checkpoint_token="base-checkpoint",
        )
    )
    setup.close()

    left_connection = _pg_connection(isolated_postgres)
    right_connection = _pg_connection(isolated_postgres)
    left = _pg_result(
        "concurrent-left-batch",
        "concurrent-route",
        (_pg_raw("concurrent-left", previous_revision_id=predecessor.revision_id),),
        checkpoint_token="left-checkpoint",
        expected_previous_checkpoint="base-checkpoint",
    )
    right = _pg_result(
        "concurrent-right-batch",
        "concurrent-route",
        (_pg_raw("concurrent-right", previous_revision_id=predecessor.revision_id),),
        checkpoint_token="right-checkpoint",
        expected_previous_checkpoint="base-checkpoint",
    )

    def commit(repository: PostgresSeatRepository, result: SeatBatchResult) -> object:
        try:
            return repository.commit(result)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(commit, PostgresSeatRepository(left_connection), left),
            executor.submit(commit, PostgresSeatRepository(right_connection), right),
        )
        outcomes = tuple(future.result() for future in futures)

    assert sum(isinstance(outcome, SeatBatchResult) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, BatchConflictError) for outcome in outcomes) == 1
    expected_checkpoint = (
        ("concurrent-left-batch", "left-checkpoint")
        if isinstance(outcomes[0], SeatBatchResult)
        else ("concurrent-right-batch", "right-checkpoint")
    )
    verification = _pg_connection(isolated_postgres)
    with verification.transaction(), verification.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM seat_collection_raw_records WHERE is_latest = TRUE")
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT batch_id, checkpoint_token FROM seat_collection_checkpoints "
            "WHERE route_key = %s",
            ("concurrent-route",),
        )
        assert cursor.fetchone() == expected_checkpoint
    verification.close()
    left_connection.close()
    right_connection.close()


def test_postgres_concurrent_raw_content_conflict_writes_one_batch(
    isolated_postgres: tuple[str, str, Any],
) -> None:
    setup = _pg_connection(isolated_postgres)
    PostgresSeatRepository(setup).initialize()
    setup.close()

    original = _pg_raw("concurrent-raw-conflict", payload=b"original")
    conflicting = replace(original)
    object.__setattr__(conflicting, "buy_amount", original.buy_amount + Decimal("1.00"))
    first_connection = _pg_connection(isolated_postgres)
    second_connection = _pg_connection(isolated_postgres)
    first = _pg_result(
        "raw-conflict-first",
        "raw-conflict-route",
        (original,),
        checkpoint_token=None,
    )
    second = _pg_result(
        "raw-conflict-second",
        "raw-conflict-route",
        (conflicting,),
        checkpoint_token=None,
    )

    def commit(repository: PostgresSeatRepository, result: SeatBatchResult) -> object:
        try:
            return repository.commit(result)
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(commit, PostgresSeatRepository(first_connection), first),
            executor.submit(commit, PostgresSeatRepository(second_connection), second),
        )
        outcomes = tuple(future.result() for future in futures)

    assert sum(isinstance(outcome, SeatBatchResult) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, RevisionConflictError) for outcome in outcomes) == 1
    verification = _pg_connection(isolated_postgres)
    with verification.transaction(), verification.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM seat_collection_batches")
        assert cursor.fetchone() == (1,)
        cursor.execute("SELECT COUNT(*) FROM seat_collection_raw_records")
        assert cursor.fetchone() == (1,)
    verification.close()
    first_connection.close()
    second_connection.close()
