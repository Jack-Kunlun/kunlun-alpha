"""Repository-visible P6-N03 materialization runtime test."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from data_worker.jobs.limit_pool_terminal import ClickHouseTerminalConfig
from data_worker.jobs.limit_pool_terminal.runtime import (
    load_materialization_request,
    run_materialization_file,
)

FIXTURE = (
    Path(__file__).resolve().parents[3] / "data" / "fixtures" / "limit-pool-terminal-local.json"
)


def test_runtime_materializes_repository_fixture_and_persists() -> None:
    calls: list[tuple[str, Mapping[str, str], bytes, float]] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        calls.append((url, headers, body, timeout_seconds))
        return 200, b""

    projection = run_materialization_file(
        FIXTURE,
        ClickHouseTerminalConfig(
            url="http://clickhouse:8123",
            database="kunlun",
            user="writer",
        ),
        transport=transport,
    )

    assert projection.trading_date == "2026-08-25"
    assert projection.source_versions == ("sanitized-local-fixture:v1",)
    assert projection.evidence_ids == ("fixture-limit-600000-1",)
    assert len(calls) == 1
    assert calls[0][2].startswith(
        b"INSERT INTO limit_pool_terminal_snapshots_v2 FORMAT JSONEachRow\n"
    )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_runtime_rejects_non_finite_json_constants(tmp_path: Path, constant: str) -> None:
    request = tmp_path / "request.json"
    request.write_text(f'{{"value": {constant}}}', encoding="utf-8")

    with pytest.raises(ValueError, match="non-finite JSON number"):
        load_materialization_request(request)


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0"])
def test_runtime_rejects_invalid_price_strings(tmp_path: Path, price: str) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["entries"][0]["priceCny"] = price
    request = tmp_path / "request.json"
    request.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="priceCny must be a positive finite decimal"):
        load_materialization_request(request)
