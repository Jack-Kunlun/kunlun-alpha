"""Behavior RED tests for transactional PostgreSQL fund persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from data_worker.storage.precious_metals import (
    EvidenceEnvelope,
    LeaseContext,
    PostgresFundStorage,
    RejectedObservation,
    controlled_rejection,
)


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []
        self._row: tuple[object, ...] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, params: tuple[object, ...] | None = None) -> None:
        self.calls.append((statement, params))
        self._row = None
        if "SELECT lease_token" in statement:
            self._row = (self.connection.lease_token, self.connection.lease_expires_at)
        elif "RETURNING" in statement and params:
            self._row = (params[0],)

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _Transaction:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> _Transaction:
        self.connection.in_transaction = True
        return self

    def __exit__(self, exc_type: object, *_args: object) -> None:
        self.connection.rolled_back = exc_type is not None
        self.connection.committed = exc_type is None
        self.connection.in_transaction = False


class FakeConnection:
    def __init__(self) -> None:
        self.lease_token = "lease-token"
        self.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        self.cursors: list[FakeCursor] = []
        self.in_transaction = False
        self.committed = False
        self.rolled_back = False

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor(self)
        self.cursors.append(cursor)
        return cursor


def _evidence() -> EvidenceEnvelope:
    return EvidenceEnvelope(
        raw_capture_id="capture-redaction",
        raw_object_id="a" * 64,
        checksum="a" * 64,
        source="provider-x",
        source_revision=None,
        schema_version="schema-v1",
        normalizer_version="normalizer-v1",
        payload_digest="b" * 64,
        item_ordinal=0,
        ingest_time=datetime.now(UTC),
        available_time=datetime.now(UTC),
    )


def test_postgres_rejection_payload_redacts_credentials_before_sql() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(connection)
    evidence = _evidence()
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="nav",
        payload={"apiKey": "top-secret", "token": "session-secret", "nav": "-1"},
        reason="nav must be >= 0",
        evidence=evidence,
    )
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    adapter.commit_page(
        accepted=(),
        rejected=(rejected,),
        quality_events=(),
        checkpoint={},
        context=context,
    )

    statements = [
        json.dumps(params, default=str)
        for cursor in connection.cursors
        for statement, params in cursor.calls
        if "fund_rejections" in statement
    ]
    assert all("top-secret" not in statement for statement in statements)
    assert all("session-secret" not in statement for statement in statements)
    assert all("apiKey" not in statement for statement in statements)
    assert all("token" not in statement for statement in statements)


def test_postgres_lease_query_is_database_time_fenced() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(connection)
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    adapter.commit_page(
        accepted=(),
        rejected=(),
        quality_events=(),
        checkpoint={},
        context=context,
    )

    lease_query = next(
        statement
        for cursor in connection.cursors
        for statement, _ in cursor.calls
        if "SELECT lease_token" in statement
    )
    assert "CURRENT_TIMESTAMP" in lease_query


def test_postgres_rejection_non_mapping_payload_does_not_persist_raw_text() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(connection)
    evidence = _evidence()
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="nav",
        payload=cast(dict[str, object], "Bearer super-secret-dsn-cookie"),
        reason="invalid provider payload",
        evidence=evidence,
    )
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    adapter.commit_page(
        accepted=(),
        rejected=(rejected,),
        quality_events=(),
        checkpoint={},
        context=context,
    )

    statements = [
        json.dumps(params, default=str)
        for cursor in connection.cursors
        for _, params in cursor.calls
    ]
    assert all("Bearer super-secret-dsn-cookie" not in statement for statement in statements)


def test_postgres_rejection_boundary_drops_nested_values_and_exception_text() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(cast(Any, connection))
    evidence = _evidence()
    dsn_secret = "task2-postgres-userinfo-secret"
    bearer_secret = "task2-bearer-secret"
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="metadata",
        payload=cast(
            dict[str, object],
            {
                "details": {
                    "Authorization": f"Bearer {bearer_secret}",
                    "dsn": f"postgresql://collector:{dsn_secret}@db.example.test/funds",
                    "CookieHeader": "task2-cookie-secret",
                }
            },
        ),
        reason=f"validation input leaked {dsn_secret}",
        evidence=evidence,
    )
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    adapter.commit_page(
        accepted=(),
        rejected=(rejected,),
        quality_events=(),
        checkpoint={},
        context=context,
    )

    statements = [
        json.dumps(params, default=str)
        for cursor in connection.cursors
        for _, params in cursor.calls
    ]
    serialized = "\n".join(statements)
    for secret in (dsn_secret, bearer_secret, "task2-cookie-secret"):
        assert secret not in serialized
    assert "validation input leaked" not in serialized


def test_postgres_rejection_uses_evidence_digest_for_canonical_looking_payload() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(cast(Any, connection))
    evidence = _evidence()
    forged_digest = "e" * 64
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="metadata",
        payload={"item_digest": forged_digest, "field_names": ["validFrom", "T" * 64]},
        reason="normalization_error",
        evidence=evidence,
    )

    normalized_once = controlled_rejection(rejected)
    normalized_twice = controlled_rejection(normalized_once)
    assert normalized_once == normalized_twice
    assert normalized_once.payload["item_digest"] == evidence.payload_digest
    assert normalized_once.payload["field_names"] == []
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    adapter.commit_page(
        accepted=(),
        rejected=(rejected,),
        quality_events=(),
        checkpoint={},
        context=context,
    )

    statements = [
        json.dumps(params, default=str)
        for cursor in connection.cursors
        for statement, params in cursor.calls
        if "fund_rejections" in statement
    ]
    serialized = "\n".join(statements)
    assert forged_digest not in serialized
    assert "T" * 64 not in serialized
    assert evidence.payload_digest in serialized


def test_postgres_rejection_invalid_evidence_digest_fails_closed() -> None:
    connection = FakeConnection()
    adapter = PostgresFundStorage(cast(Any, connection))
    evidence = _evidence()
    object.__setattr__(evidence, "payload_digest", "Bearer test-value")
    rejected = RejectedObservation(
        record_id=evidence.record_id,
        kind="metadata",
        payload={"item_digest": "f" * 64, "field_names": []},
        reason="normalization_error",
        evidence=evidence,
    )
    context = LeaseContext("fund-task", "lease-token", connection.lease_expires_at)

    with pytest.raises(ValueError, match="payload_digest"):
        adapter.commit_page(
            accepted=(),
            rejected=(rejected,),
            quality_events=(),
            checkpoint={},
            context=context,
        )
    statements = [
        json.dumps(params, default=str)
        for cursor in connection.cursors
        for _, params in cursor.calls
    ]
    assert all("Bearer test-value" not in statement for statement in statements)
