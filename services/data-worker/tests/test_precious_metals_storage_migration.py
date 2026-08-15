"""RED tests for the additive precious-metals PostgreSQL schema."""

from __future__ import annotations

import data_worker.storage as storage_module


def test_additive_migration_declares_numeric_observation_tables() -> None:
    sql = str(getattr(storage_module, "PRECIOUS_METALS_MIGRATION", ""))
    assert sql, "additive migration SQL artifact is missing"
    for table in (
        "fund_observation_evidence",
        "fund_metadata_observations",
        "fund_nav_observations",
        "fund_inav_observations",
        "fund_rejections",
        "fund_quality_event_evidence",
    ):
        assert table in sql
    assert "NUMERIC" in sql
    assert "CREATE TABLE IF NOT EXISTS" not in sql


def test_migration_does_not_rewrite_v1_or_use_floating_point() -> None:
    migration = str(getattr(storage_module, "PRECIOUS_METALS_MIGRATION", ""))
    assert migration, "additive migration SQL artifact is missing"
    assert "DROP TABLE" not in migration.upper()
    assert "DOUBLE PRECISION" not in migration.upper()
    assert "FLOAT" not in migration.upper()
