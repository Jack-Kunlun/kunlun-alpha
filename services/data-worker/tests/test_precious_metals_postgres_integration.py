"""Optional live PostgreSQL migration/restart evidence for P1-R07.

The suite is skipped unless ``KUNLUN_TEST_POSTGRES_DSN`` is provided.  It uses
an isolated schema and drops only that schema during teardown.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from data_worker.jobs.precious_metals_funds import normalize_fund_observation
from data_worker.jobs.precious_metals_funds.collector import (
    TrustedFundContext,
    _semantic_key,
    _semantic_value,
)
from data_worker.raw import RawObjectManifest
from data_worker.storage import (
    FundQualityEvent,
    InMemoryFundStorage,
    LeaseContext,
    LeaseFenceError,
    PostgresFundStorage,
    RejectedObservation,
    StorageConflictError,
    apply_precious_metals_migration,
)
from data_worker.storage.precious_metals import controlled_rejection_payload


@pytest.fixture()
def pg_connection():  # type: ignore[no-untyped-def]
    dsn = os.getenv("KUNLUN_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KUNLUN_TEST_POSTGRES_DSN is not configured")
    psycopg = pytest.importorskip("psycopg")
    try:
        connection = psycopg.connect(dsn)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    schema = f"task7_{uuid4().hex}"
    try:
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA "{schema}"')
            cursor.execute(f'SET search_path TO "{schema}"')
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
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE checkpoints (
                  task_id TEXT PRIMARY KEY,
                  cursor TEXT,
                  state JSONB,
                  updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE quality_events (
                  id TEXT PRIMARY KEY,
                  kind TEXT NOT NULL,
                  unified_code TEXT,
                  date DATE,
                  detail TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE providers (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  capabilities TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE data_versions (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  date DATE NOT NULL,
                  checksum TEXT NOT NULL
                )
                """
            )
        yield connection, schema
    finally:
        # The body may leave an aborted or otherwise open transaction (for
        # example after a failed stale-lease assertion).  Roll it back before
        # starting a fresh transaction so teardown always commits its DROP.
        connection.rollback()
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS " + f'"{schema}" CASCADE')
        with psycopg.connect(dsn) as verifier, verifier.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,))
            assert cursor.fetchone() is None, (
                f"isolated test schema was not committed away: {schema}"
            )
        connection.close()


def _nav(
    value: str = "1.250000000001",
    *,
    capture_id: str = "capture-live",
    processing_delta: timedelta = timedelta(0),
):  # type: ignore[no-untyped-def]
    event = datetime(2026, 8, 13, 1, tzinfo=UTC)
    ingest = event + timedelta(hours=2)
    available = event + timedelta(hours=3)
    processing = event + timedelta(hours=4) + processing_delta
    payload_processing = event + timedelta(hours=4)
    checksum = hashlib.sha256(b"{}").hexdigest()
    manifest = RawObjectManifest(
        object_id=checksum,
        source="provider-x",
        date="2026-08-13",
        request="GET /funds/nav?exchange=SH",
        checksum=checksum,
        size=2,
        capture_id=capture_id,
        ingest_time=ingest,
        available_time=available,
        endpoint_kind="nav",
        run_id="run-live",
        source_revision="revision-live",
    )
    context = TrustedFundContext.from_manifest(
        manifest,
        processing_time=processing,
        schema_version="precious-metals-fund-v1",
        normalizer_version="precious-metals-normalizer-v1",
    )
    return normalize_fund_observation(
        "nav",
        {
            "unifiedCode": "518880.SH",
            "date": "2026-08-13",
            "nav": value,
            "eventTime": event.isoformat(),
            "publishTime": (event + timedelta(hours=1)).isoformat(),
            "ingestTime": ingest.isoformat(),
            "availableTime": available.isoformat(),
            "processingTime": payload_processing.isoformat(),
            "source": "provider-x",
        },
        trusted_context=context,
        item_ordinal=0,
    )


def _insert_task(
    cursor,
    now: datetime,
    *,
    task_id: str = "fund-task",
    lease_token: str = "lease-1",
) -> None:  # type: ignore[no-untyped-def]
    cursor.execute(
        """
        INSERT INTO tasks
          (id, kind, status, attempts, max_attempts, lease_token,
           lease_expires_at, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            task_id,
            "precious_metals_funds",
            "RUNNING",
            1,
            3,
            lease_token,
            now + timedelta(minutes=5),
            now,
            now,
        ),
    )


def _safe_checkpoint(kind: str = "nav", *, task_id: str = "fund-task") -> dict[str, object]:
    return {
        "kind": kind,
        "exchange": "SH",
        "date": "2026-08-13",
        "run_id": task_id,
        "source_revision": "rev-1",
        "attempt_id": "attempt-1",
        "committed_page_count": 1,
        "last_capture_id": "capture-live",
        "cursor_lineage_hash": "sha256-" + "0" * 64,
        "complete": True,
    }


def _rejection_for(observation: object) -> RejectedObservation:
    evidence = observation.evidence
    return RejectedObservation(
        record_id=evidence.record_id,
        kind=str(observation.kind),
        payload=controlled_rejection_payload({"invalid": "value"}, digest=evidence.payload_digest),
        reason="normalization_error",
        evidence=evidence,
    )


def _observation(
    kind: str,
    *,
    capture_id: str,
    processing_delta: timedelta = timedelta(0),
) -> object:
    event = datetime(2026, 8, 13, 1, tzinfo=UTC)
    ingest = event + timedelta(hours=2)
    available = event + timedelta(hours=3)
    processing = event + timedelta(hours=4) + processing_delta
    fields: dict[str, object] = {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "eventTime": event.isoformat(),
        "publishTime": (event + timedelta(hours=1)).isoformat(),
        "ingestTime": ingest.isoformat(),
        "availableTime": available.isoformat(),
        "processingTime": processing.isoformat(),
        "source": "provider-x",
    }
    if kind == "metadata":
        fields.pop("date", None)
        fields.update(
            {
                "exchange": "SH",
                "assetType": "ETF",
                "fundAssetClass": "PRECIOUS_METALS",
                "underlyingCommodity": "GOLD",
                "tradingCurrency": "CNY",
                "navCurrency": "CNY",
                "benchmarkOrTrackingIndex": "Au99.99",
                "managementFeeRate": "0.005",
                "validFrom": "2026-01-01",
                "validTo": None,
                "confidence": "0.95",
                "reviewStatus": "REVIEWED",
            }
        )
    elif kind == "nav":
        fields["nav"] = "1.250000000001"
    elif kind == "inav":
        fields["inav"] = "1.260000000001"
    elif kind == "benchmark":
        fields["benchmarkOrTrackingIndex"] = "Au99.99"
    elif kind == "fees":
        fields["managementFeeRate"] = "0.005000000001"
    else:
        raise AssertionError(kind)
    body = json.dumps({"items": [fields], "nextCursor": None}, sort_keys=True).encode()
    checksum = hashlib.sha256(body).hexdigest()
    manifest = RawObjectManifest(
        object_id=checksum,
        source="provider-x",
        date="2026-08-13",
        request=f"GET /funds/{kind}?exchange=SH",
        checksum=checksum,
        size=len(body),
        capture_id=capture_id,
        ingest_time=ingest,
        available_time=available,
        endpoint_kind=kind,
        run_id="run-1",
        source_revision="rev-1",
    )
    context = TrustedFundContext.from_manifest(
        manifest,
        processing_time=processing,
        schema_version="precious-metals-fund-v1",
        normalizer_version="precious-metals-normalizer-v1",
    )
    return normalize_fund_observation(kind, fields, trusted_context=context, item_ordinal=0)


def test_checkpoint_plaintext_cursor_is_rejected_before_inmemory_mutation() -> None:
    storage = InMemoryFundStorage()
    with pytest.raises(ValueError, match="remote cursor"):
        storage.commit_page(
            accepted=(),
            rejected=(),
            quality_events=(),
            checkpoint={"next_cursor": "secret-cursor"},
        )
    assert storage.observations() == []
    assert storage.get_checkpoint("default") is None


@pytest.mark.parametrize("field", ["next_cursor", "consumed_cursors"])
def test_checkpoint_plaintext_cursor_is_rejected_before_postgres_mutation(
    pg_connection, field: str
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    checkpoint = {field: ["secret-cursor"] if field == "consumed_cursors" else "secret-cursor"}
    with pytest.raises(ValueError, match="remote cursor"):
        adapter.commit_page(
            accepted=(),
            rejected=(),
            quality_events=(),
            checkpoint=checkpoint,
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM checkpoints")
        assert cursor.fetchone()[0] == 0


def test_postgres_stored_semantics_match_inmemory_for_all_five_kinds(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    in_memory = InMemoryFundStorage()
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    observations = tuple(
        _observation(kind, capture_id=f"capture-{kind}")
        for kind in ("metadata", "nav", "inav", "benchmark", "fees")
    )
    for observation in observations:
        in_memory.commit_page(
            accepted=(observation,), rejected=(), quality_events=(), checkpoint=_safe_checkpoint()
        )
        adapter.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(),
            checkpoint=_safe_checkpoint(task_id="fund-task"),
            context=context,
        )
    stored = {item.kind: item for item in adapter.observations()}
    for kind in ("metadata", "nav", "inav", "benchmark", "fees"):
        expected = next(item for item in observations if item.kind == kind)
        actual = stored[kind]
        assert _semantic_key(actual) == _semantic_key(expected)
        assert _semantic_value(actual) == _semantic_value(expected)
    metadata = stored["metadata"]
    assert metadata.observation_id == _logical_id(observations[0])


def _logical_id(observation: object) -> str:
    from data_worker.storage.precious_metals import _logical_observation_id

    return _logical_observation_id(observation)


def test_postgres_same_evidence_cannot_switch_between_accepted_and_rejected(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    accepted = _nav()
    adapter.commit_page(
        accepted=(accepted,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(),
            rejected=(_rejection_for(accepted),),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_rejections")
        assert cursor.fetchone()[0] == 0


def test_inmemory_same_evidence_cannot_switch_between_accepted_and_rejected() -> None:
    storage = InMemoryFundStorage()
    accepted = _nav()
    storage.commit_page(
        accepted=(accepted,), rejected=(), quality_events=(), checkpoint=_safe_checkpoint()
    )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(),
            rejected=(_rejection_for(accepted),),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        )


def test_postgres_same_evidence_cannot_switch_from_rejected_to_accepted(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    rejected = _nav()
    adapter.commit_page(
        accepted=(),
        rejected=(_rejection_for(rejected),),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(rejected,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM fund_rejections")
        assert cursor.fetchone()[0] == 1


def test_inmemory_same_evidence_cannot_switch_from_rejected_to_accepted() -> None:
    storage = InMemoryFundStorage()
    rejected = _nav()
    storage.commit_page(
        accepted=(),
        rejected=(_rejection_for(rejected),),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
    )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(rejected,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        )
    assert storage.observations() == []
    assert len(storage.rejections()) == 1


def test_postgres_same_evidence_has_one_accepted_logical_claim(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    first = _nav()
    second = replace(
        first,
        value=replace(first.value, nav=Decimal("1.260000000001")),
        payload={**first.payload, "nav": "1.260000000001"},
    )
    adapter.commit_page(
        accepted=(first,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(second,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_logical_observations")
        assert cursor.fetchone()[0] == 1


def test_inmemory_same_evidence_has_one_accepted_logical_claim() -> None:
    storage = InMemoryFundStorage()
    first = _nav()
    second = replace(
        first,
        value=replace(first.value, nav=Decimal("1.260000000001")),
        payload={**first.payload, "nav": "1.260000000001"},
    )
    storage.commit_page(
        accepted=(first,), rejected=(), quality_events=(), checkpoint=_safe_checkpoint()
    )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(second,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        )


def test_postgres_same_evidence_cannot_claim_a_second_accepted_kind(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    first = _nav()
    second = _observation("inav", capture_id="capture-cross-kind")
    second = replace(second, evidence=first.evidence)
    adapter.commit_page(
        accepted=(first,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(second,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_logical_observations")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM fund_inav_observations")
        assert cursor.fetchone()[0] == 0


def test_inmemory_same_evidence_cannot_claim_a_second_accepted_kind() -> None:
    storage = InMemoryFundStorage()
    first = _nav()
    second = replace(_observation("inav", capture_id="capture-cross-kind"), evidence=first.evidence)
    storage.commit_page(
        accepted=(first,), rejected=(), quality_events=(), checkpoint=_safe_checkpoint()
    )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(second,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        )
    assert len(storage.observations()) == 1


def test_quality_detail_is_value_free_and_event_fields_are_immutable_inmemory() -> None:
    storage = InMemoryFundStorage()
    observation = _nav()
    secret = "Bearer quality-secret DSN=postgresql://user:secret@db Cookie=token"
    first = FundQualityEvent(
        event_id="quality-audit",
        kind="SOURCE_CONFLICT",
        semantic_key="nav:518880.SH:2026-08-13",
        detail=secret,
        evidence_ids=(observation.evidence.record_id,),
        created_at=datetime(2026, 8, 13, 4, tzinfo=UTC),
    )
    storage.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(first,),
        checkpoint=_safe_checkpoint(),
    )
    assert secret not in storage.quality_events()[0].detail
    replay = replace(first, created_at=first.created_at + timedelta(hours=1))
    storage.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(replay,),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
    )
    changed_links = replace(first, evidence_ids=())
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(changed_links,),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 3},
        )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(replace(first, detail="changed detail"),),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 4},
        )
    empty_first = replace(first, event_id="quality-empty", evidence_ids=())
    storage.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(empty_first,),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 5},
    )
    with pytest.raises(StorageConflictError):
        storage.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(replace(empty_first, evidence_ids=(observation.evidence.record_id,)),),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 6},
        )


def test_quality_detail_and_links_are_immutable_postgres(pg_connection) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    observation = _nav()
    first = FundQualityEvent(
        event_id="quality-audit",
        kind="SOURCE_CONFLICT",
        semantic_key="nav:518880.SH:2026-08-13",
        detail="Bearer quality-secret DSN=postgresql://user:secret@db Cookie=token",
        evidence_ids=(observation.evidence.record_id,),
        created_at=now,
    )
    adapter.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(first,),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    assert "quality-secret" not in adapter.quality_events()[0].detail
    replay = replace(first, created_at=now + timedelta(hours=1))
    adapter.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(replay,),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(replace(first, evidence_ids=()),),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 3},
            context=context,
        )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(replace(first, detail="changed detail"),),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 4},
            context=context,
        )
    empty_first = replace(first, event_id="quality-empty", evidence_ids=())
    adapter.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(empty_first,),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 5},
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(replace(empty_first, evidence_ids=(observation.evidence.record_id,)),),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 6},
            context=context,
        )


def test_same_logical_observation_different_capture_and_processing_is_idempotent(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    first = _nav(capture_id="capture-a")
    second = _nav(capture_id="capture-b", processing_delta=timedelta(hours=1))
    adapter.commit_page(
        accepted=(first,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    adapter.commit_page(
        accepted=(second,),
        rejected=(),
        quality_events=(),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        context=context,
    )
    assert len(adapter.observations("nav")) == 1
    assert len(adapter.evidence()) == 2


def test_evidence_processing_time_is_first_write_wins_for_same_identity_postgres(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    first = _nav(capture_id="capture-same")
    replay = _nav(capture_id="capture-same", processing_delta=timedelta(hours=1))
    adapter.commit_page(
        accepted=(first,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    adapter.commit_page(
        accepted=(replay,),
        rejected=(),
        quality_events=(),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
        context=context,
    )
    assert adapter.evidence()[0].processing_time == first.evidence.processing_time


def test_evidence_processing_time_is_first_write_wins_for_same_identity_inmemory() -> None:
    storage = InMemoryFundStorage()
    first = _nav(capture_id="capture-same")
    replay = _nav(capture_id="capture-same", processing_delta=timedelta(hours=1))
    storage.commit_page(
        accepted=(first,), rejected=(), quality_events=(), checkpoint=_safe_checkpoint()
    )
    storage.commit_page(
        accepted=(replay,),
        rejected=(),
        quality_events=(),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
    )
    assert storage.evidence()[0].processing_time == first.evidence.processing_time


def test_inmemory_rejection_processing_time_is_first_write_wins_and_content_is_exact() -> None:
    storage = InMemoryFundStorage()
    observation = _nav(capture_id="capture-rejection-replay")
    first = _rejection_for(observation)
    assert first.evidence.processing_time is not None
    replay = replace(
        first,
        evidence=replace(
            first.evidence,
            processing_time=first.evidence.processing_time + timedelta(seconds=1),
        ),
    )
    storage.commit_page(
        accepted=(), rejected=(first,), quality_events=(), checkpoint=_safe_checkpoint()
    )
    storage.commit_page(
        accepted=(),
        rejected=(replay,),
        quality_events=(),
        checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
    )
    assert len(storage.rejections()) == 1
    assert len(storage.evidence()) == 1
    assert storage.rejections()[0].evidence.processing_time == first.evidence.processing_time
    assert storage.evidence()[0].processing_time == first.evidence.processing_time

    changed_reason = replace(first, reason="item_not_mapping")
    changed_payload_evidence = replace(
        first.evidence,
        payload_digest="c" * 64,
    )
    changed_payload = replace(
        first,
        evidence=changed_payload_evidence,
        payload={"item_digest": "c" * 64, "field_names": ["changed"]},
    )
    changed_evidence = replace(
        first,
        evidence=replace(
            first.evidence,
            raw_object_id=hashlib.sha256(b"changed rejection object").hexdigest(),
        ),
    )
    for changed in (changed_reason, changed_payload, changed_evidence):
        with pytest.raises(StorageConflictError):
            storage.commit_page(
                accepted=(),
                rejected=(changed,),
                quality_events=(),
                checkpoint={**_safe_checkpoint(), "committed_page_count": 3},
            )
        assert len(storage.rejections()) == 1
        assert len(storage.evidence()) == 1
        assert storage.get_checkpoint("default")["committed_page_count"] == 2


def test_live_concurrent_same_evidence_changed_content_fails_closed(pg_connection) -> None:  # type: ignore[no-untyped-def]
    """Two independent lease owners must not bypass exact evidence CAS."""

    connection, schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
        _insert_task(cursor, now, task_id="fund-task-2", lease_token="lease-2")
        # Hold both pre-insert SELECTs open long enough for the two transactions
        # to overlap.  The legacy SELECT + ON CONFLICT DO NOTHING path then
        # silently accepts one changed payload instead of raising a conflict.
        cursor.execute(
            """
            CREATE FUNCTION task7_pause_evidence_insert() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              PERFORM pg_sleep(0.5);
              RETURN NEW;
            END;
            $$
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER task7_pause_evidence
            BEFORE INSERT ON fund_observation_evidence
            FOR EACH ROW EXECUTE FUNCTION task7_pause_evidence_insert()
            """
        )

    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["KUNLUN_TEST_POSTGRES_DSN"]
    second_connection = psycopg.connect(dsn)
    try:
        with second_connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        second_connection.commit()
        first = PostgresFundStorage(connection)
        second = PostgresFundStorage(second_connection)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def commit(storage: PostgresFundStorage, value: str, task_id: str, token: str) -> None:
            observation = _nav(value)
            context = LeaseContext(task_id, token, now + timedelta(minutes=5))
            barrier.wait()
            try:
                storage.commit_page(
                    accepted=(observation,),
                    rejected=(),
                    quality_events=(),
                    checkpoint={
                        "kind": "nav",
                        "exchange": "SH",
                        "date": "2026-08-13",
                        "run_id": task_id,
                        "source_revision": "rev-1",
                        "committed_page_count": 1,
                        "last_capture_id": observation.evidence.raw_capture_id,
                        "cursor_lineage_hash": "sha256-" + "0" * 64,
                        "complete": True,
                    },
                    context=context,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=commit, args=(first, "1.250000000001", "fund-task", "lease-1")),
            threading.Thread(
                target=commit,
                args=(second, "1.260000000001", "fund-task-2", "lease-2"),
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)

        assert len(errors) == 1
        assert isinstance(errors[0], StorageConflictError)
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fund_observation_evidence")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
            assert cursor.fetchone()[0] == 1
    finally:
        second_connection.close()


def test_live_concurrent_same_evidence_equal_content_is_idempotent(pg_connection) -> None:  # type: ignore[no-untyped-def]
    """Equal concurrent retries are no-ops rather than false conflicts."""

    connection, schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now, task_id="fund-task-a", lease_token="lease-a")
        _insert_task(cursor, now, task_id="fund-task-b", lease_token="lease-b")
        cursor.execute(
            """
            CREATE FUNCTION task7_pause_equal_evidence_insert() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              PERFORM pg_sleep(0.5);
              RETURN NEW;
            END;
            $$
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER task7_pause_equal_evidence
            BEFORE INSERT ON fund_observation_evidence
            FOR EACH ROW EXECUTE FUNCTION task7_pause_equal_evidence_insert()
            """
        )

    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["KUNLUN_TEST_POSTGRES_DSN"]
    second_connection = psycopg.connect(dsn)
    try:
        with second_connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        second_connection.commit()
        first = PostgresFundStorage(connection)
        second = PostgresFundStorage(second_connection)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def commit(storage: PostgresFundStorage, task_id: str, token: str) -> None:
            observation = _nav("1.250000000001")
            context = LeaseContext(task_id, token, now + timedelta(minutes=5))
            barrier.wait()
            try:
                storage.commit_page(
                    accepted=(observation,),
                    rejected=(),
                    quality_events=(),
                    checkpoint={
                        "kind": "nav",
                        "exchange": "SH",
                        "date": "2026-08-13",
                        "run_id": task_id,
                        "source_revision": "rev-1",
                        "committed_page_count": 1,
                        "last_capture_id": observation.evidence.raw_capture_id,
                        "cursor_lineage_hash": "sha256-" + "0" * 64,
                        "complete": True,
                    },
                    context=context,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=commit, args=(first, "fund-task-a", "lease-a")),
            threading.Thread(target=commit, args=(second, "fund-task-b", "lease-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)
        assert errors == [], errors
        with connection.transaction(), connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fund_observation_evidence")
            assert cursor.fetchone()[0] == 1
            cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
            assert cursor.fetchone()[0] == 1
    finally:
        second_connection.close()


def test_live_migration_numeric_evidence_restart_and_stale_fence(pg_connection) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    observation = _nav()
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    adapter.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT value FROM fund_nav_observations")
        assert cursor.fetchone()[0] == Decimal("1.250000000001")
        cursor.execute(
            """
            SELECT e.raw_capture_id
              FROM fund_nav_observations n
              JOIN fund_observation_evidence e ON e.record_id = n.evidence_id
            """
        )
        assert cursor.fetchone()[0] == "capture-live"

    psycopg = pytest.importorskip("psycopg")
    reopened = psycopg.connect(os.environ["KUNLUN_TEST_POSTGRES_DSN"])
    with reopened.transaction(), reopened.cursor() as cursor:
        cursor.execute(f'SET search_path TO "{_schema}"')
        cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
        assert cursor.fetchone()[0] == 1
    adapter_reopened = PostgresFundStorage(reopened)
    adapter_reopened.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with reopened.transaction(), reopened.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "UPDATE tasks SET lease_token = %s, "
            "lease_expires_at = CURRENT_TIMESTAMP + INTERVAL '5 minutes' "
            "WHERE id = %s",
            ("lease-2", "fund-task"),
        )
    with pytest.raises(LeaseFenceError):
        adapter_reopened.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(),
            checkpoint=_safe_checkpoint(),
            context=context,
        )
    with reopened.transaction(), reopened.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
        assert cursor.fetchone()[0] == 1
    reopened.close()


def test_live_postgres_changed_same_evidence_rolls_back_page_and_checkpoint(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    original = _nav()
    changed = _nav("1.260000000001")
    adapter.commit_page(
        accepted=(original,),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )

    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(changed,),
            rejected=(),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )

    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_nav_observations")
        assert cursor.fetchone()[0] == 1
    assert "next_cursor" not in adapter.get_checkpoint("fund-task")


def test_live_postgres_reads_return_typed_domain_and_evidence(pg_connection) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    adapter.commit_page(
        accepted=(_nav(),),
        rejected=(),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )

    rows = adapter.observations("nav")
    assert len(rows) == 1
    assert getattr(rows[0], "kind", None) == "nav"
    assert getattr(getattr(rows[0], "evidence", None), "raw_capture_id", None) == "capture-live"


def test_live_postgres_changed_rejection_rolls_back_page_and_checkpoint(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    evidence = _nav().evidence
    original = RejectedObservation(
        record_id=evidence.record_id,
        kind="nav",
        payload={"nav": "-1"},
        reason="negative nav",
        evidence=evidence,
    )
    changed_evidence = replace(
        evidence,
        raw_object_id=hashlib.sha256(b"changed rejection raw object").hexdigest(),
        checksum=hashlib.sha256(b"changed rejection raw object").hexdigest(),
        payload_digest=hashlib.sha256(b"changed rejection raw item").hexdigest(),
    )
    changed = RejectedObservation(
        record_id=changed_evidence.record_id,
        kind="nav",
        payload={"nav": "-2"},
        reason="different negative nav",
        evidence=changed_evidence,
    )
    adapter.commit_page(
        accepted=(),
        rejected=(original,),
        quality_events=(),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(),
            rejected=(changed,),
            quality_events=(),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM fund_rejections")
        assert cursor.fetchone()[0] == 1
    assert "next_cursor" not in adapter.get_checkpoint("fund-task")


def test_live_postgres_changed_quality_event_or_link_rolls_back_page(
    pg_connection,
) -> None:  # type: ignore[no-untyped-def]
    connection, _schema = pg_connection
    apply_precious_metals_migration(connection)
    now = datetime.now(UTC)
    with connection.transaction(), connection.cursor() as cursor:
        _insert_task(cursor, now)
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-1", now + timedelta(minutes=5))
    observation = _nav()
    first = FundQualityEvent(
        event_id="fund-quality-conflict",
        kind="SOURCE_CONFLICT",
        semantic_key="nav:518880.SH:2026-08-13",
        detail="first detail",
        evidence_ids=(observation.evidence.record_id,),
        created_at=now,
    )
    changed = FundQualityEvent(
        event_id=first.event_id,
        kind=first.kind,
        semantic_key=first.semantic_key,
        detail="changed detail",
        evidence_ids=first.evidence_ids,
        created_at=now,
    )
    adapter.commit_page(
        accepted=(observation,),
        rejected=(),
        quality_events=(first,),
        checkpoint=_safe_checkpoint(),
        context=context,
    )
    with pytest.raises(StorageConflictError):
        adapter.commit_page(
            accepted=(observation,),
            rejected=(),
            quality_events=(changed,),
            checkpoint={**_safe_checkpoint(), "committed_page_count": 2},
            context=context,
        )
    assert "next_cursor" not in adapter.get_checkpoint("fund-task")
