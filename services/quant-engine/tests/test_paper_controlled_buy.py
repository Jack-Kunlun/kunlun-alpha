from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Never
from zoneinfo import ZoneInfo

import pytest
from ashare_contracts import PaperAllocationDecision, PaperTerminalWorkspace
from quant_engine.paper_journal import PaperCommandJournal, PaperCommandJournalError
from quant_engine.paper_workspace import PaperWorkspace, PaperWorkspaceError

NOW = datetime(2026, 10, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def workspace(path: Path, *, capital: str = "100000", enabled: bool = True) -> PaperWorkspace:
    result = PaperWorkspace(lambda: NOW, path, controlled_buy_enabled=enabled)
    result.create_account(
        {
            "schemaVersion": "paper-terminal-create-account-v1",
            "clientRequestId": "isolated-buy-account",
            "name": "隔离模拟买入",
            "initialCapital": capital,
        }
    )
    return result


def allocation(book: PaperWorkspace, **changes: object) -> dict[str, object]:
    return book.preview(
        {
            "schemaVersion": "paper-terminal-simulation-v1",
            "clientRequestId": "isolated-buy-preview",
            "instrumentId": "600519.SH",
            "price": "100",
            "score": "0.3",
            "confidence": "1",
            "lotSize": 100,
            **changes,
        }
    )


def test_controlled_buy_commits_one_fill_with_fees_and_balanced_books(tmp_path: Path) -> None:
    book = workspace(tmp_path / "paper.jsonl")
    before = PaperTerminalWorkspace.model_validate(book.snapshot())
    snapshot = allocation(book)
    result = PaperTerminalWorkspace.model_validate(book.buy_allocation(snapshot))
    assert result.account is not None and before.account is not None
    assert result.account.cash == "69991"
    assert result.account.positions[0].quantity == 300
    assert result.account.positions[0].available_quantity == 0
    assert result.account.positions[0].cost_amount == "30009"
    assert result.orders[0].status.value == "FILLED"
    assert result.orders[0].filled_quantity == 300
    assert result.orders[0].total_fees == "9"
    assert result.latest_risk is not None and result.latest_risk.allowed
    assert result.reconciliation is not None and result.reconciliation.status.value == "MATCHED"
    assert result.audit.alert_count == 0


def test_retry_and_restart_do_not_duplicate_a_committed_fill(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    snapshot = allocation(book)
    first = book.buy_allocation(snapshot)
    original = path.read_bytes()
    assert book.buy_allocation(snapshot) == first
    restored = PaperWorkspace(lambda: NOW, path, controlled_buy_enabled=True)
    assert restored.snapshot() == first
    assert restored.buy_allocation(snapshot) == first
    assert path.read_bytes() == original


@pytest.mark.parametrize("mode", ["stale", "forged", "no_action", "precision", "disabled", "fee"])
def test_failed_preflight_never_appends_a_command_or_changes_state(
    tmp_path: Path, mode: str
) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(
        path, capital="0.01" if mode == "fee" else "100000", enabled=mode != "disabled"
    )
    snapshot = allocation(
        book,
        **(
            {"price": "0.00001", "lotSize": 1}
            if mode == "fee"
            else {"score": "0"}
            if mode == "no_action"
            else {"price": "100.000000001"}
            if mode == "precision"
            else {}
        ),
    )
    if mode == "stale":
        snapshot["accountStateDigest"] = "0" * 64
    if mode == "forged":
        parsed = PaperAllocationDecision.model_validate(snapshot)
        parsed.intents[0].quantity += 100
        snapshot = parsed.model_dump(by_alias=True, mode="json")
    before, original = book.snapshot(), path.read_bytes()
    with pytest.raises(PaperWorkspaceError):
        book.buy_allocation(snapshot)
    assert path.read_bytes() == original
    assert book.snapshot() == before


def test_competing_snapshots_cannot_spend_the_same_account_basis(tmp_path: Path) -> None:
    book = workspace(tmp_path / "paper.jsonl")
    first = allocation(book)
    second = allocation(book, clientRequestId="another-isolated-preview")
    book.buy_allocation(first)
    before = book.snapshot()
    with pytest.raises(PaperWorkspaceError, match="变化"):
        book.buy_allocation(second)
    assert book.snapshot() == before


def test_concurrent_retries_commit_exactly_one_fill(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    snapshot = allocation(book)

    def submit(_: int) -> dict[str, object]:
        return book.buy_allocation(snapshot)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert all(result == results[0] for result in results)
    assert len(path.read_bytes().splitlines()) == 2


def test_uncertain_write_stops_until_restart_and_recovers_one_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    snapshot = allocation(book)
    append = PaperCommandJournal.append

    def interrupted(
        self: PaperCommandJournal,
        *,
        kind: str,
        occurred_at: datetime,
        command: Mapping[str, object],
    ) -> Never:
        append(self, kind=kind, occurred_at=occurred_at, command=command)
        raise PaperCommandJournalError("isolated failure after durable write")

    with monkeypatch.context() as patch:
        patch.setattr(PaperCommandJournal, "append", interrupted)
        with pytest.raises(PaperWorkspaceError, match="重启"):
            book.buy_allocation(snapshot)
    with pytest.raises(PaperWorkspaceError, match="重启"):
        book.snapshot()
    assert book.available is False
    with pytest.raises(PaperWorkspaceError, match="重启"):
        book.buy_allocation(snapshot)
    restored = PaperWorkspace(lambda: NOW, path, controlled_buy_enabled=True)
    result = PaperTerminalWorkspace.model_validate(restored.buy_allocation(snapshot))
    assert len(result.orders) == 1 and result.orders[0].filled_quantity == 300
    assert len(path.read_bytes().splitlines()) == 2


@pytest.mark.parametrize(
    ("capital", "price", "lot", "fee"),
    [("33500", "100.5", 1, "3.02"), ("333834", "100.15", 100, "30.04"), ("1000", "1", 100, "1")],
)
def test_fees_use_half_even_cents_and_preserve_cash_plus_cost(
    tmp_path: Path, capital: str, price: str, lot: int, fee: str
) -> None:
    from decimal import Decimal

    book = workspace(tmp_path / "paper.jsonl", capital=capital)
    result = PaperTerminalWorkspace.model_validate(
        book.buy_allocation(allocation(book, price=price, lotSize=lot))
    )
    assert result.account is not None
    assert result.orders[0].total_fees == fee
    assert Decimal(result.account.cash) + Decimal(
        result.account.positions[0].cost_amount
    ) == Decimal(capital)


def test_sell_and_old_baseline_are_rejected_without_journal_growth(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    book.buy_allocation(allocation(book))
    sell = allocation(book, score="0.1")
    assert PaperAllocationDecision.model_validate(sell).intents[0].side.value == "SELL"
    before, original = book.snapshot(), path.read_bytes()
    with pytest.raises(PaperWorkspaceError, match="买入"):
        book.buy_allocation(sell)
    assert book.snapshot() == before and path.read_bytes() == original


def test_buy_availability_requires_explicit_enablement_and_durable_storage(tmp_path: Path) -> None:
    book = workspace(tmp_path / "paper.jsonl")
    snapshot = allocation(book)
    assert book.risk_preview(snapshot)["allowed"] is True
    disabled = PaperWorkspace(lambda: NOW, tmp_path / "paper.jsonl")
    assert disabled.risk_preview(snapshot)["allowed"] is False
    book.buy_allocation(snapshot)
    # Disabling new buys must still recover and display already committed data.
    assert (
        len(
            PaperTerminalWorkspace.model_validate(
                PaperWorkspace(lambda: NOW, tmp_path / "paper.jsonl").snapshot()
            ).orders
        )
        == 1
    )


def test_sequential_buys_preserve_existing_average_cost_identity_and_replay(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path, capital="1000")
    first = allocation(book, price="1")
    book.buy_allocation(first)
    second = allocation(book, price="1", instrumentId="000001.SZ", clientRequestId="second-stock")
    assert book.risk_preview(second)["allowed"] is True
    result = PaperTerminalWorkspace.model_validate(book.buy_allocation(second))
    assert result.account is not None and result.account.cash == "498"
    assert len(result.account.positions) == 2
    original = path.read_bytes()
    restarted = PaperWorkspace(lambda: NOW, path, controlled_buy_enabled=True)
    assert restarted.snapshot() == book.snapshot()
    assert len(PaperTerminalWorkspace.model_validate(restarted.buy_allocation(first)).orders) == 2
    assert path.read_bytes() == original


def test_limit_failure_has_no_order_or_journal_side_effects(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path, capital="10000000000")
    snapshot = allocation(book)
    before, original = book.snapshot(), path.read_bytes()
    assert book.risk_preview(snapshot)["allowed"] is False
    with pytest.raises(PaperWorkspaceError, match="风险"):
        book.buy_allocation(snapshot)
    assert book.snapshot() == before and path.read_bytes() == original


def test_http_buy_and_retry_share_one_durable_fill(tmp_path: Path) -> None:
    import json
    from urllib.request import Request, urlopen

    from quant_engine.http import QuantEngineHttpServer

    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    snapshot = allocation(book)
    server = QuantEngineHttpServer("127.0.0.1", 0, book)
    server.start()
    try:

        def post() -> PaperTerminalWorkspace:
            request = Request(
                f"http://127.0.0.1:{server.port}/v1/paper/buy-simulations",
                data=json.dumps(snapshot).encode(),
                headers={"content-type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2) as response:  # noqa: S310
                assert response.status == 200
                return PaperTerminalWorkspace.model_validate(json.load(response))

        first = post()
        assert post() == first
        assert first.orders[0].filled_quantity == 300
        assert len(path.read_bytes().splitlines()) == 2
    finally:
        server.stop()


def test_later_buy_binds_risk_to_its_own_order_and_retries_original(tmp_path: Path) -> None:
    path = tmp_path / "paper.jsonl"
    book = workspace(path)
    first = allocation(book)
    book.buy_allocation(first)
    second = allocation(book, price="50", clientRequestId="isolated-buy-preview-next")
    result = PaperTerminalWorkspace.model_validate(book.buy_allocation(second))
    assert result.account is not None and result.account.positions[0].quantity > 300
    assert len(result.orders) == 2 and all(
        order.status.value == "FILLED" for order in result.orders
    )
    original = path.read_bytes()
    assert len(PaperTerminalWorkspace.model_validate(book.buy_allocation(first)).orders) == 2
    assert path.read_bytes() == original
