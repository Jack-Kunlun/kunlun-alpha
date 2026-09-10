"""Focused contract tests for the additive official-calendar V4 boundary."""

from __future__ import annotations

import hashlib
import inspect
import os
import runpy
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import data_worker.jobs.calendars.official_calendar_repository as repository_module
import data_worker.jobs.calendars.official_szse_daily as official_szse_daily_module
import psycopg
import pytest
from data_worker.jobs.calendars.official_calendar_repository import (
    OfficialCalendarPersistenceError,
    PostgresOfficialCalendarRepository,
    official_calendar_snapshot_id,
)
from data_worker.jobs.calendars.official_szse_daily import SzseOfficialCalendarCollector
from data_worker.raw import LocalFileStorage
from data_worker.storage import (
    OFFICIAL_CALENDAR_MIGRATION,
    OFFICIAL_CALENDAR_MIGRATION_VERSION,
    apply_data_worker_migrations,
    load_official_calendar_migration,
)
from psycopg import Error as PsycopgError
from psycopg.pq import TransactionStatus


def test_v4_migration_is_a_distinct_packaged_resource() -> None:
    resource = load_official_calendar_migration()
    assert resource
    assert OFFICIAL_CALENDAR_MIGRATION.encode("utf-8") == resource
    assert len(hashlib.sha256(resource).hexdigest()) == 64
    assert OFFICIAL_CALENDAR_MIGRATION_VERSION == 4
    for table in (
        "official_calendar_scan_runs",
        "official_calendar_evidence_refs",
        "official_calendar_capture_attempts",
        "official_calendar_run_catalogs",
        "official_calendar_run_passes",
        "official_calendar_run_pages",
        "official_calendar_snapshots",
        "official_calendar_snapshot_evidence",
        "official_calendar_snapshot_days",
    ):
        assert f"CREATE TABLE {table}" in OFFICIAL_CALENDAR_MIGRATION


def test_v4_resource_is_in_source_tree_and_wheel_configuration() -> None:
    resource_path = (
        Path(__file__).parents[3] / "src/data_worker/jobs/calendars/official_calendar_migration.sql"
    )
    assert resource_path.exists()


def test_writer_public_boundary_has_no_result_or_proof_parameter() -> None:
    signature = inspect.signature(PostgresOfficialCalendarRepository.persist_authoritative_szse_run)
    assert "raw_storage" in signature.parameters
    assert "run_id" in signature.parameters
    assert "manifest_date" in signature.parameters
    assert "manifest_capture_id" in signature.parameters
    assert "result" not in signature.parameters
    assert "proof" not in signature.parameters


def test_v4_shape_matches_current_c2a_identity_path_contract(tmp_path: Path) -> None:
    result, _raw, _helpers = _collect_result(tmp_path)

    references, role_map = repository_module._validate_result_shape(result)  # pyright: ignore[reportPrivateUsage]

    assert len(result.identity_assets) == 4
    assert tuple(reference.kind for reference in result.identity_assets) == (
        "root",
        "path",
        "concat",
        "js",
    )
    assert len(result.attempts) == 28
    assert len(references) == 69
    assert tuple(
        role_map[(reference.kind, reference.capture_id, reference.checksum)]
        for reference in result.identity_assets
    ) == ("IDENTITY_ROOT", "IDENTITY_PATH", "IDENTITY_CONCAT", "IDENTITY_JS")


def test_v4_shape_preserves_c2a_evidence_chronology(tmp_path: Path) -> None:
    result, _raw, _helpers = _collect_result(tmp_path)

    references, _role_map = repository_module._validate_result_shape(result)  # pyright: ignore[reportPrivateUsage]
    expected_kinds = (
        ("root", "run", "path", "run", "concat", "run", "js", "run")
        + ("catalog",) * 12
        + ("page", "run") * 24
        + ("manifest",)
    )
    assert tuple(reference.kind for reference in references) == expected_kinds
    for previous, current in zip(references, references[1:], strict=False):
        assert current.observed_at >= previous.available_at
        assert current.available_at >= previous.available_at


def _mutate_result(result: Any, **changes: Any) -> Any:
    mutated: Any = object.__new__(cast(type[Any], type(result)))
    for field_name in (
        "exchange",
        "year",
        "run_id",
        "proof",
        "raw_manifest_ref",
        "identity_assets",
        "catalog_refs",
        "attempts",
    ):
        object.__setattr__(mutated, field_name, getattr(result, field_name))
    for field_name, value in changes.items():
        object.__setattr__(mutated, field_name, value)
    return mutated


@pytest.mark.parametrize(
    "attack",
    (
        "missing_identity_path",
        "replacement_identity_path",
        "identity_ordinal_shift",
        "page_at_identity_ordinal",
        "refs_67",
        "refs_68",
        "refs_70",
        "attempts_27",
        "attempts_29",
    ),
)
def test_v4_shape_rejects_identity_and_graph_count_attacks(tmp_path: Path, attack: str) -> None:
    result, _raw, _helpers = _collect_result(tmp_path / attack)
    identity_assets = result.identity_assets
    attempts = result.attempts
    catalog_refs = result.catalog_refs
    if attack == "missing_identity_path":
        identity_assets = (identity_assets[0], identity_assets[2], identity_assets[3])
    elif attack == "replacement_identity_path":
        identity_assets = (
            identity_assets[0],
            identity_assets[2],
            identity_assets[2],
            identity_assets[3],
        )
    elif attack == "identity_ordinal_shift":
        attempts = (attempts[1], attempts[0], *attempts[2:])
    elif attack == "page_at_identity_ordinal":
        attempts = (
            attempts[0],
            attempts[1],
            attempts[2],
            replace(attempts[3], endpoint_kind="page", pass_number=1, month=1),
            *attempts[4:],
        )
    elif attack == "refs_67":
        attempts = (*attempts[:3], replace(attempts[3], state_ref=None), *attempts[4:])
    elif attack == "refs_68":
        attempts = (
            *attempts[:3],
            replace(attempts[3], state_ref=attempts[2].state_ref),
            *attempts[4:],
        )
    elif attack == "refs_70":
        extra = replace(catalog_refs[-1], capture_id="capture-extra-catalog")
        catalog_refs = (*catalog_refs, extra)
    elif attack == "attempts_27":
        attempts = attempts[:-1]
    elif attack == "attempts_29":
        attempts = (*attempts, attempts[-1])
    else:
        raise AssertionError(attack)
    forged = _mutate_result(
        result,
        identity_assets=identity_assets,
        catalog_refs=catalog_refs,
        attempts=attempts,
    )
    with pytest.raises(OfficialCalendarPersistenceError):
        repository_module._validate_result_shape(forged)  # pyright: ignore[reportPrivateUsage]


def test_snapshot_id_is_derived_from_run_id() -> None:
    from uuid import UUID, uuid5

    run_id = UUID("00000000-0000-0000-0000-00000000002a")
    assert official_calendar_snapshot_id(run_id) == uuid5(run_id, "official-calendar-v4:snapshot")


class _RecordingCursor:
    def __init__(self, existing_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.queries: list[str] = []
        self.existing_rows = [] if existing_rows is None else existing_rows
        self.last_query = ""
        self.last_params: tuple[object, ...] | None = None

    def execute(self, query: str, params: object = None) -> None:
        self.last_query = query
        self.last_params = cast(tuple[object, ...] | None, params)
        self.queries.append(query)

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "JOIN official_calendar_snapshots" in self.last_query:
            return self.existing_rows
        return []

    def fetchone(self) -> tuple[Any, ...] | None:
        return None

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *args: object) -> bool:
        del args
        return False


class _RecordingConnection:
    def __init__(self, existing_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.info = type("Info", (), {"transaction_status": TransactionStatus.IDLE})()
        self.recording_cursor = _RecordingCursor(existing_rows)

    def cursor(self) -> _RecordingCursor:
        return self.recording_cursor

    @contextmanager
    def transaction(self, **kwargs: object) -> Generator[None, None, None]:
        del kwargs
        yield None


def _collect_result(tmp_path: Path) -> tuple[Any, Any, Any]:
    helpers = runpy.run_path(str(Path(__file__).with_name("test_official_szse_daily.py")))
    raw = LocalFileStorage(tmp_path / "raw")
    collector = SzseOfficialCalendarCollector(
        raw,
        transport=helpers["_transport"](),
        clock=helpers["_Clock"](),
    )
    with _fixture_identity_pins(helpers):
        result = collector.collect()
    return result, raw, helpers


@contextmanager
def _fixture_identity_pins(helpers: dict[str, Any]) -> Generator[None, None, None]:
    """Use the fixture's explicit identity bytes for collection and replay only."""

    fixture_bodies = {
        "root": helpers["_official_root_body"](),
        "path": helpers["_official_path_body"](),
        "concat": helpers["_official_concatversion_body"](),
        "js": helpers["_official_js_body"](),
    }
    original_pins = official_szse_daily_module._IDENTITY_SOURCE_SHA256  # pyright: ignore[reportPrivateUsage]
    official_szse_daily_module._IDENTITY_SOURCE_SHA256 = {  # pyright: ignore[reportPrivateUsage]
        kind: hashlib.sha256(body).hexdigest() for kind, body in fixture_bodies.items()
    }
    try:
        yield
    finally:
        official_szse_daily_module._IDENTITY_SOURCE_SHA256 = original_pins  # pyright: ignore[reportPrivateUsage]


def _persist_fixture_run(
    repository: PostgresOfficialCalendarRepository,
    raw: Any,
    result: Any,
    helpers: dict[str, Any],
) -> Any:
    with _fixture_identity_pins(helpers):
        return repository.persist_authoritative_szse_run(
            raw,
            result.run_id,
            result.raw_manifest_ref.raw_date,
            result.raw_manifest_ref.capture_id,
        )


class _HydrationCursor(_RecordingCursor):
    def __init__(self, result: Any) -> None:
        super().__init__()
        self.result = result
        self.page_refs = {
            page.raw_evidence_id: result.attempts[
                4 + (page.pass_number - 1) * 12 + page.month - 1
            ].raw_ref
            for page in result.proof.pages
        }

    def fetchall(self) -> list[tuple[Any, ...]]:
        if "SELECT (SELECT count(*)" in self.last_query:
            return [(69, 28, 12, 2, 24, 69, 365)]
        if "SELECT role, count(*)" in self.last_query:
            return [
                ("CATALOG", 12),
                ("IDENTITY_CONCAT", 1),
                ("IDENTITY_JS", 1),
                ("IDENTITY_PATH", 1),
                ("IDENTITY_ROOT", 1),
                ("MANIFEST", 1),
                ("RESPONSE", 24),
                ("STATE", 28),
            ]
        if "SELECT role, source, count(*)" in self.last_query:
            return [
                ("CATALOG", "szse-calendar-catalog", 12),
                ("IDENTITY_CONCAT", "szse-calendar", 1),
                ("IDENTITY_JS", "szse-calendar", 1),
                ("IDENTITY_PATH", "szse-calendar", 1),
                ("IDENTITY_ROOT", "szse-calendar", 1),
                ("MANIFEST", "szse-calendar-manifest", 1),
                ("RESPONSE", "szse-calendar", 24),
                ("STATE", "szse-calendar-state", 28),
            ]
        if "SELECT ordinal, role FROM official_calendar_snapshot_evidence" in self.last_query:
            return [
                (0, "IDENTITY_ROOT"),
                (1, "STATE"),
                (2, "IDENTITY_PATH"),
                (3, "STATE"),
                (4, "IDENTITY_CONCAT"),
                (5, "STATE"),
                (6, "IDENTITY_JS"),
                (7, "STATE"),
                *((ordinal, "CATALOG") for ordinal in range(8, 20)),
                *(
                    (ordinal, "RESPONSE" if (ordinal - 20) % 2 == 0 else "STATE")
                    for ordinal in range(20, 68)
                ),
                (68, "MANIFEST"),
            ]
        if "SELECT a.ordinal, a.attempt_id" in self.last_query:
            rows: list[tuple[Any, ...]] = []
            for ordinal, attempt in enumerate(self.result.attempts, start=1):
                raw = attempt.raw_ref
                state = attempt.state_ref
                assert raw is not None
                assert state is not None
                raw_role = (
                    f"IDENTITY_{attempt.endpoint_kind.upper()}" if ordinal <= 4 else "RESPONSE"
                )
                rows.append(
                    (
                        ordinal,
                        attempt.attempt_id,
                        attempt.capture_id,
                        attempt.endpoint_kind,
                        attempt.pass_number,
                        attempt.month,
                        attempt.status_code,
                        attempt.error_code,
                        attempt.replay_allowed,
                        attempt.observed_at,
                        attempt.available_at,
                        raw.capture_id,
                        raw_role,
                        "szse-calendar",
                        raw.observed_at,
                        raw.available_at,
                        state.capture_id,
                        state.request_identity,
                        "STATE",
                        "szse-calendar-state",
                        state.observed_at,
                        state.available_at,
                    )
                )
            return rows
        if "SELECT count(*)" in self.last_query:
            return [(0,)]
        if "SELECT ordinal, calendar_date, is_trading_day" in self.last_query:
            return [
                (ordinal, day.date, day.is_trading_day)
                for ordinal, day in enumerate(self.result.proof.daily_days)
            ]
        if "FROM official_calendar_run_catalogs" in self.last_query:
            return [
                (
                    catalog.month,
                    catalog.catalog_id,
                    catalog.resource_id,
                    catalog.raw_evidence_id,
                    bytes.fromhex(catalog.raw_artifact_sha256),
                )
                for catalog in self.result.proof.catalog_receipts
            ]
        if "FROM official_calendar_run_passes" in self.last_query:
            return [
                (
                    receipt.pass_number,
                    receipt.pass_id,
                    receipt.opened_at,
                    receipt.finished_at,
                    bytes.fromhex(receipt.member_digest),
                )
                for receipt in self.result.proof.pass_receipts
            ]
        if "FROM official_calendar_run_pages" in self.last_query:
            return [
                (
                    page.pass_number,
                    page.month,
                    page.page_id,
                    page.pass_id,
                    page.catalog_id,
                    page.resource_id,
                    page.raw_evidence_id,
                    bytes.fromhex(page.raw_artifact_sha256),
                    bytes.fromhex(page.canonical_payload_sha256),
                    page.artifact_id,
                    page.capture_id,
                    page.opened_at,
                    page.observed_at,
                    page.available_at,
                    page.source_nowdate,
                )
                for page in self.result.proof.pages
            ]
        return super().fetchall()

    def fetchone(self) -> tuple[Any, ...] | None:
        if "SELECT (SELECT count(*)" in self.last_query:
            return (69, 28, 12, 2, 24, 69, 365)
        if "SELECT count(*)" in self.last_query:
            return (0,)
        if "SELECT authority, exchange, calendar_year, captured_at" in self.last_query:
            proof = self.result.proof
            return (
                proof.authority,
                proof.exchange,
                proof.year,
                proof.opened_at,
                proof.cutoff_at,
                "INDETERMINATE",
                proof.coverage.level.value,
                proof.coverage.confirmed_through,
                None,
            )
        if "SELECT authority, exchange, calendar_year, parser_version" in self.last_query:
            proof = self.result.proof
            manifest = proof.manifest
            coverage = proof.coverage
            return (
                proof.authority,
                proof.exchange,
                proof.year,
                proof.parser_version,
                proof.parser_version,
                proof.contract_version,
                proof.policy_id,
                bytes.fromhex(proof.compiled_catalog_sha256),
                bytes.fromhex(manifest.canonical_member_digest),
                bytes.fromhex(manifest.raw_artifact_sha256),
                bytes.fromhex(proof.proof_digest),
                manifest.raw_evidence_id,
                manifest.artifact_id,
                manifest.capture_id,
                proof.opened_at,
                proof.cutoff_at,
                coverage.source_nowdate,
                coverage.level.value,
                coverage.confirmed_through,
                "CONFIRMED",
            )
        if "FROM official_calendar_evidence_refs WHERE evidence_ref_id" in self.last_query:
            params = self.last_params
            if params is None or not params:
                raise AssertionError("missing evidence reference parameter")
            evidence_id = params[0]
            reference = self.page_refs[UUID(str(evidence_id))]
            assert reference is not None
            return (
                "szse-calendar",
                reference.capture_id,
                date.fromisoformat(reference.raw_date),
                reference.size,
                reference.content_type,
                bytes.fromhex(reference.checksum),
                bytes.fromhex(reference.route_digest),
                reference.request_identity,
                True,
                True,
                reference.observed_at,
                reference.available_at,
            )
        return super().fetchone()


def test_writer_replays_before_opening_database(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _RecordingConnection()
    repository = PostgresOfficialCalendarRepository(connection)  # type: ignore[arg-type]
    called: list[object] = []

    def fail_replay(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        called.append(True)
        raise RuntimeError("replay failed")

    monkeypatch.setattr(repository_module, "replay_szse_daily_run", fail_replay)
    with pytest.raises(OfficialCalendarPersistenceError):
        repository.persist_authoritative_szse_run(
            LocalFileStorage(Path("/private/tmp/unused")), uuid4(), "2026-09-06", "capture"
        )
    assert called == [True]
    assert connection.recording_cursor.queries == []


def test_writer_records_complete_graph_from_fresh_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, raw, _helpers = _collect_result(tmp_path)
    connection = _RecordingConnection()
    repository = PostgresOfficialCalendarRepository(connection)  # type: ignore[arg-type]

    def replay_result(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        return result

    monkeypatch.setattr(repository_module, "replay_szse_daily_run", replay_result)
    outcome = repository.persist_authoritative_szse_run(
        raw,
        result.run_id,
        result.raw_manifest_ref.raw_date,
        result.raw_manifest_ref.capture_id,
    )
    assert outcome.snapshot_id == official_calendar_snapshot_id(result.run_id)
    assert outcome.disposition == "SNAPSHOT_CREATED"
    queries = connection.recording_cursor.queries
    assert sum("INSERT INTO official_calendar_evidence_refs" in query for query in queries) == 69
    assert sum("INSERT INTO official_calendar_capture_attempts" in query for query in queries) == 28
    assert sum("INSERT INTO official_calendar_run_catalogs" in query for query in queries) == 12
    assert sum("INSERT INTO official_calendar_run_passes" in query for query in queries) == 2
    assert sum("INSERT INTO official_calendar_run_pages" in query for query in queries) == 24
    assert (
        sum("INSERT INTO official_calendar_snapshot_evidence" in query for query in queries) == 69
    )
    assert sum("INSERT INTO official_calendar_snapshot_days" in query for query in queries) == 365


def test_same_run_idempotency_returns_existing_without_inserts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, raw, _helpers = _collect_result(tmp_path)
    connection = _RecordingConnection(
        [
            (
                result.run_id,
                bytes.fromhex(result.proof.proof_digest),
                result.proof.manifest.capture_id,
                official_calendar_snapshot_id(result.run_id),
                "CONFIRMED",
                "SNAPSHOT_CREATED",
                "INDETERMINATE",
                "CONFIRMED_HORIZON",
            )
        ]
    )
    repository = PostgresOfficialCalendarRepository(connection)  # type: ignore[arg-type]

    def replay_result(*args: object, **kwargs: object) -> Any:
        del args, kwargs
        return result

    monkeypatch.setattr(repository_module, "replay_szse_daily_run", replay_result)
    outcome = repository.persist_authoritative_szse_run(
        raw,
        result.run_id,
        result.raw_manifest_ref.raw_date,
        result.raw_manifest_ref.capture_id,
    )
    assert outcome.disposition == "DUPLICATE"
    assert not any(query.startswith("INSERT INTO") for query in connection.recording_cursor.queries)


def test_hydration_reconstructs_domain_proof_and_rechecks_digest(tmp_path: Path) -> None:
    result, _raw, _helpers = _collect_result(tmp_path)
    repository = object.__new__(PostgresOfficialCalendarRepository)
    cursor = _HydrationCursor(result)
    snapshot = repository._hydrate_snapshot(  # pyright: ignore[reportPrivateUsage]
        cursor,
        official_calendar_snapshot_id(result.run_id),
        result.run_id,
    )
    assert snapshot.resolution_proof is not None
    assert snapshot.resolution_proof.proof_digest == result.proof.proof_digest
    assert len(snapshot.days) == 365


def _create_worker_base_schema(cursor: Any) -> None:
    cursor.execute(
        """
        CREATE TABLE tasks (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
          attempts INTEGER NOT NULL, max_attempts INTEGER NOT NULL,
          lease_token TEXT, lease_expires_at TIMESTAMPTZ, next_run_at TIMESTAMPTZ,
          last_error_category TEXT, last_error_detail JSONB, dead_letter_detail JSONB,
          created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE checkpoints (
          task_id TEXT PRIMARY KEY, cursor TEXT, state JSONB,
          updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE TABLE quality_events (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, unified_code TEXT,
          date DATE, detail TEXT
        );
        """
    )


@pytest.fixture()
def official_calendar_pg() -> Generator[Any, None, None]:
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg: Any = pytest.importorskip("psycopg")
    try:
        admin = psycopg.connect(dsn)
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    schema = f"official_calendar_v4_{uuid4().hex}"
    connection: Any = None
    try:
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
        connection = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        with connection.transaction(), connection.cursor() as cursor:
            _create_worker_base_schema(cursor)
        apply_data_worker_migrations(connection)
        yield connection
    finally:
        if connection is not None:
            connection.close()
        with admin.transaction(), admin.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def test_v4_migration_applies_and_replays_immutably(official_calendar_pg: Any) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT version, name FROM data_worker_schema_migrations ORDER BY version")
        assert cursor.fetchall() == [
            (1, "precious_metals_migration"),
            (2, "seat_collection_migration"),
            (3, "calendar_snapshot_migration"),
            (4, "official_calendar_migration"),
        ]
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema=current_schema() AND table_name LIKE 'official_calendar_%'"
        )
        assert cursor.fetchone()[0] == 9
    apply_data_worker_migrations(official_calendar_pg)


def test_real_repository_persists_graph_and_resolves_horizon(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    outcome = _persist_fixture_run(repository, raw, result, helpers)
    assert outcome.snapshot_id == official_calendar_snapshot_id(result.run_id)
    assert outcome.run_disposition == "CONFIRMED"
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        for table, expected in (
            ("official_calendar_scan_runs", 1),
            ("official_calendar_evidence_refs", 69),
            ("official_calendar_capture_attempts", 28),
            ("official_calendar_run_catalogs", 12),
            ("official_calendar_run_passes", 2),
            ("official_calendar_run_pages", 24),
            ("official_calendar_snapshots", 1),
            ("official_calendar_snapshot_evidence", 69),
            ("official_calendar_snapshot_days", 365),
        ):
            cursor.execute(f"SELECT count(*) FROM {table}")
            assert cursor.fetchone()[0] == expected
    visible = repository.resolve_szse_direct_daily_as_of(
        date(2026, 9, 4), result.proof.cutoff_at + timedelta(minutes=1)
    )
    assert visible.status.value == "TRADING"
    before_cutoff = repository.resolve_szse_direct_daily_as_of(
        date(2026, 9, 4), result.proof.cutoff_at - timedelta(minutes=1)
    )
    assert before_cutoff.status.value == "INDETERMINATE"
    assert before_cutoff.reason.value == "NO_VISIBLE_OFFICIAL"
    horizon = repository.resolve_szse_direct_daily_as_of(
        date(2026, 12, 31), result.proof.cutoff_at + timedelta(minutes=1)
    )
    assert horizon.status.value == "INDETERMINATE"
    assert horizon.reason.value == "OFFICIAL_HORIZON_UNCONFIRMED"


def test_real_repository_is_idempotent_and_rejects_child_append(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    first = _persist_fixture_run(repository, raw, result, helpers)
    second = _persist_fixture_run(repository, raw, result, helpers)
    assert first.snapshot_id == second.snapshot_id
    assert second.disposition == "DUPLICATE"
    with pytest.raises(OfficialCalendarPersistenceError), _fixture_identity_pins(helpers):
        repository.persist_authoritative_szse_run(
            raw,
            result.run_id,
            "2026-09-05",
            result.raw_manifest_ref.capture_id,
        )
    with (
        pytest.raises(PsycopgError),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT run_id, raw_date, raw_size, content_type, object_sha256, route_sha256, "
            "observed_at, available_at FROM official_calendar_evidence_refs "
            "WHERE run_id=%s LIMIT 1",
            (result.run_id,),
        )
        run, raw_date, raw_size, content_type, object_sha, route_sha, observed, available = (
            cursor.fetchone()
        )
        cursor.execute(
            "INSERT INTO official_calendar_evidence_refs "
            "(evidence_ref_id, run_id, role, source, raw_capture_id, raw_date, raw_size, "
            "content_type, object_sha256, route_sha256, request_identity, "
            "identity_verified, replay_verified, observed_at, available_at) "
            "VALUES (%s, %s, 'RESPONSE', 'szse-calendar', %s, %s, %s, %s, %s, %s, %s, "
            "TRUE, TRUE, %s, %s)",
            (
                uuid4(),
                run,
                f"append-{uuid4().hex}",
                raw_date,
                raw_size,
                content_type,
                object_sha,
                route_sha,
                "GET /szse-calendar/append",
                observed,
                available,
            ),
        )
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM official_calendar_evidence_refs WHERE run_id=%s",
            (result.run_id,),
        )
        assert cursor.fetchone()[0] == 69


def test_real_repository_fails_closed_when_manifest_link_is_missing(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE official_calendar_scan_runs "
            "DROP CONSTRAINT official_calendar_scan_runs_manifest_fkey"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_scan_runs "
            "DISABLE TRIGGER official_calendar_scan_runs_immutable"
        )
        cursor.execute(
            "UPDATE official_calendar_scan_runs SET manifest_raw_evidence_id=%s WHERE run_id=%s",
            (uuid4(), result.run_id),
        )
        cursor.execute(
            "ALTER TABLE official_calendar_scan_runs "
            "ENABLE TRIGGER official_calendar_scan_runs_immutable"
        )
    with pytest.raises(OfficialCalendarPersistenceError):
        repository.resolve_szse_direct_daily_as_of(
            date(2026, 9, 4), result.proof.cutoff_at + timedelta(minutes=1)
        )


def test_real_repository_history_tables_reject_update_delete_and_truncate(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    mutations = (
        "UPDATE official_calendar_scan_runs SET policy_id=policy_id WHERE run_id=%s",
        "UPDATE official_calendar_evidence_refs SET raw_size=raw_size WHERE run_id=%s",
        "UPDATE official_calendar_capture_attempts SET status_code=status_code WHERE run_id=%s",
        "UPDATE official_calendar_run_catalogs SET resource_id=resource_id WHERE run_id=%s",
        "UPDATE official_calendar_run_passes SET member_sha256=member_sha256 WHERE run_id=%s",
        "UPDATE official_calendar_run_pages SET resource_id=resource_id WHERE run_id=%s",
        "UPDATE official_calendar_snapshots SET disposition=disposition WHERE run_id=%s",
        "UPDATE official_calendar_snapshot_evidence SET role=role WHERE run_id=%s",
        "UPDATE official_calendar_snapshot_days SET reason=reason WHERE snapshot_id=%s",
    )
    for statement in mutations:
        parameter = result.run_id
        if "snapshot_days" in statement:
            parameter = official_calendar_snapshot_id(result.run_id)
        with (
            pytest.raises(PsycopgError),
            official_calendar_pg.transaction(),
            official_calendar_pg.cursor() as cursor,
        ):
            cursor.execute(statement, (parameter,))
    for table in (
        "official_calendar_scan_runs",
        "official_calendar_evidence_refs",
        "official_calendar_capture_attempts",
        "official_calendar_run_catalogs",
        "official_calendar_run_passes",
        "official_calendar_run_pages",
        "official_calendar_snapshots",
        "official_calendar_snapshot_evidence",
        "official_calendar_snapshot_days",
    ):
        with (
            pytest.raises(PsycopgError),
            official_calendar_pg.transaction(),
            official_calendar_pg.cursor() as cursor,
        ):
            cursor.execute(f"DELETE FROM {table}")
        with (
            pytest.raises(PsycopgError),
            official_calendar_pg.transaction(),
            official_calendar_pg.cursor() as cursor,
        ):
            cursor.execute(f"TRUNCATE {table}")


def test_real_repository_concurrent_same_run_has_one_winner(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        schema = str(cursor.fetchone()[0])
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    assert dsn

    def persist_once() -> Any:
        connection = psycopg.connect(dsn, options=f'-c search_path="{schema}"')
        try:
            return _persist_fixture_run(
                PostgresOfficialCalendarRepository(connection), raw, result, helpers
            )
        finally:
            connection.close()

    def run_once(_index: int) -> Any:
        del _index
        return persist_once()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(run_once, range(2)))
    assert {outcome.disposition for outcome in outcomes} == {
        "SNAPSHOT_CREATED",
        "DUPLICATE",
    }
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM official_calendar_scan_runs")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM official_calendar_snapshots")
        assert cursor.fetchone()[0] == 1


def test_real_repository_same_cutoff_creates_conflict_head(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    first, first_raw, first_helpers = _collect_result(tmp_path / "first")
    second, second_raw, second_helpers = _collect_result(tmp_path / "second")
    assert first.run_id != second.run_id
    assert first.proof.cutoff_at == second.proof.cutoff_at
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, first_raw, first, first_helpers)
    conflict = _persist_fixture_run(repository, second_raw, second, second_helpers)
    assert conflict.disposition == "CONFLICT_HEAD"
    assert conflict.snapshot_id is None
    assert conflict.run_disposition == "CONFLICT"
    resolved = repository.resolve_szse_direct_daily_as_of(
        date(2026, 9, 4), first.proof.cutoff_at + timedelta(minutes=1)
    )
    assert resolved.status.value == "INDETERMINATE"
    assert resolved.reason.value == "OFFICIAL_CONFLICT"


def test_hydrator_rejects_tampered_capture_attempt_edge(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE official_calendar_capture_attempts "
            "DISABLE TRIGGER official_calendar_capture_attempts_immutable"
        )
        cursor.execute(
            "UPDATE official_calendar_capture_attempts "
            "SET attempt_id='tampered-attempt' "
            "WHERE run_id=%s AND ordinal=1",
            (result.run_id,),
        )
        cursor.execute(
            "ALTER TABLE official_calendar_capture_attempts "
            "ENABLE TRIGGER official_calendar_capture_attempts_immutable"
        )
    with pytest.raises(OfficialCalendarPersistenceError):
        repository.resolve_szse_direct_daily_as_of(
            date(2026, 9, 4), result.proof.cutoff_at + timedelta(minutes=1)
        )


def test_database_rejects_tampered_page_pass_and_catalog_edges(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    with (
        pytest.raises(PsycopgError),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "ALTER TABLE official_calendar_run_pages "
            "DISABLE TRIGGER official_calendar_run_pages_immutable"
        )
        cursor.execute(
            "UPDATE official_calendar_run_pages p "
            "SET pass_id = (SELECT pass_id FROM official_calendar_run_passes "
            "WHERE run_id=p.run_id AND pass_number=2) "
            "WHERE p.run_id=%s AND p.pass_number=1 AND p.month=1",
            (result.run_id,),
        )
    with (
        pytest.raises(PsycopgError),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "ALTER TABLE official_calendar_run_pages "
            "DISABLE TRIGGER official_calendar_run_pages_immutable"
        )
        cursor.execute(
            "UPDATE official_calendar_run_pages p "
            "SET catalog_id = (SELECT catalog_id FROM official_calendar_run_catalogs "
            "WHERE run_id=p.run_id AND month=2) "
            "WHERE p.run_id=%s AND p.pass_number=1 AND p.month=1",
            (result.run_id,),
        )


def test_real_repository_rolls_back_partial_graph(
    tmp_path: Path, official_calendar_pg: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    original_insert_graph = repository._insert_graph  # pyright: ignore[reportPrivateUsage]

    def insert_then_fail(*args: Any, **kwargs: Any) -> Any:
        original_insert_graph(*args, **kwargs)
        raise RuntimeError("intentional test failure")

    monkeypatch.setattr(repository, "_insert_graph", insert_then_fail)
    with pytest.raises(OfficialCalendarPersistenceError):
        _persist_fixture_run(repository, raw, result, helpers)
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM official_calendar_scan_runs")
        assert cursor.fetchone()[0] == 0


def test_verifier_rejects_weakening_v4_constraint(
    official_calendar_pg: Any,
) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE official_calendar_evidence_refs "
            "DROP CONSTRAINT official_calendar_evidence_refs_verification_ck"
        )
    with pytest.raises(ValueError, match="official calendar schema drift"):
        apply_data_worker_migrations(official_calendar_pg)
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT version FROM data_worker_schema_migrations WHERE version=4")
        assert cursor.fetchone()[0] == 4


def test_verifier_rejects_constraint_relocated_to_other_table(
    official_calendar_pg: Any,
) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE official_calendar_evidence_refs "
            "DROP CONSTRAINT official_calendar_evidence_refs_window_ck"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_capture_attempts "
            "ADD CONSTRAINT official_calendar_evidence_refs_window_ck "
            "CHECK (observed_at <= available_at)"
        )
    with pytest.raises(ValueError, match="official calendar schema drift: constraints"):
        apply_data_worker_migrations(official_calendar_pg)


def test_verifier_rejects_dead_branch_immutable_function(
    official_calendar_pg: Any,
) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION official_calendar_history_immutable()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            SET search_path = pg_catalog
            AS $$
            BEGIN
                IF FALSE THEN
                    RAISE EXCEPTION 'official calendar history is immutable';
                END IF;
                RETURN OLD;
            END;
            $$
            """
        )
    with pytest.raises(ValueError, match="official calendar schema drift"):
        apply_data_worker_migrations(official_calendar_pg)


def test_v4_validate_run_ignores_search_path_shadow_tables(official_calendar_pg: Any) -> None:
    shadow_schema = f"official_calendar_shadow_{uuid4().hex}"
    run_id = uuid4()
    manifest_evidence_id = uuid4()
    artifact_id = uuid4()
    capture_id = uuid4()
    opened_at = datetime(2026, 9, 6, tzinfo=UTC)
    cutoff_at = opened_at + timedelta(minutes=1)
    digest = bytes(32)
    shadow_counts = {
        "official_calendar_evidence_refs": 69,
        "official_calendar_capture_attempts": 28,
        "official_calendar_run_catalogs": 12,
        "official_calendar_run_passes": 2,
        "official_calendar_run_pages": 24,
    }
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        canonical_schema = str(cursor.fetchone()[0])
        cursor.execute(f'CREATE SCHEMA "{shadow_schema}"')
        for table, count in shadow_counts.items():
            cursor.execute(f'CREATE TABLE "{shadow_schema}"."{table}" (run_id UUID)')
            cursor.execute(
                f'INSERT INTO "{shadow_schema}"."{table}" (run_id) '
                "SELECT %s FROM generate_series(1, %s)",
                (run_id, count),
            )
        cursor.execute(
            f'CREATE TABLE "{shadow_schema}"."official_calendar_snapshots" (run_id UUID)'
        )
    try:
        with (
            pytest.raises(PsycopgError, match="official calendar run is incomplete"),
            official_calendar_pg.transaction(),
            official_calendar_pg.cursor() as cursor,
        ):
            cursor.execute(
                "ALTER TABLE official_calendar_evidence_refs "
                "DISABLE TRIGGER official_calendar_evidence_refs_append_guard"
            )
            cursor.execute(
                "INSERT INTO official_calendar_scan_runs "
                "(run_id, authority, exchange, calendar_year, parser_version, source_version, "
                "contract_version, policy_id, compiled_catalog_sha256, manifest_member_sha256, "
                "manifest_raw_sha256, proof_sha256, manifest_raw_evidence_id, "
                "manifest_artifact_id, "
                "manifest_capture_id, opened_at, cutoff_at, source_nowdate, coverage_level, "
                "confirmed_through, run_disposition) "
                "VALUES (%s, 'SZSE', 'SZ', 2026, 'szse-direct-daily-v4', 'szse-direct-daily-v4', "
                "'calendar-scan-run-v4', 'szse-direct-daily-v1', %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, '2026-09-06', 'INDETERMINATE', NULL, 'OUT_OF_ORDER')",
                (
                    run_id,
                    digest,
                    digest,
                    digest,
                    digest,
                    manifest_evidence_id,
                    artifact_id,
                    capture_id,
                    opened_at,
                    cutoff_at,
                ),
            )
            cursor.execute(
                "INSERT INTO official_calendar_evidence_refs "
                "(evidence_ref_id, run_id, role, source, raw_capture_id, raw_date, raw_size, "
                "content_type, object_sha256, route_sha256, request_identity, "
                "identity_verified, replay_verified, observed_at, available_at) "
                "VALUES (%s, %s, 'MANIFEST', 'shadow', 'shadow-capture', '2026-09-06', 0, "
                "'text/plain', %s, %s, 'shadow', TRUE, TRUE, %s, %s)",
                (manifest_evidence_id, run_id, digest, digest, opened_at, cutoff_at),
            )
            cursor.execute(
                "ALTER TABLE official_calendar_evidence_refs "
                "ENABLE TRIGGER official_calendar_evidence_refs_append_guard"
            )
            cursor.execute(
                f'SET LOCAL search_path = "{shadow_schema}", "{canonical_schema}", pg_catalog'
            )
            cursor.execute("SET CONSTRAINTS official_calendar_scan_runs_complete IMMEDIATE")
    finally:
        with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA "{shadow_schema}" CASCADE')


def test_verifier_rejects_unsafe_function_search_path(official_calendar_pg: Any) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("ALTER FUNCTION official_calendar_validate_run() SET search_path = public")
    with pytest.raises(ValueError, match="official calendar schema drift: function"):
        apply_data_worker_migrations(official_calendar_pg)


def test_verifier_rejects_wrong_resolution_index(official_calendar_pg: Any) -> None:
    with official_calendar_pg.transaction(), official_calendar_pg.cursor() as cursor:
        cursor.execute("DROP INDEX official_calendar_snapshots_resolution_idx")
        cursor.execute(
            "CREATE INDEX official_calendar_snapshots_resolution_idx "
            "ON official_calendar_snapshots (calendar_year)"
        )
    with pytest.raises(ValueError, match="official calendar schema drift: index"):
        apply_data_worker_migrations(official_calendar_pg)


def test_out_of_order_run_cannot_later_create_snapshot(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    first, first_raw, helpers = _collect_result(tmp_path / "first")
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, first_raw, first, helpers)
    earlier_raw = LocalFileStorage(tmp_path / "earlier" / "raw")
    earlier_clock = helpers["_Clock"]()
    earlier_start = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
    earlier_clock.current = earlier_start
    earlier_random_ms = helpers["_identity_random_ms"](earlier_start + timedelta(minutes=1))
    earlier_path_url = helpers["_LIVE_PATH_URL_TEMPLATE"].format(random_ms=earlier_random_ms)
    earlier_concat_url = helpers["_LIVE_CONCAT_URL_TEMPLATE"].format(random_ms=earlier_random_ms)
    earlier_responses = helpers["_transport"]().responses.copy()
    earlier_responses[earlier_path_url] = earlier_responses[
        helpers["_LIVE_PATH_URL_TEMPLATE"].format(
            random_ms=helpers["_identity_random_ms"](helpers["_CLOCK_START"] + timedelta(minutes=1))
        )
    ]
    earlier_responses[earlier_concat_url] = earlier_responses[
        helpers["_LIVE_CONCAT_URL_TEMPLATE"].format(
            random_ms=helpers["_identity_random_ms"](helpers["_CLOCK_START"] + timedelta(minutes=1))
        )
    ]
    earlier_collector = SzseOfficialCalendarCollector(
        earlier_raw,
        transport=helpers["_FakeTransport"](earlier_responses),
        clock=earlier_clock,
    )
    with _fixture_identity_pins(helpers):
        earlier = earlier_collector.collect()
    blocked = _persist_fixture_run(repository, earlier_raw, earlier, helpers)
    assert blocked.snapshot_id is None
    assert blocked.run_disposition == "OUT_OF_ORDER"
    with pytest.raises(OfficialCalendarPersistenceError):
        repository.resolve_szse_direct_daily_as_of(
            date(2026, 9, 4), earlier.proof.cutoff_at + timedelta(minutes=1)
        )
    with (
        pytest.raises(PsycopgError, match="official calendar run snapshot disposition is invalid"),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT authority, exchange, calendar_year, opened_at, cutoff_at, "
            "coverage_level, confirmed_through FROM official_calendar_scan_runs "
            "WHERE run_id=%s",
            (earlier.run_id,),
        )
        authority, exchange, year, captured, available, coverage, confirmed = cursor.fetchone()
        terminal = "INDETERMINATE"
        cursor.execute(
            "INSERT INTO official_calendar_snapshots "
            "(snapshot_id, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, terminal, coverage_level, confirmed_through, disposition) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'SNAPSHOT_CREATED')",
            (
                official_calendar_snapshot_id(earlier.run_id),
                earlier.run_id,
                authority,
                exchange,
                year,
                captured,
                available,
                terminal,
                coverage,
                confirmed,
            ),
        )


def test_snapshot_validator_rejects_cross_scope_snapshot(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    original_snapshot_id = official_calendar_snapshot_id(result.run_id)
    invalid_snapshot_id = uuid4()
    with (
        pytest.raises(PsycopgError, match="official calendar run snapshot disposition is invalid"),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "ALTER TABLE official_calendar_snapshots "
            "DROP CONSTRAINT official_calendar_snapshots_run_uk"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshots "
            "DISABLE TRIGGER official_calendar_snapshots_append_guard"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshot_evidence "
            "DISABLE TRIGGER official_calendar_snapshot_evidence_append_guard"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshot_days "
            "DISABLE TRIGGER official_calendar_snapshot_days_append_guard"
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshots "
            "(snapshot_id, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, terminal, coverage_level, confirmed_through, "
            "supersedes_snapshot_id, disposition) "
            "SELECT %s, run_id, authority, exchange, 2025, captured_at, available_at, "
            "'INDETERMINATE', 'INDETERMINATE', NULL, NULL, 'SNAPSHOT_CREATED' "
            "FROM official_calendar_snapshots WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshot_evidence "
            "(snapshot_id, run_id, ordinal, evidence_ref_id, role) "
            "SELECT %s, run_id, ordinal, evidence_ref_id, role "
            "FROM official_calendar_snapshot_evidence WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshot_days "
            "(snapshot_id, ordinal, calendar_date, is_trading_day, reason) "
            "SELECT %s, ordinal, (calendar_date - INTERVAL '1 year')::date, "
            "is_trading_day, reason FROM official_calendar_snapshot_days "
            "WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute("SET CONSTRAINTS official_calendar_snapshots_complete IMMEDIATE")


def test_snapshot_validator_rejects_coverage_lineage_mismatch(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    original_snapshot_id = official_calendar_snapshot_id(result.run_id)
    invalid_snapshot_id = uuid4()
    with (
        pytest.raises(PsycopgError, match="official calendar run snapshot disposition is invalid"),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "ALTER TABLE official_calendar_snapshots "
            "DROP CONSTRAINT official_calendar_snapshots_run_uk"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshots "
            "DISABLE TRIGGER official_calendar_snapshots_append_guard"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshot_evidence "
            "DISABLE TRIGGER official_calendar_snapshot_evidence_append_guard"
        )
        cursor.execute(
            "ALTER TABLE official_calendar_snapshot_days "
            "DISABLE TRIGGER official_calendar_snapshot_days_append_guard"
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshots "
            "(snapshot_id, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, terminal, coverage_level, confirmed_through, "
            "supersedes_snapshot_id, disposition) "
            "SELECT %s, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, "
            "CASE WHEN coverage_level = 'FINAL_YEAR' "
            "     THEN 'INDETERMINATE' ELSE 'COMPLETE' END, "
            "CASE WHEN coverage_level = 'FINAL_YEAR' "
            "     THEN 'CONFIRMED_HORIZON' ELSE 'FINAL_YEAR' END, "
            "CASE WHEN coverage_level = 'FINAL_YEAR' "
            "     THEN make_date(calendar_year, 1, 1) "
            "     ELSE make_date(calendar_year, 12, 31) END, "
            "NULL, 'SNAPSHOT_CREATED' "
            "FROM official_calendar_snapshots WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshot_evidence "
            "(snapshot_id, run_id, ordinal, evidence_ref_id, role) "
            "SELECT %s, run_id, ordinal, evidence_ref_id, role "
            "FROM official_calendar_snapshot_evidence WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshot_days "
            "(snapshot_id, ordinal, calendar_date, is_trading_day, reason) "
            "SELECT %s, ordinal, calendar_date, is_trading_day, reason "
            "FROM official_calendar_snapshot_days WHERE snapshot_id=%s",
            (invalid_snapshot_id, original_snapshot_id),
        )
        cursor.execute("SET CONSTRAINTS official_calendar_snapshots_complete IMMEDIATE")


def test_snapshot_table_rejects_audit_only_disposition(
    tmp_path: Path, official_calendar_pg: Any
) -> None:
    result, raw, helpers = _collect_result(tmp_path)
    repository = PostgresOfficialCalendarRepository(official_calendar_pg)
    _persist_fixture_run(repository, raw, result, helpers)
    with (
        pytest.raises(PsycopgError, match="official_calendar_snapshots_disposition_ck"),
        official_calendar_pg.transaction(),
        official_calendar_pg.cursor() as cursor,
    ):
        cursor.execute(
            "ALTER TABLE official_calendar_snapshots "
            "DROP CONSTRAINT official_calendar_snapshots_run_uk"
        )
        cursor.execute(
            "INSERT INTO official_calendar_snapshots "
            "(snapshot_id, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, terminal, coverage_level, confirmed_through, "
            "supersedes_snapshot_id, disposition) "
            "SELECT %s, run_id, authority, exchange, calendar_year, captured_at, "
            "available_at, terminal, coverage_level, confirmed_through, NULL, "
            "'CONFLICT_HEAD' FROM official_calendar_snapshots LIMIT 1",
            (uuid4(),),
        )
