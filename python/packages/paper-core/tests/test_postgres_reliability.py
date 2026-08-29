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
    AppendOutcome,
    FaultScenarioStatus,
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


class _FakeAdminConnection:
    def __init__(self, cursor: _FakeAdminCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "_FakeAdminConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeAdminCursor:
        return self._cursor


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
