from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pytest
from ashare_contracts import PaperReconciliationResult
from paper_core import (
    PaperExecutionBookProjection,
    PaperSettlementBook,
    reconcile_paper_books,
)
from paper_core import (
    PaperReconciliationResult as DomainReconciliation,
)
from quant_engine.http import QuantEngineHttpServer
from quant_engine.paper_workspace import PaperWorkspace, PaperWorkspaceError

NOW = datetime(2026, 10, 25, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.mark.parametrize("traded", [False, True])
def test_fresh_report_never_changes_ledger_or_cached_reconciliation(
    tmp_path: Path, traded: bool
) -> None:
    clock = [NOW]
    path = tmp_path / "paper.jsonl"
    book = PaperWorkspace(lambda: clock[0], path, controlled_buy_enabled=True)
    book.create_account(
        {
            "schemaVersion": "paper-terminal-create-account-v1",
            "clientRequestId": "report-account",
            "name": "隔离核对",
            "initialCapital": "100000",
        }
    )
    if traded:
        allocation = book.preview(
            {
                "schemaVersion": "paper-terminal-simulation-v1",
                "clientRequestId": "report-preview",
                "instrumentId": "600519.SH",
                "price": "100",
                "score": "0.3",
                "confidence": "1",
                "lotSize": 100,
            }
        )
        book.buy_allocation(allocation)
    clock[0] = NOW + timedelta(minutes=1)
    before, journal = book.snapshot(), path.read_bytes()
    report = PaperReconciliationResult.model_validate(book.reconciliation_report())
    assert report.as_of == clock[0]
    assert report.status.value == "MATCHED" and report.diffs == []
    assert report.expected_book_digest == report.observed_book_digest
    assert book.snapshot() == before and path.read_bytes() == journal
    clock[0] += timedelta(minutes=1)
    newer = PaperReconciliationResult.model_validate(book.reconciliation_report())
    assert newer.as_of == clock[0] and newer.reconciliation_id != report.reconciliation_id
    assert book.snapshot()["reconciliation"] == before["reconciliation"]
    assert path.read_bytes() == journal
    restored = PaperWorkspace(lambda: clock[0], path)
    assert restored.reconciliation_report() == book.reconciliation_report()


def test_report_recomputes_actual_drift_instead_of_returning_cached_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "paper.jsonl"
    book = PaperWorkspace(lambda: NOW, path)
    book.create_account(
        {
            "schemaVersion": "paper-terminal-create-account-v1",
            "clientRequestId": "drift-account",
            "name": "隔离差异",
            "initialCapital": "100000",
        }
    )
    before, journal = book.snapshot(), path.read_bytes()

    def drift(
        expected: PaperExecutionBookProjection, observed: PaperSettlementBook
    ) -> DomainReconciliation:
        return reconcile_paper_books(
            expected, replace(observed, cash=observed.cash - Decimal("0.01"))
        )

    monkeypatch.setattr("quant_engine.paper_workspace.reconcile_paper_books", drift)
    result = PaperReconciliationResult.model_validate(book.reconciliation_report())
    assert result.status.value == "DRIFTED"
    assert len(result.diffs) == 1
    assert result.diffs[0].kind.value == "CASH"
    assert result.diffs[0].difference == "-0.01"
    assert book.snapshot() == before and path.read_bytes() == journal


def test_report_empty_and_uncertain_state_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = PaperWorkspace(lambda: NOW, tmp_path / "paper.jsonl")
    with pytest.raises(PaperWorkspaceError):
        book.reconciliation_report()
    monkeypatch.setattr(book, "_write_failed", True)
    with pytest.raises(PaperWorkspaceError):
        book.reconciliation_report()


def test_report_http_is_read_only_and_returns_error_statuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = PaperWorkspace(lambda: NOW, tmp_path / "paper.jsonl")
    server = QuantEngineHttpServer("127.0.0.1", 0, book)
    server.start()
    try:
        url = f"http://127.0.0.1:{server.port}/v1/paper/reconciliation"
        with pytest.raises(HTTPError) as missing:
            urlopen(url)
        assert missing.value.code == 422
        book.create_account(
            {
                "schemaVersion": "paper-terminal-create-account-v1",
                "clientRequestId": "http-report",
                "name": "隔离读取",
                "initialCapital": "100000",
            }
        )
        with urlopen(url) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "MATCHED"
        monkeypatch.setattr(book, "_write_failed", True)
        with pytest.raises(HTTPError) as unavailable:
            urlopen(url)
        assert unavailable.value.code == 503
    finally:
        server.stop()


def test_report_uses_fixed_precision_after_a_valid_fractional_price_buy(tmp_path: Path) -> None:
    from decimal import localcontext

    path = tmp_path / "precision.jsonl"
    book = PaperWorkspace(lambda: NOW, path, controlled_buy_enabled=True)
    book.create_account(
        {
            "schemaVersion": "paper-terminal-create-account-v1",
            "clientRequestId": "precision-account",
            "name": "隔离精度",
            "initialCapital": "100000",
        }
    )
    allocation = book.preview(
        {
            "schemaVersion": "paper-terminal-simulation-v1",
            "clientRequestId": "precision-preview",
            "instrumentId": "600519.SH",
            "price": "100.12345678",
            "score": "0.3",
            "confidence": "1",
            "lotSize": 100,
        }
    )
    book.buy_allocation(allocation)
    expected, before, journal = book.reconciliation_report(), book.snapshot(), path.read_bytes()
    with localcontext() as context:
        context.prec = 10
        assert book.reconciliation_report() == expected
    assert book.snapshot() == before and path.read_bytes() == journal
