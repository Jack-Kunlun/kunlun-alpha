from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pytest
from ashare_contracts import PaperAllocationDecision as AllocationContract
from ashare_contracts import PaperRiskDecision as RiskContract
from ashare_contracts import PaperTerminalSimulationCommand
from paper_core import (
    PaperAccountState,
    PaperAccountStatus,
    PaperExecutionTape,
    ReconciliationHealth,
    replay_execution,
)
from quant_engine.http import QuantEngineHttpServer
from quant_engine.paper_preview import preview_allocation
from quant_engine.paper_risk_preview import preview_risk_decision
from quant_engine.paper_workspace import PaperWorkspace, PaperWorkspaceError

NOW = datetime(2026, 10, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def command(**changes: object) -> dict[str, object]:
    return {
        "schemaVersion": "paper-terminal-simulation-v1",
        "clientRequestId": "preview-request-1",
        "instrumentId": "600519.SH",
        "price": "100",
        "score": "1",
        "confidence": "1",
        "lotSize": 100,
        **changes,
    }


def account(journal: Path | None = None, capital: str = "100000") -> PaperWorkspace:
    workspace = PaperWorkspace(lambda: NOW, journal)
    workspace.create_account(
        {
            "schemaVersion": "paper-terminal-create-account-v1",
            "clientRequestId": "create-preview-test",
            "name": "隔离试算账户",
            "initialCapital": capital,
        }
    )
    return workspace


def test_risk_preview_is_bound_to_the_unexecuted_allocation_and_reads_real_books() -> None:
    workspace = account()
    allocation = workspace.preview(command())
    before = workspace.snapshot()
    result = RiskContract.model_validate(workspace.risk_preview(allocation))
    assert result.intent_id == AllocationContract.model_validate(allocation).intents[0].intent_id
    assert result.allowed is False
    checks = {item.code.value: item for item in result.checks}
    assert len(checks) == 10
    assert checks["EXECUTION_CONNECTED"].actual == "false"
    assert checks["EXECUTION_CONNECTED"].status.value == "FAIL"
    assert checks["RECONCILIATION_HEALTHY"].actual == "MATCHED"
    assert checks["ORDER_NOTIONAL_LIMIT"].actual == "30000"
    assert checks["CASH_AVAILABLE"].actual == "70000"
    assert workspace.snapshot() == before


@pytest.mark.parametrize("field", ["quantity", "price", "digest", "policy"])
def test_risk_preview_refuses_forged_allocation_snapshots(field: str) -> None:
    workspace = account()
    allocation = AllocationContract.model_validate(workspace.preview(command()))
    before = workspace.snapshot()
    if field == "quantity":
        allocation.intents[0].quantity += 100
        allocation.intents[0].target_quantity += 100
        allocation.targets[0].target_quantity += 100
    elif field == "price":
        allocation.targets[0].reference_price = "101"
        allocation.intents[0].reference_price = "101"
    elif field == "digest":
        allocation.decision_digest = "0" * 64
    else:
        allocation.policy_version = "2.0.0"
    with pytest.raises(PaperWorkspaceError):
        workspace.risk_preview(allocation.model_dump(by_alias=True, mode="json"))
    assert workspace.snapshot() == before


def test_risk_preview_does_not_change_journal_or_register_a_command(tmp_path: Path) -> None:
    journal = tmp_path / "paper.jsonl"
    workspace = account(journal)
    allocation = workspace.preview(command())
    original = journal.read_bytes()
    before = workspace.snapshot()
    first = workspace.risk_preview(allocation)
    assert workspace.risk_preview(allocation) == first
    assert journal.read_bytes() == original
    assert workspace.snapshot() == before
    assert PaperWorkspace(lambda: NOW, journal).snapshot() == before


def test_risk_preview_rejects_a_stale_account_basis() -> None:
    workspace = account()
    allocation = workspace.preview(command())
    workspace.simulate(command())
    before = workspace.snapshot()
    with pytest.raises(PaperWorkspaceError, match="变化"):
        workspace.risk_preview(allocation)
    assert workspace.snapshot() == before


def test_risk_preview_requires_an_actionable_existing_allocation() -> None:
    workspace = account()
    with pytest.raises(PaperWorkspaceError):
        workspace.risk_preview(workspace.preview(command(confidence="0.1")))


def test_risk_preview_requires_an_account_and_rejects_future_snapshots(tmp_path: Path) -> None:
    journal = tmp_path / "paper.jsonl"
    workspace = account(journal)
    allocation = workspace.preview(command())
    with pytest.raises(PaperWorkspaceError, match="创建模拟账户"):
        PaperWorkspace(lambda: NOW).risk_preview(allocation)
    with pytest.raises(PaperWorkspaceError, match="晚于"):
        PaperWorkspace(lambda: NOW - timedelta(seconds=1), journal).risk_preview(allocation)


@pytest.mark.parametrize("time", ["2026-10-25T02:00:00.000000001Z", "2026-10-25T10:00:00+08:00"])
def test_risk_preview_refuses_timestamp_rewriting(time: str) -> None:
    workspace = account()
    allocation = workspace.preview(command())
    allocation["decisionTime"] = time
    with pytest.raises(PaperWorkspaceError, match="未改写|不一致"):
        workspace.risk_preview(allocation)


@pytest.mark.parametrize("health", [ReconciliationHealth.DRIFTED, ReconciliationHealth.UNAVAILABLE])
def test_risk_preview_preserves_failed_reconciliation_as_a_blocker(
    health: ReconciliationHealth,
) -> None:
    state = PaperAccountState(
        "a" * 64,
        "isolated-risk-fixture",
        "隔离风险检查",
        PaperAccountStatus.ACTIVE,
        Decimal("100000"),
        Decimal("100000"),
        (),
        None,
        NOW,
        1,
        "b" * 64,
    )
    allocation = AllocationContract.model_validate(
        preview_allocation(state, PaperTerminalSimulationCommand.model_validate(command()), NOW)
    )
    result = RiskContract.model_validate(
        preview_risk_decision(
            state, replay_execution(PaperExecutionTape(state.account_id)), health, allocation, NOW
        )
    )
    check = next(item for item in result.checks if item.code.value == "RECONCILIATION_HEALTHY")
    assert check.actual == health.value
    assert check.status.value == "FAIL"
    assert result.allowed is False


def test_risk_preview_preserves_decimal_precision_for_a_long_weight() -> None:
    workspace = account()
    allocation = workspace.preview(
        command(
            price="100.000000000000000001",
            score="0.123456789012345678",
            confidence="0.987654321098765432",
        )
    )
    normal = workspace.risk_preview(allocation)
    with localcontext() as context:
        context.prec = 6
        assert workspace.risk_preview(allocation) == normal


def test_risk_preview_http_reads_without_writing_and_rejects_invalid_snapshots() -> None:
    from urllib.error import HTTPError

    workspace = account()
    allocation = workspace.preview(command())
    before = workspace.snapshot()
    server = QuantEngineHttpServer("127.0.0.1", 0, workspace)
    server.start()
    try:

        def post(value: dict[str, object]) -> RiskContract:
            request = Request(
                f"http://127.0.0.1:{server.port}/v1/paper/risk-previews",
                data=json.dumps(value).encode(),
                headers={"content-type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:  # noqa: S310
                assert response.status == 200
                return RiskContract.model_validate(json.load(response))

        assert post(allocation).allowed is False
        with pytest.raises(HTTPError) as error:
            post({})
        assert error.value.code == 422
        assert workspace.snapshot() == before
    finally:
        server.stop()


def test_preview_uses_existing_allocation_contract_without_creating_an_order() -> None:
    workspace = account()
    before = workspace.snapshot()
    result = workspace.preview(command())
    assert result["schemaVersion"] == "paper-allocation-decision-v1"
    assert result["dataMeaning"] == "INTENT_ONLY_NO_BROKER_PATH"
    parsed = AllocationContract.model_validate(result)
    assert parsed.targets[0].target_quantity == 300
    assert parsed.targets[0].target_weight == "0.3"
    assert parsed.intents[0].broker_executable is False
    assert parsed.intents[0].execution_capability == "PAPER_ONLY"
    assert workspace.snapshot() == before


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"confidence": "0.1"}, "LOW_CONFIDENCE"),
        ({"price": "1000"}, "BOARD_LOT_ROUNDED_TO_ZERO"),
        ({"score": "0"}, "NO_ACTION"),
    ],
)
def test_preview_returns_explainable_rejections_without_mutation(
    changes: dict[str, object], reason: str
) -> None:
    workspace = account()
    before = workspace.snapshot()
    result = workspace.preview(command(**changes))
    assert result["intents"] == []
    assert AllocationContract.model_validate(result).rejections[0].reason.value == reason
    assert workspace.snapshot() == before


def test_preview_does_not_register_requests_or_change_durable_bytes(tmp_path: Path) -> None:
    journal = tmp_path / "paper.jsonl"
    workspace = account(journal)
    original = journal.read_bytes()
    before = workspace.snapshot()
    first = workspace.preview(command())
    assert workspace.preview(command()) == first
    assert workspace.preview(command(price="101")) != first
    assert journal.read_bytes() == original
    assert workspace.snapshot() == before
    assert PaperWorkspace(lambda: NOW, journal).snapshot() == before


def test_preview_requires_an_existing_account() -> None:
    with pytest.raises(PaperWorkspaceError, match="创建模拟账户"):
        PaperWorkspace(lambda: NOW).preview(command())


def test_preview_rejects_unsafe_javascript_quantity_without_changing_the_account() -> None:
    workspace = account()
    before = workspace.snapshot()
    with pytest.raises(PaperWorkspaceError, match="范围"):
        workspace.preview(command(price="0.00000000000001"))
    assert workspace.snapshot() == before


def test_preview_refuses_a_degraded_workspace() -> None:
    workspace = account(capital="10000000000")
    workspace.simulate(command())
    before = workspace.snapshot()
    assert before["status"] == "DEGRADED"
    with pytest.raises(PaperWorkspaceError, match="异常"):
        workspace.preview(command())
    assert workspace.snapshot() == before


@pytest.mark.parametrize("changes", [{"lotSize": True}, {"price": "NaN"}, {"unknown": "field"}])
def test_preview_rejects_invalid_external_input(changes: dict[str, object]) -> None:
    workspace = account()
    before = workspace.snapshot()
    with pytest.raises(ValueError):
        workspace.preview(command(**changes))
    assert workspace.snapshot() == before


def test_preview_precision_does_not_depend_on_the_ambient_decimal_context() -> None:
    workspace = account()
    args = command(price="100.000000000000000001")
    normal = workspace.preview(args)
    with localcontext() as context:
        context.prec = 6
        assert workspace.preview(args) == normal
    assert AllocationContract.model_validate(normal).targets[0].target_quantity == 200


def test_preview_internal_http_route_is_read_only() -> None:
    workspace = account()
    before = workspace.snapshot()
    server = QuantEngineHttpServer("127.0.0.1", 0, workspace)
    server.start()
    try:
        request = Request(  # noqa: S310
            f"http://127.0.0.1:{server.port}/v1/paper/previews",
            data=json.dumps(command()).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310
            parsed = AllocationContract.model_validate(json.load(response))
        assert parsed.targets[0].target_quantity == 300
        assert workspace.snapshot() == before
    finally:
        server.stop()
