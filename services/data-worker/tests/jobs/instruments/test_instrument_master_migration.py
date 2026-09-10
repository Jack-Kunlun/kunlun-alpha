"""Static and bounded contract checks for the private P1-N06 provider."""

from __future__ import annotations

from data_worker.storage import migrations


def test_provider_migration_is_private_and_versioned_separately() -> None:
    assert migrations.INSTRUMENT_MASTER_PROVIDER_MIGRATION_VERSION == 1
    assert migrations.INSTRUMENT_MASTER_PROVIDER_SCHEMA == "kunlun_instrument_provider"
    assert migrations.load_instrument_master_migration()
    sql = migrations.INSTRUMENT_MASTER_PROVIDER_MIGRATION
    for table in migrations.INSTRUMENT_MASTER_TABLES:
        assert f'"{migrations.INSTRUMENT_MASTER_PROVIDER_SCHEMA}"."{table}"' in sql
    assert "tushare_instrument_master_history_immutable" in sql
    assert "tushare_instrument_master_publish_head" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = pg_catalog, pg_temp" in sql
    assert "revision identity mismatch" in sql
    assert "REVOKE ALL ON FUNCTION" in sql
    assert "tushare_instrument_master_audit_actor_immutable" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "FLOAT" not in sql.upper()


def test_worker_migration_order_stays_v1_through_v4() -> None:
    assert migrations.MIGRATION_VERSION == 1
    assert migrations.SEAT_MIGRATION_VERSION == 2
    assert migrations.CALENDAR_SNAPSHOT_MIGRATION_VERSION == 3
    assert migrations.OFFICIAL_CALENDAR_MIGRATION_VERSION == 4
    assert migrations.INSTRUMENT_MASTER_PROVIDER_MIGRATION_VERSION == 1
