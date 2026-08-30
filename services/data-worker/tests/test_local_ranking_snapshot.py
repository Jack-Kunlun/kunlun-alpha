from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from ashare_contracts import RankingTerminalSnapshot
from data_worker.jobs.local_reference import load_local_reference_catalog
from data_worker.jobs.ranking_snapshot import (
    ClickHouseRankingBarsReader,
    ClickHouseRankingConfig,
    DailyRankingBar,
    RankingMaterializationError,
    RankingSnapshotPublisher,
    build_local_ranking_snapshot,
)
from quant_core.ranking import RankingRowStatus, ranking_terminal_payload


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data/reference/local-terminal-instruments-v1.json"


def _bars(
    instrument_id: str,
    *,
    base: str,
    step: str,
    amount: str,
    spread: str,
) -> tuple[DailyRankingBar, ...]:
    base_value = Decimal(base)
    step_value = Decimal(step)
    spread_value = Decimal(spread)
    rows: list[DailyRankingBar] = []
    for index in range(20):
        close = base_value + step_value * index
        visible = datetime(2026, 8, 1, 8, tzinfo=UTC) + timedelta(days=index)
        rows.append(
            DailyRankingBar(
                instrument_id=instrument_id,
                date=date(2026, 8, 1) + timedelta(days=index),
                event_time=visible - timedelta(hours=1),
                high=close * (Decimal(1) + spread_value),
                low=close * (Decimal(1) - spread_value),
                close=close,
                amount=Decimal(amount),
                available_time=visible,
                processing_time=visible + timedelta(minutes=1),
                source="akshare-eastmoney",
                source_version="2026.08.29",
                evidence_id=f"sha256:{index:064x}",
            )
        )
    return tuple(rows)


def _all_bars() -> dict[str, tuple[DailyRankingBar, ...]]:
    return {
        "000001.SZ": _bars("000001.SZ", base="10", step="0.1", amount="1000", spread="0.03"),
        "002594.SZ": _bars("002594.SZ", base="200", step="2", amount="3500", spread="0.04"),
        "300750.SZ": _bars("300750.SZ", base="100", step="3", amount="4000", spread="0.05"),
        "301236.SZ": _bars("301236.SZ", base="50", step="1", amount="2500", spread="0.04"),
        "600000.SH": _bars("600000.SH", base="8", step="0.02", amount="1500", spread="0.02"),
        "600519.SH": _bars("600519.SH", base="1500", step="5", amount="3000", spread="0.01"),
        "601318.SH": _bars("601318.SH", base="40", step="0.3", amount="2500", spread="0.025"),
        "688981.SH": _bars("688981.SH", base="80", step="1.5", amount="3800", spread="0.06"),
        "920799.BJ": _bars("920799.BJ", base="20", step="0.5", amount="800", spread="0.07"),
    }


def test_materializer_builds_real_stock_only_point_in_time_ranking() -> None:
    catalog = load_local_reference_catalog(_catalog_path())
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)

    snapshot = build_local_ranking_snapshot(
        catalog=catalog,
        bars_by_instrument=_all_bars(),
        read_cutoff=cutoff,
        generated_at=cutoff,
    )

    assert [row.instrument_id for row in snapshot.rows] == [
        "300750.SZ",
        "688981.SH",
        "301236.SZ",
        "002594.SZ",
        "600519.SH",
        "601318.SH",
        "000001.SZ",
        "920799.BJ",
        "600000.SH",
    ]
    assert all(row.status is RankingRowStatus.INCLUDED for row in snapshot.rows)
    assert snapshot.spec.spec_id == "local-daily-bars-ranking"
    assert [feature.weight_bps for feature in snapshot.spec.features] == [4000, 3000, 3000]
    assert snapshot.as_of == catalog.available_time

    payload = ranking_terminal_payload(snapshot)
    validated = RankingTerminalSnapshot.model_validate(payload)
    assert validated.source_mode == "VERSIONED_RESEARCH_SNAPSHOT"
    assert {row.instrument_id for row in validated.rows} == {
        "000001.SZ",
        "002594.SZ",
        "300750.SZ",
        "301236.SZ",
        "600000.SH",
        "600519.SH",
        "601318.SH",
        "688981.SH",
        "920799.BJ",
    }


def test_materializer_excludes_insufficient_history_and_rejects_future_visibility() -> None:
    catalog = load_local_reference_catalog(_catalog_path())
    bars = _all_bars()
    bars["600000.SH"] = bars["600000.SH"][:9]
    cutoff = datetime(2026, 8, 30, 12, tzinfo=UTC)

    snapshot = build_local_ranking_snapshot(
        catalog=catalog,
        bars_by_instrument=bars,
        read_cutoff=cutoff,
        generated_at=cutoff,
    )
    excluded = next(row for row in snapshot.rows if row.instrument_id == "600000.SH")
    assert excluded.status is RankingRowStatus.EXCLUDED
    assert excluded.exclusion_reasons == (
        "MISSING_REQUIRED_FEATURE:momentum_10d",
        "MISSING_REQUIRED_FEATURE:average_amount_10d",
        "MISSING_REQUIRED_FEATURE:intraday_range_10d",
        "NO_AVAILABLE_FEATURES",
        "COVERAGE_BELOW_MINIMUM",
    )

    future = list(bars["000001.SZ"])
    future[-1] = replace(future[-1], processing_time=cutoff + timedelta(seconds=1))
    bars["000001.SZ"] = tuple(future)
    with pytest.raises(RankingMaterializationError, match="later than read cutoff"):
        build_local_ranking_snapshot(
            catalog=catalog,
            bars_by_instrument=bars,
            read_cutoff=cutoff,
            generated_at=cutoff,
        )


def test_clickhouse_reader_uses_all_point_in_time_predicates_and_parses_decimals() -> None:
    calls: list[tuple[str, bytes]] = []

    def transport(
        url: str,
        _headers: dict[str, str],
        body: bytes,
        _timeout: float,
    ) -> tuple[int, bytes]:
        calls.append((url, body))
        return 200, (
            json.dumps(
                {
                    "date": "2026-08-29",
                    "event_time": "2026-08-29T07:00:00.000Z",
                    "high": "12.30",
                    "low": "11.10",
                    "close": "12.00",
                    "amount": "123456.78",
                    "available_time": "2026-08-29T08:00:00.000Z",
                    "processing_time": "2026-08-29T08:01:00.000Z",
                    "source": "akshare-eastmoney",
                    "source_version": "2026.08.29",
                    "evidence_id": "sha256:" + "a" * 64,
                }
            ).encode()
            + b"\n"
        )

    reader = ClickHouseRankingBarsReader(
        ClickHouseRankingConfig(
            url="http://clickhouse:8123",
            database="kunlun",
            user="kunlun",
        ),
        transport=transport,
    )
    rows = reader.read("600519.SH", datetime(2026, 8, 30, tzinfo=UTC), limit=20)

    assert rows[0].close == Decimal("12.00")
    assert "param_instrumentId=600519.SH" in calls[0][0]
    query = calls[0][1].decode()
    assert "event_time <= cutoff" in query
    assert "available_time <= cutoff" in query
    assert "processing_time <= cutoff" in query
    assert "LIMIT {limit:UInt32}" in query


def test_publisher_skips_existing_snapshot_and_posts_when_missing() -> None:
    existing_payload = {"snapshotId": "a" * 64, "asOf": "2026-08-29T08:01:00Z"}
    calls: list[str] = []

    def existing_transport(
        method: str,
        _url: str,
        _headers: dict[str, str],
        _body: bytes | None,
        _timeout: float,
    ) -> tuple[int, bytes]:
        calls.append(method)
        return 200, json.dumps(existing_payload).encode()

    publisher = RankingSnapshotPublisher("http://quant-engine:8081", transport=existing_transport)
    result = publisher.publish(cast(dict[str, object], existing_payload))
    assert result.published is False
    assert calls == ["GET"]

    calls.clear()

    def missing_transport(
        method: str,
        _url: str,
        _headers: dict[str, str],
        body: bytes | None,
        _timeout: float,
    ) -> tuple[int, bytes]:
        calls.append(method)
        if method == "GET":
            return 404, b'{"error":"not_found"}'
        assert body is not None
        return 200, body

    publisher = RankingSnapshotPublisher("http://quant-engine:8081", transport=missing_transport)
    result = publisher.publish(cast(dict[str, object], existing_payload))
    assert result.published is True
    assert calls == ["GET", "POST"]
