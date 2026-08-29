from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pytest
from quant_engine.http import QuantEngineHttpServer
from quant_engine.paper_workspace import (
    PaperWorkspace,
    PaperWorkspaceConflictError,
    PaperWorkspaceError,
)

NOW = datetime(2026, 8, 27, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def create_command(request_id: str = "create-request-1") -> dict[str, object]:
    return {
        "schemaVersion": "paper-terminal-create-account-v1",
        "clientRequestId": request_id,
        "name": "本地研究账户",
        "initialCapital": "100000",
    }


def simulation_command(request_id: str = "simulation-request-1") -> dict[str, object]:
    return {
        "schemaVersion": "paper-terminal-simulation-v1",
        "clientRequestId": request_id,
        "instrumentId": "600519.SH",
        "price": "100",
        "score": "1",
        "confidence": "1",
        "lotSize": 100,
    }


def test_paper_workspace_runs_a_simulation_only_fill_and_reconciles() -> None:
    workspace = PaperWorkspace(lambda: NOW)
    empty = workspace.snapshot()
    assert empty["status"] == "EMPTY"
    assert empty["persistenceMode"] == "VOLATILE_IN_MEMORY"

    created = workspace.create_account(create_command())
    assert created["status"] == "READY"
    assert created["account"]["cash"] == "100000"  # type: ignore[index]

    completed = workspace.simulate(simulation_command())
    assert completed["dataMeaning"] == "SIMULATION_ONLY_NO_BROKER_PATH"
    assert completed["executionCapability"] == "PAPER_ONLY"
    assert completed["orders"][0]["status"] == "FILLED"  # type: ignore[index]
    assert completed["latestRisk"]["allowed"] is True  # type: ignore[index]
    assert completed["reconciliation"]["status"] == "MATCHED"  # type: ignore[index]
    assert completed["account"]["positions"][0]["instrumentId"] == "600519.SH"  # type: ignore[index]


def test_command_retries_are_idempotent_and_conflicts_fail_closed() -> None:
    workspace = PaperWorkspace(lambda: NOW)
    first = workspace.create_account(create_command())
    assert workspace.create_account(create_command())["account"] == first["account"]
    workspace.simulate(simulation_command())
    assert len(workspace.simulate(simulation_command())["orders"]) == 1  # type: ignore[arg-type]
    with pytest.raises(PaperWorkspaceConflictError):
        workspace.simulate({**simulation_command(), "price": "101"})


def test_durable_command_journal_recovers_exact_workspace_after_restart(tmp_path: Path) -> None:
    journal = tmp_path / "paper-workspace.jsonl"
    first = PaperWorkspace(lambda: NOW, journal)
    first.create_account(create_command())
    before = first.simulate(simulation_command())

    recovered = PaperWorkspace(lambda: NOW, journal)
    after = recovered.snapshot()

    assert after["persistenceMode"] == "DURABLE_COMMAND_JOURNAL"
    assert after["account"] == before["account"]
    assert after["orders"] == before["orders"]
    assert after["reconciliation"] == before["reconciliation"]
    assert after["audit"] == before["audit"]
    assert len(recovered.simulate(simulation_command())["orders"]) == 1  # type: ignore[arg-type]
    with pytest.raises(PaperWorkspaceConflictError):
        recovered.simulate({**simulation_command(), "price": "101"})


def test_corrupted_durable_command_journal_fails_closed(tmp_path: Path) -> None:
    journal = tmp_path / "paper-workspace.jsonl"
    journal.write_text('{"sequence":1}\n', encoding="utf-8")

    with pytest.raises(PaperWorkspaceError, match="模拟工作区持久化日志损坏"):
        PaperWorkspace(lambda: NOW, journal)


def test_tampered_durable_command_journal_fails_digest_validation(tmp_path: Path) -> None:
    journal = tmp_path / "paper-workspace.jsonl"
    PaperWorkspace(lambda: NOW, journal).create_account(create_command())
    record = json.loads(journal.read_text(encoding="utf-8"))
    record["command"]["name"] = "被篡改的账户"
    journal.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(PaperWorkspaceError, match="digest does not match"):
        PaperWorkspace(lambda: NOW, journal)


def test_internal_http_boundary_exposes_health_and_bounded_commands() -> None:
    server = QuantEngineHttpServer("127.0.0.1", 0, PaperWorkspace(lambda: NOW))
    server.start()
    try:
        base = f"http://127.0.0.1:{server.port}"
        with urlopen(f"{base}/health", timeout=2) as response:  # noqa: S310
            assert json.load(response)["status"] == "ok"
        request = Request(  # noqa: S310
            f"{base}/v1/paper/accounts",
            data=json.dumps(create_command()).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310
            assert json.load(response)["status"] == "READY"
    finally:
        server.stop()
