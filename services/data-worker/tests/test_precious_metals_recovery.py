"""RED tests for raw-after-crash and commit-before-return recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ashare_contracts.providers import Capability
from data_worker.jobs.precious_metals_funds import FundCollector
from data_worker.raw import LocalFileStorage
from data_worker.storage import InMemoryFundStorage
from market_core.providers import RawFundProviderResponse


def _item() -> dict[str, object]:
    return {
        "unifiedCode": "518880.SH",
        "date": "2026-08-13",
        "nav": "1.2500",
        "eventTime": "2026-08-13T01:00:00+00:00",
        "publishTime": "2026-08-13T02:00:00+00:00",
        "ingestTime": "2026-08-13T03:00:00+00:00",
        "availableTime": "2026-08-13T03:30:00+00:00",
        "processingTime": "2026-08-13T04:00:00+00:00",
        "source": "provider-x",
    }


class Provider:
    def __init__(self, page: RawFundProviderResponse) -> None:
        self.page = page

    def capabilities(self) -> frozenset[Capability]:
        return frozenset({Capability.FETCH_FUND_NAV})

    def require(self, capability: Capability) -> None:
        if capability not in self.capabilities():
            raise NotImplementedError

    def fetch_fund_nav(self, exchange: str, cursor: str | None = None) -> RawFundProviderResponse:
        return self.page


class CrashBeforeCommit(InMemoryFundStorage):
    def commit_page(self, **kwargs: object):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated crash after raw capture")


class CrashAfterCommit(InMemoryFundStorage):
    def __init__(self) -> None:
        super().__init__()
        self.crashed = False

    def commit_page(self, **kwargs: object):  # type: ignore[no-untyped-def]
        result = super().commit_page(**kwargs)  # type: ignore[arg-type]
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("simulated crash after database commit")
        return result


def _page() -> RawFundProviderResponse:
    item = _item()
    payload = json.dumps({"items": [item], "nextCursor": None}, separators=(",", ":")).encode()
    return RawFundProviderResponse(
        body=payload,
        request="GET /funds/nav?exchange=SH",
        capture_id="capture-recovery",
        source="provider-x",
        endpoint_kind="nav",
        run_id="run-recovery",
        source_revision="rev-1",
        ingest_time=datetime(2026, 8, 13, 3, 0, tzinfo=UTC),
        available_time=datetime(2026, 8, 13, 3, 30, tzinfo=UTC),
    )


def _collector(tmp_path: Path, persistence: InMemoryFundStorage) -> FundCollector:
    return FundCollector(
        Provider(_page()),
        LocalFileStorage(tmp_path),
        persistence,
        now=datetime(2026, 8, 13, 5, 0, tzinfo=UTC),
    )


def test_recovery_replays_raw_after_crash_before_database_commit(tmp_path: Path) -> None:
    crashed = _collector(tmp_path, CrashBeforeCommit())
    with pytest.raises(RuntimeError, match="raw capture"):
        crashed.collect("nav", "SH")

    storage = LocalFileStorage(tmp_path)
    manifests = storage.list("provider-x", "2026-08-13")
    assert len(manifests) == 1
    assert manifests[0].attempt_id is not None
    recovered_persistence = InMemoryFundStorage()
    recovered = _collector(tmp_path, recovered_persistence)

    result = recovered.replay_captures(
        "nav",
        "provider-x",
        "2026-08-13",
        run_id="run-recovery",
        source_revision="rev-1",
        attempt_id=manifests[0].attempt_id,
    )

    assert len(result.accepted) == 1
    assert len(recovered_persistence.observations("nav")) == 1


def test_recovery_after_database_commit_before_return_is_idempotent(tmp_path: Path) -> None:
    persistence = CrashAfterCommit()
    crashed = _collector(tmp_path, persistence)
    with pytest.raises(RuntimeError, match="database commit"):
        crashed.collect("nav", "SH")
    assert len(persistence.observations("nav")) == 1
    manifest = LocalFileStorage(tmp_path).list("provider-x", "2026-08-13")[0]
    assert manifest.attempt_id is not None

    recovered = _collector(tmp_path, persistence)
    recovered.replay_captures(
        "nav",
        "provider-x",
        "2026-08-13",
        run_id="run-recovery",
        source_revision="rev-1",
        attempt_id=manifest.attempt_id,
    )

    assert len(persistence.observations("nav")) == 1
