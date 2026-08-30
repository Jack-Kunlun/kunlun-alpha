from __future__ import annotations

import json
from pathlib import Path

import pytest
from data_worker.jobs.offline_market_replay import (
    OfflineReplayFixtureError,
    load_offline_replay_bundle,
    run_offline_replay_check,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _fixture_path() -> Path:
    return _repo_root() / "data/fixtures/offline-market-replay-v1.json"


def _catalog_path() -> Path:
    return _repo_root() / "data/reference/local-terminal-instruments-v1.json"


def test_offline_replay_covers_all_stock_boards_without_network_or_database() -> None:
    summary = run_offline_replay_check(
        fixture_path=_fixture_path(),
        catalog_path=_catalog_path(),
    )

    assert summary.fixture_version == "2026.08.30.1"
    assert summary.catalog_version == "2026.08.30.2"
    assert summary.data_meaning == "SANITIZED_OFFLINE_FIXTURE_NO_MARKET_CLAIM"
    assert summary.capture_count == 6
    assert summary.bar_count == 11
    assert summary.instrument_ids == (
        "002594.SZ",
        "301236.SZ",
        "600519.SH",
        "688981.SH",
        "920799.BJ",
    )
    assert summary.board_coverage == ("BSE", "CHINEXT", "MAIN", "STAR")
    assert summary.exchange_coverage == ("BJ", "SH", "SZ")
    assert summary.interval_coverage == ("DAILY", "MINUTE_1")
    assert summary.source_profiles == ("akshare-sina", "akshare-tencent")


def test_offline_replay_rejects_a_fixture_that_claims_real_market_meaning(
    tmp_path: Path,
) -> None:
    raw = json.loads(_fixture_path().read_text(encoding="utf-8"))
    raw["dataMeaning"] = "REAL_MARKET_DATA"
    fixture = tmp_path / "unsafe.json"
    fixture.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(OfflineReplayFixtureError, match="dataMeaning"):
        load_offline_replay_bundle(fixture)


def test_offline_replay_rejects_instruments_outside_the_curated_catalog(
    tmp_path: Path,
) -> None:
    raw = json.loads(_fixture_path().read_text(encoding="utf-8"))
    raw["captures"][0]["unifiedCode"] = "603999.SH"
    raw["captures"][0]["rows"][0]["股票代码"] = "603999"
    raw["captures"][0]["rows"][1]["股票代码"] = "603999"
    fixture = tmp_path / "unknown-instrument.json"
    fixture.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(OfflineReplayFixtureError, match="catalog"):
        run_offline_replay_check(fixture_path=fixture, catalog_path=_catalog_path())
