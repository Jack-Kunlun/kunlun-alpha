import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from paper_core.postgres_reliability import (
    ISOLATED_DATABASE_PREFIX,
    PostgresPaperEventStore,
    PostgresPaperFaultHarness,
)
from paper_core.reliability import (
    GENESIS_DIGEST,
    AppendOutcome,
    FaultScenarioStatus,
    PaperRuntimeEvent,
    PersistenceUnavailableError,
    RecoverablePaperRuntime,
    RecoveryInvariantError,
    run_fault_matrix,
)

ADMIN_DSN = os.environ.get("KUNLUN_PAPER_ENDURANCE_ADMIN_DSN")
NOW = datetime(2026, 8, 27, 1, 2, 3, tzinfo=UTC)


class _FakeAdminCursor:
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        self._rows = rows
        self.statements: list[object] = []

    def __enter__(self) -> "_FakeAdminCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object, _params: object = None) -> None:
        self.statements.append(statement)

    def fetchone(self) -> dict[str, object] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[dict[str, object]]:
        rows = [row for row in self._rows if row is not None]
        self._rows.clear()
        return rows


class _FakeAdminConnection:
    def __init__(self, cursor: _FakeAdminCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeAdminConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeAdminCursor:
        return self._cursor


def _skip_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def postgres_harness() -> Iterator[PostgresPaperFaultHarness]:
    if ADMIN_DSN is None:
        pytest.skip("KUNLUN_PAPER_ENDURANCE_ADMIN_DSN is not configured")
    database_name = f"kunlun_paper_endurance_test_{uuid4().hex}"
    harness = PostgresPaperFaultHarness(
        admin_dsn=ADMIN_DSN,
        database_name=database_name,
    )
    harness.prepare_database()
    try:
        yield harness
    finally:
        harness.drop_database()


def test_harness_rejects_a_non_isolated_database_name() -> None:
    with pytest.raises(ValueError, match="isolated endurance database"):
        PostgresPaperFaultHarness(
            admin_dsn="postgresql://example.invalid/postgres",
            database_name="kunlun",
        )


def test_harness_generates_an_unpredictable_uuid_database_name_by_default() -> None:
    harness = PostgresPaperFaultHarness(admin_dsn="postgresql://example.invalid/postgres")

    assert re.fullmatch(
        rf"{re.escape(ISOLATED_DATABASE_PREFIX)}[0-9a-f]{{32}}",
        harness.database_name,
    )


def test_harness_rejects_a_predictable_explicit_database_name() -> None:
    with pytest.raises(ValueError, match="UUID"):
        PostgresPaperFaultHarness(
            admin_dsn="postgresql://example.invalid/postgres",
            database_name=f"{ISOLATED_DATABASE_PREFIX}p6n12",
        )


def test_prepare_database_rejects_an_existing_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_name = f"{ISOLATED_DATABASE_PREFIX}test_{uuid4().hex}"
    harness = PostgresPaperFaultHarness(
        admin_dsn="postgresql://example.invalid/postgres",
        database_name=database_name,
    )
    cursor = _FakeAdminCursor(
        [
            {"database_name": "postgres"},
            {"datallowconn": True},
        ]
    )
    monkeypatch.setattr(harness, "_admin_connection", lambda: _FakeAdminConnection(cursor))

    def skip_initialize(_store: PostgresPaperEventStore) -> None:
        return None

    monkeypatch.setattr(PostgresPaperEventStore, "initialize", skip_initialize)

    with pytest.raises(ValueError, match="already exists"):
        harness.prepare_database()


def test_harness_rejects_an_endurance_database_as_the_admin_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = PostgresPaperFaultHarness(
        admin_dsn="postgresql://example.invalid/postgres",
        database_name=f"{ISOLATED_DATABASE_PREFIX}{uuid4().hex}",
    )
    cursor = _FakeAdminCursor([{"database_name": f"{ISOLATED_DATABASE_PREFIX}p6n12_r2"}])
    monkeypatch.setattr(harness, "_admin_connection", lambda: _FakeAdminConnection(cursor))

    with pytest.raises(ValueError, match="control database"):
        harness.active_connection_count()


@pytest.mark.parametrize("operation", ("drop", "outage"))
def test_harness_refuses_destructive_operations_without_its_ownership_marker(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_name = f"{ISOLATED_DATABASE_PREFIX}test_{uuid4().hex}"
    harness = PostgresPaperFaultHarness(
        admin_dsn="postgresql://example.invalid/postgres",
        database_name=database_name,
    )
    cursor = _FakeAdminCursor(
        [
            {"database_name": "postgres"},
            {"ownership_marker": "marker-from-another-run"},
        ]
    )
    monkeypatch.setattr(harness, "_admin_connection", lambda: _FakeAdminConnection(cursor))
    monkeypatch.setattr(harness, "_wait_until_available", lambda: None)

    with pytest.raises(RecoveryInvariantError, match="ownership marker"):
        if operation == "drop":
            harness.drop_database()
        else:
            with harness.database_outage():
                pass


def test_ownership_marker_lookup_uses_the_shared_object_description_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = PostgresPaperFaultHarness(
        admin_dsn="postgresql://example.invalid/postgres",
        database_name=f"{ISOLATED_DATABASE_PREFIX}test_{uuid4().hex}",
    )
    marker = "marker-for-test"
    monkeypatch.setattr(harness, "_ownership_marker", marker)
    cursor = _FakeAdminCursor(
        [
            {"database_name": "postgres"},
            {"ownership_marker": marker},
            {"connection_count": 0},
        ]
    )
    monkeypatch.setattr(harness, "_admin_connection", lambda: _FakeAdminConnection(cursor))

    assert harness.active_connection_count() == 0
    assert "shobj_description(oid, 'pg_database')" in str(cursor.statements[1])


def test_postgres_store_retries_a_transient_connection_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresPaperEventStore("postgresql://example.invalid/postgres")
    cursor = _FakeAdminCursor([])
    connection_attempts = 0

    def connect() -> _FakeAdminConnection:
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        return _FakeAdminConnection(cursor)

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr("paper_core.postgres_reliability.time.sleep", _skip_sleep)

    assert store.read_stream("transient-read") == ()
    assert connection_attempts == 2


def test_postgres_store_bounds_transient_connection_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PostgresPaperEventStore("postgresql://example.invalid/postgres")
    connection_attempts = 0

    def connect() -> _FakeAdminConnection:
        nonlocal connection_attempts
        connection_attempts += 1
        raise psycopg.errors.ConnectionTimeout("connection timeout expired")

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr("paper_core.postgres_reliability.time.sleep", _skip_sleep)

    with pytest.raises(PersistenceUnavailableError, match="after 3 attempts"):
        store.read_stream("persistent-outage")

    assert connection_attempts == 3


def test_database_outage_retries_a_transient_admin_timeout_during_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = PostgresPaperFaultHarness(
        admin_dsn="postgresql://example.invalid/postgres",
        database_name=f"{ISOLATED_DATABASE_PREFIX}test_{uuid4().hex}",
        recovery_timeout_seconds=1,
    )
    marker = "marker-for-restore-test"
    monkeypatch.setattr(harness, "_ownership_marker", marker)
    disable_cursor = _FakeAdminCursor(
        [
            {"database_name": "postgres"},
            {"ownership_marker": marker},
        ]
    )
    restore_cursor = _FakeAdminCursor(
        [
            {"database_name": "postgres"},
            {"ownership_marker": marker},
        ]
    )
    connection_attempts = 0

    def admin_connection() -> _FakeAdminConnection:
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            return _FakeAdminConnection(disable_cursor)
        if connection_attempts == 2:
            raise psycopg.errors.ConnectionTimeout("connection timeout expired")
        return _FakeAdminConnection(restore_cursor)

    monkeypatch.setattr(harness, "_admin_connection", admin_connection)
    monkeypatch.setattr(harness, "_wait_until_available", lambda: None)
    monkeypatch.setattr("paper_core.postgres_reliability.time.sleep", _skip_sleep)

    with harness.database_outage():
        pass

    assert connection_attempts == 3
    assert "false" in str(disable_cursor.statements[-2])
    assert "true" in str(restore_cursor.statements[-1])


def test_postgres_store_survives_reopen_and_keeps_duplicates_idempotent(
    postgres_harness: PostgresPaperFaultHarness,
) -> None:
    first_runtime = RecoverablePaperRuntime(postgres_harness.new_store())
    first = first_runtime.append_message(
        stream_id="account-restart",
        event_id="deposit-1",
        event_type="CASH_DEPOSITED",
        payload={"amount": "100000.00", "currency": "CNY"},
        occurred_at=NOW,
    )

    restarted = RecoverablePaperRuntime(postgres_harness.new_store())
    recovered = restarted.recover("account-restart")
    duplicate = restarted.append_message(
        stream_id="account-restart",
        event_id="deposit-1",
        event_type="CASH_DEPOSITED",
        payload={"amount": "100000.00", "currency": "CNY"},
        occurred_at=NOW,
    )

    assert first.outcome is AppendOutcome.APPLIED
    assert recovered.event_ids == ("deposit-1",)
    assert duplicate.outcome is AppendOutcome.DUPLICATE
    assert duplicate.projection.event_count == 1


def test_postgres_store_recovers_an_ambiguous_commit_as_an_idempotent_duplicate(
    postgres_harness: PostgresPaperFaultHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = postgres_harness.new_store()
    event = PaperRuntimeEvent.build(
        stream_id="ambiguous-commit",
        event_id="deposit-ambiguous-1",
        event_type="CASH_DEPOSITED",
        sequence=1,
        occurred_at=NOW,
        payload={"amount": "100000.00", "currency": "CNY"},
        prior_digest=GENESIS_DIGEST,
    )
    original_append = store._append_event_once  # pyright: ignore[reportPrivateUsage]
    append_attempts = 0

    def lose_first_acknowledgement(
        candidate: PaperRuntimeEvent,
        *,
        expected_head_digest: str,
    ) -> tuple[AppendOutcome, tuple[PaperRuntimeEvent, ...]]:
        nonlocal append_attempts
        append_attempts += 1
        result = original_append(
            candidate,
            expected_head_digest=expected_head_digest,
        )
        if append_attempts == 1:
            raise psycopg.errors.ConnectionTimeout("commit acknowledgement was lost")
        return result

    monkeypatch.setattr(store, "_append_event_once", lose_first_acknowledgement)

    outcome, events = store.append_event(event, expected_head_digest=GENESIS_DIGEST)

    assert append_attempts == 2
    assert outcome is AppendOutcome.DUPLICATE
    assert events == (event,)


def test_postgres_store_serializes_concurrent_stream_appends(
    postgres_harness: PostgresPaperFaultHarness,
) -> None:
    def append(event_id: str) -> AppendOutcome:
        receipt = RecoverablePaperRuntime(postgres_harness.new_store()).append_message(
            stream_id="concurrent-stream",
            event_id=event_id,
            event_type="ORDER_RESERVED",
            payload={"amount": "1000.00", "eventId": event_id},
            occurred_at=NOW,
        )
        return receipt.outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(append, ("reserve-1", "reserve-2")))

    recovered = RecoverablePaperRuntime(postgres_harness.new_store()).recover("concurrent-stream")
    assert outcomes == (AppendOutcome.APPLIED, AppendOutcome.APPLIED)
    assert recovered.event_count == 2
    assert set(recovered.event_ids) == {"reserve-1", "reserve-2"}


def test_postgres_fault_matrix_disables_only_the_isolated_database(
    postgres_harness: PostgresPaperFaultHarness,
) -> None:
    results = run_fault_matrix(now=NOW, harness=postgres_harness)

    assert len(results) == 4
    assert all(result.status is FaultScenarioStatus.PASS for result in results)


def test_postgres_fault_matrix_passes_one_hundred_high_frequency_iterations(
    postgres_harness: PostgresPaperFaultHarness,
) -> None:
    for _iteration in range(100):
        results = run_fault_matrix(now=NOW, harness=postgres_harness)
        assert all(result.status is FaultScenarioStatus.PASS for result in results)


def test_postgres_outage_keeps_the_admin_database_available_and_recovers(
    postgres_harness: PostgresPaperFaultHarness,
) -> None:
    assert ADMIN_DSN is not None
    store = postgres_harness.new_store()

    with postgres_harness.database_outage():
        with pytest.raises(PersistenceUnavailableError):
            store.read_stream("outage-isolation")
        with psycopg.connect(ADMIN_DSN) as admin, admin.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    assert store.read_stream("outage-isolation") == ()
