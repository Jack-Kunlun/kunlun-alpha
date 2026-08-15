"""Compose PostgreSQL contract tests for the durable scheduler store."""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import LiteralString, cast
from uuid import uuid4

import psycopg
import pytest
from data_worker.scheduler import BackoffPolicy, TaskScheduler, TransientError
from data_worker.scheduler.postgres_store import PostgresTaskStore

POSTGRES_DSN = os.environ.get("KUNLUN_TEST_POSTGRES_DSN")


@pytest.fixture()
def postgres_store() -> Generator[tuple[PostgresTaskStore, str], None, None]:
    if not POSTGRES_DSN:
        pytest.skip("set KUNLUN_TEST_POSTGRES_DSN to run PostgreSQL integration tests")

    schema = f"task_test_{uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(_sql(f'CREATE SCHEMA "{schema}"'))
        connection.execute(_sql(f'SET search_path TO "{schema}"'))
        connection.execute(
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
            """,
        )
        connection.execute(
            """
            CREATE TABLE checkpoints (
              task_id TEXT PRIMARY KEY,
              state JSONB,
              updated_at TIMESTAMPTZ NOT NULL
            )
            """,
        )

    store = PostgresTaskStore(POSTGRES_DSN, schema=schema)
    try:
        yield store, schema
    finally:
        store.close()
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as cleanup:
            cleanup.execute(_sql(f'DROP SCHEMA "{schema}" CASCADE'))


def test_state_survives_store_reopen(postgres_store: tuple[PostgresTaskStore, str]) -> None:
    store, schema = postgres_store
    token = store.acquire_lease("restart-task", lease_seconds=30)
    assert token is not None
    assert store.save_checkpoint("restart-task", token, {"cursor": "page-2"})
    next_run = datetime.now(UTC) + timedelta(seconds=10)
    assert store.mark_failed(
        "restart-task",
        token,
        error_category="transient",
        error_detail={"code": "timeout"},
        next_run_at=next_run,
    )
    store.close()

    reopened = PostgresTaskStore(POSTGRES_DSN or "", schema=schema)
    try:
        record = reopened.get("restart-task")
        assert record.status == "FAILED"
        assert record.attempts == 1
        assert record.error_category == "transient"
        assert record.error_detail == {"code": "timeout"}
        assert record.next_run_at is not None and record.next_run_at.tzinfo is not None
        assert reopened.get_checkpoint("restart-task") == {"cursor": "page-2"}
    finally:
        reopened.close()


def test_concurrent_acquisition_has_one_winner(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    _, schema = postgres_store
    barrier = Barrier(2)

    def acquire() -> str | None:
        barrier.wait(timeout=10)
        contender = PostgresTaskStore(POSTGRES_DSN or "", schema=schema)
        try:
            return contender.acquire_lease("race-task", lease_seconds=30)
        finally:
            contender.close()

    def acquire_ignored(_index: int) -> str | None:
        return acquire()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tokens = list(executor.map(acquire_ignored, [0, 1]))
    assert [token for token in tokens if token is not None].__len__() == 1


def test_expired_lease_takeover_fences_stale_owner(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    store, _ = postgres_store
    old_token = store.acquire_lease("takeover-task", lease_seconds=0.2)
    assert old_token is not None
    time.sleep(0.5)

    assert store.release_lease("takeover-task", old_token) is False
    assert store.mark_succeeded("takeover-task", old_token) is False
    assert store.mark_failed("takeover-task", old_token) is False
    assert store.mark_dead("takeover-task", old_token) is False
    assert store.save_checkpoint("takeover-task", old_token, {"cursor": "stale"}) is False

    new_token = store.acquire_lease("takeover-task", lease_seconds=30)
    assert new_token is not None and new_token != old_token

    assert store.mark_succeeded("takeover-task", new_token) is True


def test_acquire_creates_missing_task_atomically(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    store, _ = postgres_store
    token = store.acquire_lease("implicit-task", lease_seconds=30)

    assert token is not None
    record = store.get("implicit-task")
    assert record.status == "RUNNING"
    assert record.lease_token == token


def test_next_run_and_dead_letter_details_round_trip(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    store, _ = postgres_store
    token = store.acquire_lease("dead-task", lease_seconds=30)
    assert token is not None
    assert store.mark_dead(
        "dead-task",
        token,
        error_category="permanent",
        error_detail={"reason": "invalid_payload"},
        dead_letter_detail={"provider": "fixture"},
    )
    record = store.get("dead-task")
    assert record.status == "DEAD"
    assert record.dead_letter_detail == {"provider": "fixture"}
    assert record.updated_at.tzinfo is not None


def test_postgres_store_rejects_sensitive_error_payloads(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    store, _ = postgres_store
    token = store.acquire_lease("sensitive-payload-task", lease_seconds=30)
    assert token is not None

    with pytest.raises(ValueError, match="sensitive"):
        store.save_checkpoint("sensitive-payload-task", token, {"apiKey": "secret"})
    with pytest.raises(ValueError, match="sensitive"):
        store.mark_failed(
            "sensitive-payload-task",
            token,
            error_detail="Authorization: Bearer abc",
        )


def test_postgres_store_rejects_unknown_or_sensitive_error_categories(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    store, _ = postgres_store
    categories = ("unknown", "Authorization: Bearer abc", "x" * 129)
    for index, category in enumerate(categories):
        task_id = f"invalid-category-{index}"
        token = store.acquire_lease(task_id, lease_seconds=30)
        assert token is not None
        with pytest.raises(ValueError, match="error_category"):
            store.mark_failed(task_id, token, error_category=category)

        dead_task_id = f"invalid-dead-category-{index}"
        dead_token = store.acquire_lease(dead_task_id, lease_seconds=30)
        assert dead_token is not None
        with pytest.raises(ValueError, match="error_category"):
            store.mark_dead(dead_task_id, dead_token, error_category=category)


def test_crash_at_persisted_attempt_limit_is_dead_lettered_after_reopen(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    original, schema = postgres_store
    original.get("crashed-limit-task")
    original.close()
    with psycopg.connect(POSTGRES_DSN or "", autocommit=True) as connection:
        connection.execute(
            _sql(f"""
            UPDATE "{schema}"."tasks"
               SET status = 'RUNNING', attempts = 2, max_attempts = 2,
                   lease_token = 'crashed-owner',
                   lease_expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute',
                   next_run_at = NULL, dead_letter_detail = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = %s
            """),
            ("crashed-limit-task",),
        )

    reopened = PostgresTaskStore(POSTGRES_DSN or "", schema=schema, max_attempts=2)
    try:
        scheduler = TaskScheduler(reopened, backoff=BackoffPolicy(base_seconds=0.0))
        called = False

        def should_not_run() -> None:
            nonlocal called
            called = True

        assert scheduler.run("crashed-limit-task", should_not_run) == "DEAD"
        record = reopened.get("crashed-limit-task")
        assert called is False
        assert record.status == "DEAD"
        assert record.attempts == 2
        assert record.lease_token is None
        assert record.lease_expires_at is None
        assert record.next_run_at is None
        assert record.dead_letter_detail == {"message": "retry limit reached"}
    finally:
        reopened.close()


@pytest.mark.parametrize("max_inline_attempts", [0, -1, 0.5, True])
def test_postgres_scheduler_rejects_non_positive_inline_attempts_before_lease(
    postgres_store: tuple[PostgresTaskStore, str],
    max_inline_attempts: object,
) -> None:
    store, _ = postgres_store
    scheduler = TaskScheduler(store)

    with pytest.raises(ValueError, match="max_inline_attempts must be a positive integer"):
        scheduler.run(
            "invalid-inline-attempts",
            lambda: None,
            max_inline_attempts=cast(int, max_inline_attempts),
        )

    record = store.get("invalid-inline-attempts")
    assert record.status == "PENDING"
    assert record.attempts == 0
    assert record.lease_token is None


def test_postgres_persisted_attempt_limit_dead_letters_after_reopen(
    postgres_store: tuple[PostgresTaskStore, str],
) -> None:
    original, schema = postgres_store
    original.close()
    store = PostgresTaskStore(POSTGRES_DSN or "", schema=schema, max_attempts=2)
    scheduler = TaskScheduler(store, backoff=BackoffPolicy(base_seconds=0.0))

    def fail() -> None:
        raise TransientError("unavailable")

    assert scheduler.run("attempt-limit-task", fail, max_inline_attempts=1) == "FAILED"
    assert scheduler.run("attempt-limit-task", fail, max_inline_attempts=1) == "DEAD"
    store.close()

    reopened = PostgresTaskStore(POSTGRES_DSN or "", schema=schema, max_attempts=2)
    try:
        record = reopened.get("attempt-limit-task")
        assert record.status == "DEAD"
        assert record.attempts == 2
        assert record.max_attempts == 2
        assert record.dead_letter_detail == {"message": "retry limit reached"}
    finally:
        reopened.close()


def _sql(statement: str) -> LiteralString:
    return cast(LiteralString, statement)
