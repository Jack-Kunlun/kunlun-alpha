"""Fail-first contract checks for the private Tushare provider boundary."""

from __future__ import annotations

from data_worker.storage import migrations


def test_provider_migration_uses_private_schema_and_is_not_in_generic_worker_plan() -> None:
    assert migrations.INSTRUMENT_MASTER_PROVIDER_SCHEMA == "kunlun_instrument_provider"
    assert migrations.INSTRUMENT_MASTER_PROVIDER_MIGRATION_VERSION == 1
    assert migrations.apply_instrument_master_provider_migration is not None
    sql = migrations.INSTRUMENT_MASTER_PROVIDER_MIGRATION
    assert '"kunlun_instrument_provider"."tushare_instrument_master_revisions"' in sql
    assert "CREATE TABLE IF NOT EXISTS instrument_master_revisions" not in sql
    assert "tushare_instrument_master_schema_migrations" in sql
