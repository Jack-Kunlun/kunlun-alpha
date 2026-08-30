from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_worker.jobs.local_reference import (
    LocalReferenceCatalogError,
    LocalReferenceMaterializationResult,
    build_local_reference_plan,
    load_local_reference_catalog,
    runtime,
)


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data/reference/local-terminal-instruments-v1.json"


def test_catalog_builds_versioned_instrument_sector_and_membership_revisions() -> None:
    catalog = load_local_reference_catalog(_catalog_path())
    plan = build_local_reference_plan(catalog)

    assert catalog.catalog_version == "2026.08.30.2"
    assert [item.instrument_id for item in catalog.instruments] == [
        "000001.SZ",
        "002594.SZ",
        "300750.SZ",
        "301236.SZ",
        "600000.SH",
        "600519.SH",
        "601318.SH",
        "688981.SH",
        "920799.BJ",
    ]
    assert {item.board for item in catalog.instruments} == {"MAIN", "CHINEXT", "STAR", "BSE"}
    assert len(plan.instrument_revisions) == 9
    assert len(plan.sector_revisions) == 7
    assert len(plan.membership_revisions) == 9
    assert all(item.payload_fingerprint.startswith("sha256:") for item in plan.all_revisions)
    assert all(len(item.payload_fingerprint) == 71 for item in plan.all_revisions)
    assert plan.instrument_revisions[0].payload == {
        "unifiedCode": "000001.SZ",
        "code": "000001",
        "exchange": "SZ",
        "board": "MAIN",
        "type": "STOCK",
        "name": "平安银行",
        "tradingStatus": "LISTED",
        "currency": "CNY",
    }


def test_catalog_rejects_duplicate_or_non_stock_entries(tmp_path: Path) -> None:
    raw = json.loads(_catalog_path().read_text(encoding="utf-8"))
    raw["instruments"].append(dict(raw["instruments"][0]))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(LocalReferenceCatalogError, match="duplicate instrument"):
        load_local_reference_catalog(duplicate)

    raw["instruments"].pop()
    raw["instruments"][0]["type"] = "INDEX"
    wrong_type = tmp_path / "wrong-type.json"
    wrong_type.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(LocalReferenceCatalogError, match="STOCK"):
        load_local_reference_catalog(wrong_type)


def test_runtime_routes_materialization_to_explicit_application_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class StubWriter:
        def __init__(self, dsn: str, *, schema: str) -> None:
            captured["dsn"] = dsn
            captured["schema"] = schema

        def write(self, plan: object) -> LocalReferenceMaterializationResult:
            captured["plan"] = plan
            return LocalReferenceMaterializationResult(inserted=11, existing=0)

        def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(runtime, "PostgresLocalReferenceWriter", StubWriter)

    result = runtime.run_materialization(
        dsn="postgresql://local-test",
        catalog_path=_catalog_path(),
        schema="kunlun",
    )

    assert result == LocalReferenceMaterializationResult(inserted=11, existing=0)
    assert captured["dsn"] == "postgresql://local-test"
    assert captured["schema"] == "kunlun"
    assert captured["closed"] is True
