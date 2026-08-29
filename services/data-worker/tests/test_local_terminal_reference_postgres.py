from __future__ import annotations

import os
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import LiteralString, cast
from uuid import uuid4

import psycopg
import pytest
from data_worker.jobs.local_reference import (
    LocalReferenceMaterializationError,
    PostgresLocalReferenceWriter,
    build_local_reference_plan,
    load_local_reference_catalog,
)

POSTGRES_DSN = os.environ.get("KUNLUN_TEST_POSTGRES_DSN")


def _sql(value: str) -> LiteralString:
    return cast(LiteralString, value)


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data/reference/local-terminal-instruments-v1.json"


@pytest.fixture()
def reference_schema() -> Generator[str, None, None]:
    if not POSTGRES_DSN:
        pytest.skip("set KUNLUN_TEST_POSTGRES_DSN to run PostgreSQL integration tests")

    schema = f"local_reference_test_{uuid4().hex}"
    with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
        connection.execute(_sql(f'CREATE SCHEMA "{schema}"'))
        for table, identity_columns in (
            ("instrument_master_revisions", "instrument_id TEXT NOT NULL"),
            ("sector_master_revisions", "sector_id TEXT NOT NULL"),
            (
                "sector_membership_revisions",
                "instrument_id TEXT NOT NULL, sector_id TEXT NOT NULL",
            ),
        ):
            connection.execute(
                _sql(f"""
                CREATE TABLE "{schema}".{table} (
                  revision_id TEXT PRIMARY KEY,
                  previous_revision_id TEXT,
                  {identity_columns},
                  effective_from TIMESTAMPTZ NOT NULL,
                  effective_to TIMESTAMPTZ,
                  available_time TIMESTAMPTZ NOT NULL,
                  processing_time TIMESTAMPTZ NOT NULL,
                  source TEXT NOT NULL,
                  source_version TEXT NOT NULL,
                  evidence_id TEXT NOT NULL,
                  payload_fingerprint TEXT NOT NULL,
                  payload JSONB NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL,
                  CONSTRAINT {table}_visibility_ck CHECK (available_time <= processing_time)
                )
                """)
            )
    try:
        yield schema
    finally:
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as connection:
            connection.execute(_sql(f'DROP SCHEMA "{schema}" CASCADE'))


def test_postgres_writer_is_idempotent_and_preserves_point_in_time_fields(
    reference_schema: str,
) -> None:
    plan = build_local_reference_plan(load_local_reference_catalog(_catalog_path()))
    writer = PostgresLocalReferenceWriter(POSTGRES_DSN or "", schema=reference_schema)
    try:
        first = writer.write(plan)
        second = writer.write(plan)
    finally:
        writer.close()

    assert first.inserted == 11
    assert first.existing == 0
    assert second.inserted == 0
    assert second.existing == 11

    with psycopg.connect(POSTGRES_DSN or "") as connection:
        row = cast(
            tuple[object, ...] | None,
            connection.execute(
                _sql(f"""
            SELECT instrument_id, effective_from, available_time, processing_time,
                   source, source_version, evidence_id, payload_fingerprint, payload
              FROM "{reference_schema}".instrument_master_revisions
             WHERE instrument_id = '600519.SH'
            """)
            ).fetchone(),
        )
    assert row is not None
    assert row[0] == "600519.SH"
    assert row[1] == plan.catalog.effective_from
    assert row[2] == plan.catalog.available_time
    assert cast(datetime, row[3]) >= cast(datetime, row[2])
    assert row[4:7] == (
        plan.catalog.source,
        plan.catalog.source_version,
        plan.catalog.evidence_id,
    )
    assert cast(str, row[7]).startswith("sha256:")
    assert cast(dict[str, object], row[8])["name"] == "贵州茅台"


def test_postgres_writer_fails_closed_and_rolls_back_on_conflicting_revision(
    reference_schema: str,
) -> None:
    plan = build_local_reference_plan(load_local_reference_catalog(_catalog_path()))
    writer = PostgresLocalReferenceWriter(POSTGRES_DSN or "", schema=reference_schema)
    try:
        writer.write(plan)
        with psycopg.connect(POSTGRES_DSN or "") as connection:
            connection.execute(
                _sql(f"""
                UPDATE "{reference_schema}".sector_master_revisions
                   SET payload_fingerprint = %s
                 WHERE revision_id = %s
                """),
                ("sha256:" + "0" * 64, plan.sector_revisions[0].revision_id),
            )

        with pytest.raises(LocalReferenceMaterializationError, match="immutable revision conflict"):
            writer.write(plan)
    finally:
        writer.close()

    with psycopg.connect(POSTGRES_DSN or "") as connection:
        counts = [
            cast(
                tuple[int],
                connection.execute(
                    _sql(f'SELECT COUNT(*) FROM "{reference_schema}".{table}')
                ).fetchone(),
            )[0]
            for table in (
                "instrument_master_revisions",
                "sector_master_revisions",
                "sector_membership_revisions",
            )
        ]
    assert counts == [4, 3, 4]
